"""
算法与映射层单元测试（pytest 或直接运行）
=========================================

覆盖:
  - 80Hz 低通对高频的抑制（文档 3.3(1)）
  - RMS 对音量的单调性（文档 5.1(1)）
  - 瞬态检测的命中与稳态抑制（文档 5.1(2)）
  - 对数/指数/线性映射曲线的边界与单调性（文档 3.2）
  - ADSR 包络的起振/释放时间特性（文档 5.2(3)）
  - 左右声道差异映射（文档 3.2(4)）
  - 静音阈值与防削波（文档 4.3(3)(4)）
  - 驱动值范围与限速（文档 3.1(2)(3)）

直接运行:  python tests/test_algorithm.py
或 pytest:  pytest tests/ -v
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.analysis.features import FeatureExtractor  # noqa: E402
from src.mapping.mapper import (  # noqa: E402
    AdsrEnvelope, HapticMapper, MappingConfig, map_exp, map_linear, map_log,
)

SR = 48000
FRAME_MS = 20
N = SR * FRAME_MS // 1000


def _frames(ext: FeatureExtractor, fn, count: int, warm: int = 8):
    """连续喂 count 帧，返回 warm 之后的 (rms, onset) 数组。"""
    rows = []
    for i in range(count):
        x = fn(i)
        f = ext.extract(np.repeat(np.asarray(x)[:, None], 2, axis=1))
        if i >= warm:
            rows.append((f.left.rms, f.left.onset))
    return np.array(rows) if rows else np.zeros((0, 2))


def t_lowpass_rejects_high():
    """高频信号经 80Hz 低通后 RMS 应接近 0。"""
    ext = FeatureExtractor(SR, {"lowpass_hz": 80.0})
    t = np.arange(N) / SR
    # 2kHz 强信号
    r = _frames(ext, lambda i: 0.8 * np.sin(2 * np.pi * 2000 * (i * FRAME_MS / 1000 + t)), 30)
    assert r[:, 0].mean() < 0.01, f"2kHz 未被滤除，RMS={r[:,0].mean():.4f}"
    # 8kHz 应更彻底
    ext2 = FeatureExtractor(SR, {"lowpass_hz": 80.0})
    r2 = _frames(ext2, lambda i: 0.8 * np.sin(2 * np.pi * 8000 * (i * FRAME_MS / 1000 + t)), 30)
    assert r2[:, 0].mean() < 0.003, f"8kHz 未被滤除，RMS={r2[:,0].mean():.4f}"
    return True


def t_lowpass_passes_low():
    """60Hz 信号应基本无衰减通过。"""
    ext = FeatureExtractor(SR, {"lowpass_hz": 80.0})
    t = np.arange(N) / SR
    r = _frames(ext, lambda i: 0.5 * np.sin(2 * np.pi * 60 * (i * FRAME_MS / 1000 + t)), 30)
    assert r[:, 0].mean() > 0.25, f"60Hz 被过度衰减，RMS={r[:,0].mean():.4f}"
    return True


def t_rms_monotonic():
    """RMS 应随输入幅度单调递增。"""
    t = np.arange(N) / SR
    vals = []
    for amp in (0.01, 0.05, 0.15, 0.4, 0.8):
        ext = FeatureExtractor(SR, {"lowpass_hz": 80.0})
        r = _frames(ext, lambda i, a=amp: a * np.sin(2 * np.pi * 60 * (i * FRAME_MS / 1000 + t)), 25)
        vals.append(r[:, 0].mean())
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)), f"RMS 非单调: {vals}"
    return True


def t_onset_steady_suppressed():
    """稳态信号不应触发瞬态。"""
    t = np.arange(N) / SR
    for freq in (60.0, 200.0, 1000.0):
        ext = FeatureExtractor(SR, {"onset_sensitivity": 1.4})
        r = _frames(ext, lambda i, f=freq: 0.6 * np.sin(2 * np.pi * f * (i * FRAME_MS / 1000 + t)), 40)
        assert r[:, 1].max() < 0.1, f"{freq}Hz 稳态误报 onset={r[:,1].max():.3f}"
    return True


def t_onset_detects_impact():
    """静音后的冲击应被检测为瞬态。"""
    ext = FeatureExtractor(SR, {"onset_sensitivity": 1.4})
    k = np.arange(N)
    hits = []
    for i in range(20):
        if i < 10:
            x = np.zeros(N)
        else:
            x = 0.7 * np.exp(-k / (SR * 0.005)) * np.sin(2 * np.pi * 65 * k / SR)
        f = ext.extract(np.repeat(x[:, None], 2, axis=1))
        hits.append(f.left.onset)
    assert hits[10] > 0.5, f"冲击帧未检出瞬态 onset={hits[10]:.3f}"
    assert max(hits[11:]) < 0.2, f"冲击后持续误报 onset={max(hits[11:]):.3f}"
    return True


def t_mapping_curves():
    """三条映射曲线：边界正确、单调、log 抬升弱信号。"""
    assert map_linear(0.0) == 0.0 and abs(map_linear(1.0) - 1.0) < 1e-9
    assert map_log(0.0) == 0.0 and abs(map_log(1.0) - 1.0) < 1e-9
    assert map_exp(0.0) == 0.0 and abs(map_exp(1.0) - 1.0) < 1e-9
    # 单调
    for fn in (map_linear, map_log, lambda x: map_exp(x, 2.0)):
        ys = [fn(x) for x in np.linspace(0, 1, 20)]
        assert all(ys[i] <= ys[i + 1] + 1e-12 for i in range(len(ys) - 1)), "曲线非单调"
    # log 在弱信号处显著高于线性（文档 3.2(2) 的核心目的）
    assert map_log(0.05) > map_linear(0.05) * 2, "log 未抬升弱信号"
    # exp(p=2) 在弱信号处低于线性
    assert map_exp(0.3, 2.0) < map_linear(0.3), "exp 未压制弱信号"
    return True


def t_adsr_attack_release():
    """ADSR 起振应在 attack 时间内接近目标；释放应在 release 时间内回落。"""
    e = AdsrEnvelope(attack_ms=10.0, release_ms=20.0, frame_ms=20.0)
    # 一帧 20ms，attack 10ms → 一帧内应接近目标
    v1 = e.step(1.0)
    assert v1 > 0.8, f"attack 一帧后仅到 {v1:.3f}"
    # 持续输入保持高位
    for _ in range(5):
        v = e.step(1.0)
    assert v > 0.9, f"持续输入未维持高位 {v:.3f}"
    # 归零后应在约 release 时间内衰落到低位
    for _ in range(4):
        v = e.step(0.0)
    assert v < 0.1, f"release 后仍为 {v:.3f}"
    return True


def t_mapping_silence_threshold():
    """低于静音阈值的输入应输出 0（防止底噪微震）。"""
    cfg = MappingConfig(silence_threshold=0.05, master_gain=1.0,
                        agc_enabled=False, curve="linear")
    m = HapticMapper(cfg, frame_ms=FRAME_MS)

    class _Ch:
        rms = 0.01; onset = 0.0; zcr = 0.0
        band_low = 0.0; band_mid = 0.0; band_high = 0.0; low_boost = 0.0; peak = 0.01

    class _F:
        left = _Ch(); right = _Ch()
    d = m.map_frame(_F())
    assert d.left == 0 and d.right == 0, f"静音阈值失效: {d}"
    return True


def t_mapping_soft_clip():
    """软削波不应超过 1.0，且大信号被压缩。"""
    m = HapticMapper(MappingConfig(soft_clip=True), frame_ms=FRAME_MS)
    assert m._soft_clip(1.0) <= 1.0
    assert m._soft_clip(0.5) == 0.5          # 线性区
    assert m._soft_clip(1.0) < 1.0           # 压缩
    seq = [m._soft_clip(x) for x in np.linspace(0, 1.5, 30)]
    assert all(seq[i] <= seq[i + 1] + 1e-12 for i in range(len(seq) - 1)), "削波非单调"
    return True


def t_mapping_limits_and_slew():
    """驱动值应在 [min_drive, max_drive] 内，且单帧变化受限速约束。"""
    cfg = MappingConfig(min_drive=10, max_drive=200, max_delta_per_frame=40,
                        master_gain=1.0, agc_enabled=False, curve="linear",
                        silence_threshold=0.0)
    m = HapticMapper(cfg, frame_ms=FRAME_MS)

    class _Ch:
        def __init__(self, rms): self.rms = rms; self.onset = 0.0; self.zcr = 0.0
        band_low = band_mid = band_high = low_boost = 0.0
        peak = 0.0

    class _F:
        def __init__(self, rms): self.left = _Ch(rms); self.right = _Ch(rms)

    # 从 0 直接跳到满：第一帧应受 slew 限制
    first = m.map_frame(_F(1.0))
    assert first.left <= 10 + cfg.max_delta_per_frame, f"首帧未限速 {first.left}"
    # 持续推进到上限
    for _ in range(30):
        d = m.map_frame(_F(1.0))
    assert cfg.min_drive <= d.left <= cfg.max_drive, f"驱动越界 {d.left}"
    return True


def t_channel_independence():
    """左右声道应独立映射（左强右弱）。"""
    cfg = MappingConfig(agc_enabled=False, curve="linear", master_gain=1.0,
                        silence_threshold=0.0, left_gain=1.0, right_gain=1.0,
                        max_delta_per_frame=255)
    m = HapticMapper(cfg, frame_ms=FRAME_MS)

    class _Ch:
        def __init__(self, rms): self.rms = rms; self.onset = 0.0; self.zcr = 0.0
        band_low = band_mid = band_high = low_boost = 0.0
        peak = 0.0

    class _F:
        left = _Ch(0.9); right = _Ch(0.05)

    d = m.map_frame(_F())
    assert d.left > d.right * 3, f"左右未独立映射 L={d.left} R={d.right}"
    return True


def t_pipeline_perf():
    """单帧分析+映射耗时须显著低于 20ms 帧预算（文档 6.1 延迟预算）。"""
    ext = FeatureExtractor(SR, {"onset_sensitivity": 1.4})
    m = HapticMapper(MappingConfig(), frame_ms=FRAME_MS)
    rng = np.random.default_rng(1)
    frame = (0.3 * rng.standard_normal(N)).astype(np.float32)
    stereo = np.repeat(frame[:, None], 2, axis=1)
    # 预热
    for _ in range(5):
        m.map_frame(ext.extract(stereo))
    t0 = time.perf_counter()
    iters = 50
    for _ in range(iters):
        m.map_frame(ext.extract(stereo))
    per_ms = (time.perf_counter() - t0) / iters * 1000
    print(f"      [perf] 单帧 分析+映射 = {per_ms:.3f} ms（预算 {FRAME_MS}ms）")
    assert per_ms < FRAME_MS * 0.5, f"单帧耗时 {per_ms:.2f}ms 过高"
    return True


TESTS = [
    ("80Hz 低通抑制高频", t_lowpass_rejects_high),
    ("低通通过 60Hz 低频", t_lowpass_passes_low),
    ("RMS 随音量单调", t_rms_monotonic),
    ("稳态信号不触发瞬态", t_onset_steady_suppressed),
    ("冲击被检出为瞬态", t_onset_detects_impact),
    ("映射曲线边界与单调", t_mapping_curves),
    ("ADSR 起振/释放", t_adsr_attack_release),
    ("静音阈值归零", t_mapping_silence_threshold),
    ("软削波压缩", t_mapping_soft_clip),
    ("驱动范围与限速", t_mapping_limits_and_slew),
    ("左右声道独立映射", t_channel_independence),
    ("单帧处理性能", t_pipeline_perf),
]


def main() -> int:
    print("=" * 66)
    print("  Flydigi 中间层 — 算法与映射层测试")
    print("=" * 66)
    failed = 0
    for name, fn in TESTS:
        try:
            ok = fn()
            print(f"  ✓ {name}" + ("" if ok else "  (返回非真)"))
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {name}\n      {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}\n      {type(e).__name__}: {e}")
    print("-" * 66)
    print(f"  结果: {len(TESTS) - failed}/{len(TESTS)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
