"""实时探针：跑完整管线，但把每帧强度打到一行，方便与听感对照。

用法:
    python tools/live_probe.py [秒数] [增益]
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.core.config import Config  # noqa: E402
from src.core.pipeline import HapticPipeline  # noqa: E402

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
GAIN = sys.argv[2] if len(sys.argv) > 2 else None


def bar(v: float, w: int = 26) -> str:
    n = int(max(0.0, min(1.0, v)) * w)
    return "█" * n + "·" * (w - n)


def main() -> int:
    cfg = Config.load()
    if GAIN:
        cfg.data["mapping"]["master_gain"] = float(GAIN)
    pipe = HapticPipeline(cfg)
    stop = threading.Event()
    t_end = time.time() + SECS
    last = 0.0

    def on_frame(s: dict) -> None:
        nonlocal last
        now = time.perf_counter()
        if now - last < 0.08:
            return
        last = now
        print(
            f"\rL {bar(s['drive_l']/255)} {s['drive_l']:3d} | "
            f"R {bar(s['drive_r']/255)} {s['drive_r']:3d} | "
            f"RMS {s['rms_l']:.4f} | AGC×{s['agc_gain']:.2f} | "
            f"手柄{'✓' if s['connected'] else '✗'} {s['send_rate']:.0f}Hz "
            f"丢弃{s['dropped']}",
            end="", flush=True,
        )

    print(f"实时探针启动：{SECS:.0f}s，预设={cfg.preset}，"
          f"增益={cfg.data['mapping'].get('master_gain', 1.0)}")
    print(">>> 现在放声音 <<<\n")
    try:
        pipe.run(on_frame=on_frame, max_seconds=SECS, stop_event=stop)
    except KeyboardInterrupt:
        pipe.shutdown()
    print("\n\n探针结束。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
