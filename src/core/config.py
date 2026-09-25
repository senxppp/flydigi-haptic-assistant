"""
配置系统 — JSON 读写 / 预设切换 / 参数校验
==========================================

配置文件默认位于 configs/config.json；首次运行自动生成默认配置。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..mapping.mapper import MappingConfig
from ..mapping.presets import DEFAULT_PRESET, PRESETS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "preset": DEFAULT_PRESET,
    "audio": {
        "frame_ms": 20,
        "device_hint": None,           # None = 跟随系统默认播放设备
        "sample_rate": 48000,
        "capture_queue_seconds": 0.5,
    },
    "analysis": {},
    "envelope": {},
    "mapping": {},
    "output": {
        "send_rate_hz": 60,            # 震动帧发送频率（文档建议 50-100Hz）
        "auto_stop_ms": 120,           # 无声后自动归零时间
        "safety_max_drive": 240,       # 硬上限，防止误配置打满马达
        "device_watchdog_s": 2.0,      # 手柄连接状态检测周期（6.4(4)）
    },
    "trigger": {
        "enabled": False,              # 扳机联动握把震动总开关
        "drive": 75,                   # 握把力度（冲击约 190~240，故不盖过）
        "log_path": "D:/Flydigi Space Station/Logs/service_log_{date}.txt",
        "log_key": "ForceTriggerControllerCommandNewXInput",
        "poll_ms": 4.0,
        # --- 判据：双信号组奇偶（组1=进入滑索，组2=脱离滑索）---
        "dedup_ms": 300.0,             # 组内去重窗口（<此间隔的算同一组）
        "max_ms": 20000.0,             # 兜底超时（防漏"脱离"信号）
        "min_ms": 150.0,               # 最短时长（防瞬时抖动）
        # --- 可选音频安全网（默认关闭）---
        "use_audio_guard": False,
        "abs_quiet": 0.0008,
        "quiet_frames": 25,
    },
    "logging": {
        "level": "INFO",
        "stats_interval_s": 5.0,
        "log_to_file": True,
    },
    "ui": {
        "show_live": True,             # 终端实时强度条
        "show_waveform": False,
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data: dict, path: Path | None = None):
        self.data = data
        self.path = path

    # ---------- 构造 ----------

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        if p.exists():
            try:
                user = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                user = {}
        else:
            user = {}
        return cls(_deep_merge(DEFAULT_CONFIG, user), p)

    def save(self, path: Path | str | None = None) -> Path:
        p = Path(path) if path else (self.path or DEFAULT_CONFIG_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        self.path = p
        return p

    # ---------- 派生 ----------

    @property
    def preset(self) -> str:
        return self.data.get("preset", DEFAULT_PRESET)

    def set_preset(self, name: str) -> None:
        if name not in PRESETS:
            raise KeyError(f"未知预设 '{name}'，可选：{list(PRESETS)}")
        self.data["preset"] = name
        # 切预设时清空该类别的用户覆盖，避免旧覆盖污染新预设
        for k in ("mapping", "analysis", "envelope"):
            self.data.setdefault(k, {}).clear()

    def build_mapping_config(self) -> MappingConfig:
        from ..mapping.presets import build_config
        mcfg, _, _ = build_config(self.preset, {
            "mapping": self.data.get("mapping", {}),
        })
        return mcfg

    def build_analysis_config(self) -> dict:
        from ..mapping.presets import build_config
        _, acfg, ecfg = build_config(self.preset, {
            "analysis": self.data.get("analysis", {}),
        })
        # envelope 参数并入 mapping（ADSR 在 mapper 里）
        return {**acfg, **{f"adsr_{k}": v for k, v in ecfg.items()}}

    def build_envelope_config(self) -> dict:
        from ..mapping.presets import build_config
        _, _, ecfg = build_config(self.preset, {
            "envelope": self.data.get("envelope", {}),
        })
        return ecfg

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self.data, ensure_ascii=False))
