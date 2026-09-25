"""离线验证气流通道：对比开关前后的映射结果 + 扫描 gain。

用实测特征值模拟「冲击」与「呼呼声」，直接喂给 HapticMapper。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.features import ChannelFeatures, FrameFeatures  # noqa: E402
from src.mapping.mapper import HapticMapper, MappingConfig  # noqa: E402


def make_feats(rms, band_low, band_mid, onset, zcr=0.05):
    ch = ChannelFeatures(rms=rms, band_low=band_low, band_mid=band_mid,
                         onset=onset, zcr=zcr, low_boost=min(1.0, band_low * 2.0))
    return FrameFeatures(left=ch,
                         right=ChannelFeatures(**ch.__dict__))


def run(cfg: MappingConfig, feats, warm: int = 40):
    m = HapticMapper(cfg, frame_ms=20.0)
    d = None
    for _ in range(warm):
        d = m.map_frame(feats)
    return d.left, d.right, d.agc_gain, d.airflow


def base_cfg(**over):
    kw = dict(
        curve="log", log_b=30.0, silence_threshold=0.008,
        master_gain=1.0, low_boost_gain=2.2, onset_boost=0.55,
        agc_enabled=True, agc_target=0.75, agc_max_gain=6.0,
        agc_noise_floor=0.0025, agc_attack_ms=120.0, agc_release_ms=500.0,
        soft_clip=True, max_drive=255, max_delta_per_frame=140,
    )
    kw.update(over)
    return MappingConfig(**kw)


# band_mid 实测：静音 <0.001，内容段 0.0022~0.0040
CASES = [
    ("冲击峰值",     0.0140, 0.0258, 0.0035, 1.00),
    ("冲击典型",     0.0076, 0.0114, 0.0030, 1.00),
    ("呼呼声",       0.0038, 0.0080, 0.0029, 0.00),
    ("呼呼声偏弱",   0.0024, 0.0059, 0.0024, 0.00),
    ("背景静默",     0.0000, 0.0000, 0.0005, 0.00),
    ("持续环境声",   0.0030, 0.0070, 0.0025, 0.05),
    ("安静但底噪",   0.0008, 0.0012, 0.0019, 0.00),
]

print("=" * 62)
print("对比：气流通道 关 / 开（airflow_max_drive=150）")
print("=" * 62)
print(f"{'场景':>12} {'开关':>4} {'驱动L':>7} {'AGC':>6} {'气流':>6}")
print("-" * 62)
for name, rms, low, mid, onset in CASES:
    for label, enabled in (("关", False), ("开", True)):
        cfg = base_cfg(use_airflow=enabled, airflow_max_drive=150)
        l, r, agc, air = run(cfg, make_feats(rms, low, mid, onset))
        print(f"{name:>12} {label:>4} {l:>7} {agc:>6.2f} {air:>6}")
    print()

print("=" * 62)
print("扫描 airflow_max_drive：冲击恒定，呼呼声可调")
print("=" * 62)
print(f"{'max_drive':>10} {'冲击峰值':>9} {'呼呼声':>8} {'呼呼/冲击':>10}")
print("-" * 62)
for md in (80, 110, 130, 150, 180, 210):
    cfg = base_cfg(use_airflow=True, airflow_max_drive=md)
    ip, _, _, _ = run(cfg, make_feats(0.014, 0.0258, 0.0035, 1.0))
    wh, _, _, _ = run(cfg, make_feats(0.0038, 0.0080, 0.0029, 0.0))
    print(f"{md:>10} {ip:>9} {wh:>8} {wh/max(1,ip)*100:>9.0f}%")
