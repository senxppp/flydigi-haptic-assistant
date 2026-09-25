"""全帧录制：把每一帧的完整特征写 CSV，供事后分析声学包络。

用法:
    python tools/record_frames.py [秒数] [输出csv]
"""
from __future__ import annotations

import csv
import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.core.config import Config  # noqa: E402
from src.core.pipeline import HapticPipeline  # noqa: E402

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else (_ROOT / "logs" / "frames.csv")

FIELDS = [
    "t", "rms_l", "rms_r", "onset_l", "onset_r", "zcr_l", "zcr_r",
    "band_low_l", "band_low_r", "drive_l", "drive_r", "agc",
]


def main() -> int:
    cfg = Config.load()
    pipe = HapticPipeline(cfg)
    stop = threading.Event()
    t0 = time.time()
    rows: list[list] = []
    lock = threading.Lock()

    print(f"全帧录制启动：{SECS:.0f}s → {OUT}")
    print(">>> 请复现那个动作（冲击 + 尾随的呼呼声）<<<\n")

    def on_frame(s: dict) -> None:
        with lock:
            rows.append([
                round(time.time() - t0, 3),
                round(s["rms_l"], 5), round(s["rms_r"], 5),
                round(s["onset_l"], 3), round(s["onset_r"], 3),
                round(s["zcr_l"], 4), round(s["zcr_r"], 4),
                round(s["band_low"], 5), round(s["band_low_r"], 5),
                s["drive_l"], s["drive_r"],
                round(s["agc_gain"], 3),
            ])

    try:
        pipe.run(on_frame=on_frame, max_seconds=SECS, stop_event=stop)
    except KeyboardInterrupt:
        pipe.shutdown()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        w.writerows(rows)
    print(f"\n已录制 {len(rows)} 帧 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
