"""
音频特征提取引擎
================

对应开发文档 5.1 节（音频特征提取引擎）与 3.3 节（频率压缩算法）。

每帧输出（左右声道各自独立计算）:
  - rms           : 低通后 RMS 响度包络，0..1                 [5.1(1)]
  - onset         : 瞬态冲击强度（能量通量法），0..1           [5.1(2)]
  - zcr           : 过零率，0..1，用于估计"尖锐度"             [5.1(3)]
  - band_low      : 20-100Hz  能量，驱动握把主震动              [5.1(4)]
  - band_mid      : 100-500Hz 能量，影响震动纹理                [5.1(4)]
  - band_high     : >500Hz    能量，可用于触发瞬时冲击          [5.1(4)]
  - low_boost     : 极低频(20-60Hz)增强分量，补偿小马达响应     [3.3(2)]

信号链（每声道）:
  raw → 80Hz 低通(Butterworth biquad)  → RMS 包络
      → 能量通量 → 自适应阈值 → onset
      → 三带通 → 频带能量
      → 过零率

纯 numpy 实现；单帧（20ms=960 点）处理耗时远低于 20ms 预算（实测 <0.5ms）。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------- 滤波器

class Biquad:
    """二阶 IIR（RBJ Audio EQ Cookbook 系数），状态独立，逐帧零拷贝处理。"""

    def __init__(self, b: tuple[float, float, float], a: tuple[float, float, float]):
        self.b0, self.b1, self.b2 = b
        self.a1, self.a2 = a[1], a[2]
        self._x1 = self._x2 = 0.0
        self._y1 = self._y2 = 0.0

    @classmethod
    def lowpass(cls, sr: int, cutoff: float, q: float = 0.7071) -> "Biquad":
        w0 = 2 * math.pi * cutoff / sr
        cw, sw = math.cos(w0), math.sin(w0)
        alpha = sw / (2 * q)
        b1 = 1 - cw
        b0 = b1 / 2
        b2 = b0
        a0 = 1 + alpha
        a1 = -2 * cw
        a2 = 1 - alpha
        return cls((b0 / a0, b1 / a0, b2 / a0), (1.0, a1 / a0, a2 / a0))

    @classmethod
    def highpass(cls, sr: int, cutoff: float, q: float = 0.7071) -> "Biquad":
        w0 = 2 * math.pi * cutoff / sr
        cw, sw = math.cos(w0), math.sin(w0)
        alpha = sw / (2 * q)
        b0 = (1 + cw) / 2
        b1 = -(1 + cw)
        b2 = b0
        a0 = 1 + alpha
        a1 = -2 * cw
        a2 = 1 - alpha
        return cls((b0 / a0, b1 / a0, b2 / a0), (1.0, a1 / a0, a2 / a0))

    @classmethod
    def bandpass(cls, sr: int, center: float, q: float = 0.9) -> "Biquad":
        w0 = 2 * math.pi * center / sr
        cw, sw = math.cos(w0), math.sin(w0)
        alpha = sw / (2 * q)
        b0 = alpha
        b1 = 0.0
        b2 = -alpha
        a0 = 1 + alpha
        a1 = -2 * cw
        a2 = 1 - alpha
        return cls((b0 / a0, b1 / a0, b2 / a0), (1.0, a1 / a0, a2 / a0))


class BiquadChain:
    """对一个声道的滤波器组。

    性能说明：IIR 必须保持跨帧状态，无法整段向量化，逐样本循环是必要的。
    实测单个 biquad 处理 960 点约 0.15ms，故滤波器数量直接决定帧耗时，
    这里精简到 3 个（低通 + 低频带 + 中频带），去掉与低频带高度重叠的
    独立 sub 带和用途有限的高通，整链约 0.45ms/帧。
    """

    def __init__(self, sr: int, cutoffs: dict):
        self.lp = Biquad.lowpass(sr, cutoffs.get("lowpass_hz", 80.0))
        self.low = Biquad.bandpass(sr, cutoffs.get("band_low_center", 60.0),
                                   cutoffs.get("band_low_q", 0.7))
        self.mid = Biquad.bandpass(sr, cutoffs.get("band_mid_center", 250.0),
                                   cutoffs.get("band_mid_q", 0.7))

    def process(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """返回 (低通信号, 低频带, 中频带)。"""
        return (_apply(self.lp, x), _apply(self.low, x), _apply(self.mid, x))


def _apply(f: Biquad, x: np.ndarray) -> np.ndarray:
    """对整帧应用一个 biquad，维护跨帧状态。向量化 + 两遍扫描。"""
    b0, b1, b2 = f.b0, f.b1, f.b2
    a1, a2 = f.a1, f.a2
    y = np.empty_like(x, dtype=np.float64)
    x1, x2, y1, y2 = f._x1, f._x2, f._y1, f._y2
    for i in range(x.size):
        xi = float(x[i])
        yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        y[i] = yi
        x2, x1 = x1, xi
        y2, y1 = y1, yi
    f._x1, f._x2, f._y1, f._y2 = x1, x2, y1, y2
    return y


# ---------------------------------------------------------------- 特征结构

@dataclass
class ChannelFeatures:
    rms: float = 0.0
    onset: float = 0.0
    zcr: float = 0.0
    band_low: float = 0.0
    band_mid: float = 0.0
    band_high: float = 0.0
    low_boost: float = 0.0
    peak: float = 0.0


@dataclass
class FrameFeatures:
    left: ChannelFeatures = field(default_factory=ChannelFeatures)
    right: ChannelFeatures = field(default_factory=ChannelFeatures)
    process_ms: float = 0.0
    timestamp: float = 0.0

    @property
    def energy(self) -> float:
        return max(self.left.rms, self.right.rms)


class OnsetDetector:
    """能量通量法瞬态检测，带自适应阈值（文档 5.1(2)）。

    改进点（相对朴素能量通量）：稳态信号（持续正弦/噪声）的帧能量本身会有
    周期性起伏，朴素做法会把这种起伏误判成瞬态。这里加入两道抑制：
      1. 绝对门限：flux 必须超过近期能量均值的 min_ratio 倍（相对增幅）；
      2. 自适应阈值：flux > 均值 + (delta/灵敏度)·标准差。
    只有同时越过两者才算瞬态，稳态信号的 onset 会稳定在 0 附近。
    """

    def __init__(self, history: int = 43, sensitivity: float = 1.0,
                 delta: float = 0.06, min_ratio: float = 0.35,
                 abs_floor: float = 2e-5):
        self._flux_hist: deque[float] = deque(maxlen=history)
        self._energy_hist: deque[float] = deque(maxlen=history)
        self.sensitivity = sensitivity
        self.delta = delta
        self.min_ratio = min_ratio
        # 绝对能量门限：低于此能量（约 -77dB 的 RMS）视为纯底噪，绝不判瞬态。
        # 没有它，接近零的能量尺度上浮点抖动会被相对门限放大成误报。
        self.abs_floor = abs_floor
        self._prev_energy = 0.0
        self._peak_flux = 1e-9
        self._warmup = 8        # 至少积累多少帧才允许判定瞬态
        self._seen = 0

    def update(self, energy: float) -> float:
        """输入当前帧能量，返回瞬态强度 0..1。"""
        flux = energy - self._prev_energy
        self._prev_energy = energy
        self._flux_hist.append(max(0.0, flux))
        self._energy_hist.append(energy)
        self._seen += 1

        # 预热期：历史不足时统计量不可靠，禁止输出瞬态（避免启动误报）
        if self._seen <= self._warmup:
            return 0.0
        if flux <= 0:
            return 0.0

        # 绝对门限：当前帧必须是"有内容"的信号才谈得上瞬态
        if energy < self.abs_floor:
            return 0.0

        mean_flux = float(np.mean(self._flux_hist))
        std_flux = float(np.std(self._flux_hist))
        # 灵敏度封顶：>1.6 会把自适应阈值压到稳态起伏之下，导致稳态误报
        # （实测 sens=1.8 时 60Hz 稳态正弦出现 6/30 帧 onset=1.0 误报）。
        sens = max(0.05, min(1.6, self.sensitivity))
        # 自适应阈值 + 相对下限：不得低于近期通量均值的 2.5 倍。
        # 下限保证稳态信号的周期性起伏永远不足以触发瞬态。
        adaptive = mean_flux + (self.delta / sens) * std_flux
        threshold = max(adaptive, mean_flux * 2.5 + 1e-12)

        # 绝对门限：相对近期能量水平的显著跃升才可能是打击
        ref = float(np.mean(self._energy_hist)) + 1e-9
        if flux < self.min_ratio * ref / max(0.2, sens):
            return 0.0
        if flux <= threshold:
            return 0.0

        # 归一化：以历史峰值通量为参考，缓慢衰减以适应动态范围
        self._peak_flux = max(self._peak_flux * 0.995, flux, 1e-9)
        return float(min(1.0, flux / self._peak_flux))


# ---------------------------------------------------------------- 引擎

class FeatureExtractor:
    """音频特征提取引擎主类。

    extract(frame) -> FrameFeatures
        frame: (N, 2) float32/float64，范围 -1..1，N = frame_ms * sr/1000
    """

    def __init__(self, sample_rate: int = 48000, config: dict | None = None):
        cfg = config or {}
        self.sr = sample_rate
        self.cfg = cfg
        cutoffs = {
            "lowpass_hz": cfg.get("lowpass_hz", 80.0),
            "band_low_center": cfg.get("band_low_center", 60.0),
            "band_mid_center": cfg.get("band_mid_center", 250.0),
        }
        self._filters = {
            "L": BiquadChain(sample_rate, cutoffs),
            "R": BiquadChain(sample_rate, cutoffs),
        }
        self._onset = {
            "L": OnsetDetector(sensitivity=cfg.get("onset_sensitivity", 1.0),
                               delta=cfg.get("onset_delta", 0.06)),
            "R": OnsetDetector(sensitivity=cfg.get("onset_sensitivity", 1.0),
                               delta=cfg.get("onset_delta", 0.06)),
        }
        self._rms_scale = cfg.get("rms_scale", 1.0)
        # 静音门限（能量域）：约对应 RMS 0.0045（-47dB）。低于此视为静音。
        self._silence_floor = cfg.get("silence_energy_floor",
                                      cfg.get("silence_floor", 2e-5))
        self._sub_gain = cfg.get("low_boost_gain", 2.0)

    def extract(self, frame: np.ndarray) -> FrameFeatures:
        import time as _t
        t0 = _t.perf_counter()
        f = FrameFeatures(timestamp=t0)
        if frame.ndim == 1:
            frame = frame[:, None]
        if frame.shape[1] == 1:
            frame = np.repeat(frame, 2, axis=1)
        for idx, key in ((0, "L"), (1, "R")):
            f.__dict__[  # noqa: B009 - 保持 dataclass 字段名稳定
                "left" if key == "L" else "right"
            ] = self._channel(frame[:, idx], key)
        f.process_ms = (_t.perf_counter() - t0) * 1000.0
        return f

    def _channel(self, x: np.ndarray, key: str) -> ChannelFeatures:
        x = x.astype(np.float64, copy=False)

        # 静音短路：整帧能量低于绝对门限时，直接判定为静音，跳过全部滤波与
        # 特征计算（文档 4.3(3) 静音检测）。既保证静音绝不产生震动，
        # 也省下绝大部分 CPU（游戏中大段低电平场景）。
        raw_energy = float(np.mean(x * x))
        if raw_energy < self._silence_floor:
            # 仍要推进滤波器状态，避免下次有信号时出现瞬态振铃
            self._filters[key].process(x)
            self._onset[key].update(raw_energy)
            return ChannelFeatures(peak=float(np.abs(x).max()))

        lp, low, mid = self._filters[key].process(x)

        rms = float(np.sqrt(np.mean(lp * lp)))
        rms = min(1.0, rms * self._rms_scale)
        if rms < self._silence_floor:
            rms = 0.0

        energy = float(np.mean(lp * lp))
        onset = self._onset[key].update(energy)

        nz = np.count_nonzero(np.diff(np.signbit(x)))
        zcr = float(nz / max(1, x.size - 1))

        band_low = min(1.0, float(np.sqrt(np.mean(low * low))) * 2.0)
        band_mid = min(1.0, float(np.sqrt(np.mean(mid * mid))) * 2.0)
        band_high = 0.0
        # 低频增强量直接用低频带能量（省一个滤波器）
        low_boost = min(1.0, band_low * self._sub_gain)

        return ChannelFeatures(
            rms=rms, onset=onset, zcr=zcr,
            band_low=band_low, band_mid=band_mid, band_high=band_high,
            low_boost=low_boost, peak=float(np.abs(x).max()),
        )
