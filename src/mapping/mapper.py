"""
映射层 — 音频特征 → 马达驱动强度
==================================

对应开发文档 3.2（振动强度映射表）、5.2（震动指令编码 / ADSR / 左右声道差异化）、
4.3(3)(4)（静音阈值、AGC、防削波）、6.2（用户可调参数与预设）。

映射管线（每声道独立）:
  特征(0..1) → 静音阈值门限 → 对数/指数曲线 → 低频增强加权
            → AGC 平滑 → 全局强度缩放 → 防削波 → ADSR 包络 → 0..255

关键公式（文档 3.2(2)）:
  output = a * log(b * input + 1) + c
本实现取 a/b 归一化，使 input=1 时 output≈1：
  norm_log(x) = log(b*x + 1) / log(b + 1)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 映射曲线


def map_linear(x: float) -> float:
    """线性映射（文档 3.2(1)，实现简单但体验差）。"""
    return max(0.0, min(1.0, x))


def map_log(x: float, b: float = 12.0) -> float:
    """对数映射（文档 3.2(2)，推荐）。b 越大，弱信号抬升越明显。"""
    x = max(0.0, min(1.0, x))
    b = max(1.0001, b)
    return math.log(b * x + 1.0) / math.log(b + 1.0)


def map_exp(x: float, p: float = 2.0) -> float:
    """指数映射（文档 3.2(3)，增强中高强度，适合动作游戏）。"""
    x = max(0.0, min(1.0, x))
    return x ** max(0.1, p)


CURVES = {"linear": map_linear, "log": map_log, "exp": map_exp}


# ---------------------------------------------------------------- ADSR


@dataclass
class AdsrEnvelope:
    """ADSR 振幅包络（文档 5.2(3)）。时间单位 ms，按帧长推进。

    阶段: attack → decay → sustain → release → idle
    target 是曲线算出的"当前目标强度"，包络向它逼近，避免突变爆音。
    """
    attack_ms: float = 10.0
    decay_ms: float = 30.0
    sustain_level: float = 0.85
    release_ms: float = 20.0
    frame_ms: float = 20.0

    _value: float = field(default=0.0, init=False)
    _stage: str = field(default="idle", init=False)
    _stage_elapsed_ms: float = field(default=0.0, init=False)
    _target: float = field(default=0.0, init=False)
    _peak: float = field(default=0.0, init=False)

    def step(self, target: float) -> float:
        """推进一帧，返回当前包络输出（0..1）。"""
        target = max(0.0, min(1.0, target))
        self._target = target
        dt = self.frame_ms

        if target > self._value:
            # 上升 → attack（快速逼近新目标）
            if self._stage != "attack":
                self._stage = "attack"
                self._stage_elapsed_ms = 0.0
                self._peak = target
            self._peak = max(self._peak, target)
            self._value = self._approach(self._value, self._peak,
                                         self.attack_ms, dt)
        else:
            # 下降 → release
            if self._stage != "release":
                self._stage = "release"
                self._stage_elapsed_ms = 0.0
            self._value = self._approach(self._value, target,
                                         self.release_ms, dt)
        self._stage_elapsed_ms += dt
        if self._value < 1e-4 and target < 1e-4:
            self._value = 0.0
            self._stage = "idle"
        return self._value

    @staticmethod
    def _approach(cur: float, goal: float, tau_ms: float, dt_ms: float) -> float:
        """指数逼近：一阶低通，tau 为时间常数(ms)。"""
        tau = max(0.5, tau_ms)
        k = 1.0 - math.exp(-dt_ms / tau)
        return cur + (goal - cur) * k

    def reset(self) -> None:
        self._value = 0.0
        self._stage = "idle"
        self._target = 0.0
        self._peak = 0.0
        self._stage_elapsed_ms = 0.0

    @property
    def value(self) -> float:
        return self._value


# ---------------------------------------------------------------- 映射器


@dataclass
class MappingConfig:
    """用户可调参数（文档 6.2）。"""
    curve: str = "log"
    log_b: float = 12.0
    exp_p: float = 2.0
    silence_threshold: float = 0.02     # 静音阈值 6.2(4)
    master_gain: float = 1.0            # 全局强度 6.2(1)
    left_gain: float = 1.0              # 左右声道权重 3.2(4)
    right_gain: float = 1.0
    low_boost_gain: float = 1.0         # 低频增强 3.3(2)
    onset_boost: float = 0.35           # 瞬态对输出的额外贡献
    agc_enabled: bool = True            # 自动增益 4.3(3)
    agc_target: float = 0.55            # AGC 目标 RMS
    agc_max_gain: float = 3.0
    agc_attack_ms: float = 200.0        # AGC 增益上升要慢
    agc_release_ms: float = 800.0       # AGC 增益下降要更慢
    agc_noise_floor: float = 0.008      # 低于此电平视为底噪，AGC 不放大
    soft_clip: bool = True              # 防削波 4.3(4)
    max_drive: int = 230                # 马达最大安全驱动 3.1(3)
    min_drive: int = 0                  # 最小触发阈值 3.1(2)
    max_delta_per_frame: int = 90       # 单帧最大变化量，抑制马达爆音
    use_onset: bool = True
    use_bands: bool = True

    # --- 气流/摩擦通道（呼呼声等「有持续能量但无瞬态」的宽带噪声）---
    # 绕过曲线/AGC/ADSR，直接给出驱动目标，力度与冲击峰值解耦、可精确标定。
    # 实测 band_mid 量级：静音<0.001，普通内容 0.0022~0.0040（中位 0.0029）。
    use_airflow: bool = True
    airflow_max_drive: int = 180        # 气流分量能达到的最大驱动（冲击峰值约 190~240）
    airflow_onset_max: float = 0.35     # onset 超过此值视为冲击，不走气流通道
    airflow_floor: float = 0.0018       # band_mid 低于此视为无气流，防止底噪起振
    airflow_span: float = 0.0014        # mid 从 floor 到满量程的跨度（实测 0.0022~0.0040）

    def curve_fn(self):
        fn = CURVES.get(self.curve, map_log)
        if self.curve == "log":
            return lambda x: fn(x, self.log_b)
        if self.curve == "exp":
            return lambda x: fn(x, self.exp_p)
        return fn


@dataclass
class DriveOutput:
    left: int = 0
    right: int = 0
    left_norm: float = 0.0
    right_norm: float = 0.0
    agc_gain: float = 1.0
    transient: bool = False
    airflow: float = 0.0       # 本帧气流通道贡献（0=未走，>0=走的补偿强度）


class HapticMapper:
    """特征 → 马达驱动强度（含 ADSR 与 AGC）。"""

    def __init__(self, cfg: MappingConfig | None = None, frame_ms: float = 20.0):
        self.cfg = cfg or MappingConfig()
        self.frame_ms = frame_ms
        self._env = {
            "L": AdsrEnvelope(frame_ms=frame_ms),
            "R": AdsrEnvelope(frame_ms=frame_ms),
        }
        self._agc_gain = 1.0
        self._prev_out = {"L": 0.0, "R": 0.0}
        self._curve = self.cfg.curve_fn()
        self._last_airflow = 0.0

    def set_config(self, cfg: MappingConfig) -> None:
        self.cfg = cfg
        self._curve = cfg.curve_fn()

    def set_envelope(self, attack_ms=None, decay_ms=None, sustain_level=None,
                     release_ms=None) -> None:
        """运行时调整 ADSR 参数（预设切换 / 用户调参用）。"""
        for e in self._env.values():
            if attack_ms is not None:
                e.attack_ms = max(0.5, attack_ms)
            if decay_ms is not None:
                e.decay_ms = max(0.5, decay_ms)
            if sustain_level is not None:
                e.sustain_level = max(0.0, min(1.0, sustain_level))
            if release_ms is not None:
                e.release_ms = max(0.5, release_ms)

    def map_frame(self, feats) -> DriveOutput:
        cfg = self.cfg
        self._last_airflow = 0.0
        l_norm, l_air = self._channel_norm(feats.left, "L")
        r_norm, r_air = self._channel_norm(feats.right, "R")
        airflow = max(l_air, r_air)

        if cfg.agc_enabled:
            l_norm, r_norm = self._apply_agc(l_norm, r_norm)

        l_norm = min(1.0, l_norm * cfg.master_gain * cfg.left_gain)
        r_norm = min(1.0, r_norm * cfg.master_gain * cfg.right_gain)

        if cfg.soft_clip:
            l_norm = self._soft_clip(l_norm)
            r_norm = self._soft_clip(r_norm)

        # 静音阈值：低于门限直接归零（避免底噪微震）4.3(3)
        if max(l_norm, r_norm) < cfg.silence_threshold:
            l_norm = r_norm = 0.0

        l_env = self._env["L"].step(l_norm)
        r_env = self._env["R"].step(r_norm)

        l_out = self._to_drive(l_env, "L")
        r_out = self._to_drive(r_env, "R")

        # 气流分量绕过包络/限速，直接以驱动值取大（自带绝对标定，
        # 力度与冲击峰值解耦，可精确控制比例）
        l_out = max(l_out, l_air)
        r_out = max(r_out, r_air)

        return DriveOutput(
            left=l_out, right=r_out,
            left_norm=l_env, right_norm=r_env,
            agc_gain=self._agc_gain,
            transient=feats.left.onset > 0.35 or feats.right.onset > 0.35,
            airflow=airflow,
        )

    # ---------- 内部 ----------

    def _channel_norm(self, ch, key: str) -> float:
        cfg = self.cfg
        base = ch.rms
        if cfg.use_bands and ch.band_low > 0:
            # 低频带能量为主，RMS 为辅（转子马达主要响应低频）
            base = 0.65 * ch.rms + 0.35 * ch.band_low
        if cfg.low_boost_gain != 1.0:
            base = base * (1.0 + (cfg.low_boost_gain - 1.0) * ch.low_boost)
        x = self._curve(max(0.0, min(1.0, base)))
        if cfg.use_onset and ch.onset > 0:
            x = min(1.0, x + cfg.onset_boost * ch.onset * (1.0 - x))

        # --- 气流/摩擦通道 ---
        # 症状：呼呼声这类"宽带持续噪声"没有瞬态、低频也不突出，走主路径只会
        # 得到 30~68 的微震。
        #
        # 为什么不做成"归一化强度再取 max"：主路径经过 log_b=30 曲线后，
        # 弱信号也会被抬到归一 0.2+，气流的归一值反被吞掉（实测 gain 拉到 0.6
        # 也只从 66 涨到 76）。因此气流分量**绕过曲线/AGC/ADSR 全链路**，
        # 直接给出 0..255 的驱动目标，由 airflow_max_drive 精确标定，
        # 这样它的力度与冲击峰值彻底解耦、可独立控制在任意比例。
        air_drive = 0
        if cfg.use_airflow and ch.onset < cfg.airflow_onset_max:
            mid = ch.band_mid
            if mid > cfg.airflow_floor:
                # 无瞬态程度：onset 越小越接近纯气流（0..1）
                steady = 1.0 - min(1.0, ch.onset / max(1e-6, cfg.airflow_onset_max))
                # 中频能量 → 0..1（实测内容段 0.0022~0.0040）
                mid_norm = min(1.0, (mid - cfg.airflow_floor)
                               / max(1e-6, cfg.airflow_span))
                air_drive = int(mid_norm * (0.55 + 0.45 * steady)
                                * cfg.airflow_max_drive)

        return max(0.0, min(1.0, x)), air_drive

    def _apply_agc(self, l: float, r: float) -> tuple[float, float]:
        """自动增益控制（文档 4.3(3)）。

        关键约束：**AGC 不得把底噪放大成震动**。若当前电平低于一个绝对下限
        （noise_floor），说明是底噪/静音而非真实内容，此时不拉升增益、并把
        增益缓慢回落到 1.0，避免"静音段被放大成持续震动"。
        """
        cfg = self.cfg
        level = max(l, r)

        if level < cfg.agc_noise_floor:
            # 视为静音：不放大，增益缓慢回归 1.0
            k = 1.0 - math.exp(-self.frame_ms / max(1.0, cfg.agc_release_ms))
            self._agc_gain += (1.0 - self._agc_gain) * k
            return l * self._agc_gain, r * self._agc_gain

        desired = cfg.agc_target / level
        desired = max(1.0 / cfg.agc_max_gain, min(cfg.agc_max_gain, desired))
        tau = cfg.agc_release_ms if desired < self._agc_gain else cfg.agc_attack_ms
        k = 1.0 - math.exp(-self.frame_ms / max(1.0, tau))
        self._agc_gain += (desired - self._agc_gain) * k
        return min(1.0, l * self._agc_gain), min(1.0, r * self._agc_gain)

    @staticmethod
    def _soft_clip(x: float) -> float:
        """tanh 软削波：x<0.7 近乎线性，高段平滑压限。"""
        if x <= 0.7:
            return x
        return 0.7 + 0.3 * math.tanh((x - 0.7) / 0.3)

    def _to_drive(self, norm: float, key: str) -> int:
        cfg = self.cfg
        if norm <= 0.0:
            self._prev_out[key] = 0.0
            return 0
        raw = cfg.min_drive + norm * (cfg.max_drive - cfg.min_drive)
        # 单帧限速，抑制马达突变噪音
        prev = self._prev_out[key]
        delta = cfg.max_delta_per_frame
        if raw > prev + delta:
            raw = prev + delta
        elif raw < prev - delta:
            raw = prev - delta
        self._prev_out[key] = raw
        return int(max(cfg.min_drive, min(cfg.max_drive, round(raw))))

    def reset(self) -> None:
        for e in self._env.values():
            e.reset()
        self._agc_gain = 1.0
        self._prev_out = {"L": 0.0, "R": 0.0}
