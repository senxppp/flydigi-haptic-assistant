"""动作事件监测：打印完整特征，用于定位某个游戏动作的声学指纹。

用法:
    python tools/watch_action.py [秒数]
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

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0


def bar(v: float, w: int = 16) -> str:
    n = int(max(0.0, min(1.0, v)) * w)
    return "#" * n + "." * (w - n)


def main() -> int:
    cfg = Config.load()
    pipe = HapticPipeline(cfg)
    stop = threading.Event()
    last = 0.0
    t0 = time.time()
    prev_low = 0.0

    print(f"动作监测启动：{SECS:.0f}s（只看有效帧，静音自动跳过）")
    print(">>> 现在去游戏里做那个动作 <<<\n")
    print(f"{'时刻':>7} {'RMS_L':>7} {'RMS_R':>7} {'onset':>6} "
          f"{'band_low':>9} {'zcr':>6} {'AGC':>5} {'驱动L':>5} {'驱动R':>5}")
    print("-" * 70)

    def on_frame(s: dict) -> None:
        nonlocal last, prev_low
        now = time.perf_counter()
        if now - last < 0.1:
            return
        last = now
        rms = max(s["rms_l"], s["rms_r"])
        onset = max(s["onset_l"], s["onset_r"])
        # 只打印有意义的事件：有声音 或 有瞬态
        if rms < 0.0012 and onset < 0.05:
            prev_low = 0.0
            return
        t = time.time() - t0
        bl = s["band_low"]
        jump = "" if prev_low < 0.005 else "  <-- 突增"
        prev_low = bl
        print(f"{t:>6.1f}s {s['rms_l']:>7.4f} {s['rms_r']:>7.4f} "
              f"{onset:>6.2f} {bl:>9.4f} {s['zcr_l']:>6.3f} "
              f"{s['agc_gain']:>5.2f} {s['drive_l']:>5d} {s['drive_r']:>5d}"
              f"{jump}")

    try:
        pipe.run(on_frame=on_frame, max_seconds=SECS, stop_event=stop)
    except KeyboardInterrupt:
        pipe.shutdown()
    print("\n监测结束。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
