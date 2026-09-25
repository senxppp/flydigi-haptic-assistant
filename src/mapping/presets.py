"""预设配置（文档 6.2(5)：动作 / 赛车 / 音乐 / 自定义）。"""

from __future__ import annotations

from .mapper import MappingConfig

# 文档 6.2(5) 四种预设
PRESETS: dict[str, dict] = {
    "action": {
        "label": "动作游戏模式",
        "desc": "高强度、高瞬态敏感度、快速 ADSR",
        "mapping": {
            "curve": "log", "log_b": 14.0,
            "silence_threshold": 0.02, "master_gain": 1.0,
            "onset_boost": 0.5, "low_boost_gain": 1.4,
            "agc_enabled": True, "max_drive": 240,
            "soft_clip": True,
        },
        "analysis": {"onset_sensitivity": 1.4, "lowpass_hz": 85.0},
        "envelope": {"attack_ms": 6.0, "decay_ms": 20.0, "release_ms": 12.0},
    },
    "racing": {
        "label": "赛车游戏模式",
        "desc": "中强度、低频增强、平滑包络",
        "mapping": {
            "curve": "log", "log_b": 8.0,
            "silence_threshold": 0.015, "master_gain": 0.85,
            "onset_boost": 0.15, "low_boost_gain": 2.4,
            "agc_enabled": True, "max_drive": 210,
            "soft_clip": True,
        },
        "analysis": {"onset_sensitivity": 0.7, "lowpass_hz": 70.0},
        "envelope": {"attack_ms": 40.0, "decay_ms": 80.0, "release_ms": 90.0},
    },
    "music": {
        "label": "音乐游戏模式",
        "desc": "高保真、宽频带响应、精确瞬态",
        "mapping": {
            "curve": "exp", "exp_p": 1.6,
            "silence_threshold": 0.025, "master_gain": 0.95,
            "onset_boost": 0.35, "low_boost_gain": 1.1,
            "agc_enabled": False, "max_drive": 220,
            "soft_clip": True,
        },
        "analysis": {"onset_sensitivity": 1.8, "lowpass_hz": 100.0},
        "envelope": {"attack_ms": 4.0, "decay_ms": 25.0, "release_ms": 18.0},
    },
    "custom": {
        "label": "自定义模式",
        "desc": "所有参数手动调节",
        "mapping": {}, "analysis": {}, "envelope": {},
    },
}

DEFAULT_PRESET = "action"


def build_config(preset: str = DEFAULT_PRESET, overrides: dict | None = None
                 ) -> tuple[MappingConfig, dict, dict]:
    """返回 (MappingConfig, analysis_cfg, envelope_cfg)，已套用预设与覆盖项。"""
    base = PRESETS.get(preset, PRESETS[DEFAULT_PRESET])
    m = dict(base.get("mapping", {}))
    a = dict(base.get("analysis", {}))
    e = dict(base.get("envelope", {}))
    ov = overrides or {}
    m.update(ov.get("mapping", {}))
    a.update(ov.get("analysis", {}))
    e.update(ov.get("envelope", {}))
    return MappingConfig(**m), a, e
