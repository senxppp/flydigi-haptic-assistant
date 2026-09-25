"""观察扳机信号在一次完整动作中的时间分布。

用法:
    python tools/watch_trigger_timeline.py [秒数]
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

LOG = Path("D:/Flydigi Space Station/Logs/service_log_20260925.txt")
KEYS = {
    "ForceTriggerControllerCommandNewXInput": "扳机震动",
    "VibrationControllerCommandNewXInput": "握把震动",
    "EnableRawDataTransportInCommand": "原始透传",
}
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0


def main() -> int:
    pos = LOG.stat().st_size if LOG.exists() else 0
    print(f"跟踪 {DUR:.0f}s，offset={pos}")
    print(">>> 请完整做一次动作（从开始到结束），最好做 2~3 次 <<<\n")
    print(f"{'时刻':>12}  {'距上次(ms)':>10}  类型")
    print("-" * 50)

    t_end = time.time() + DUR
    last_t = None
    counts = {v: 0 for v in KEYS.values()}
    while time.time() < t_end:
        try:
            size = LOG.stat().st_size
        except OSError:
            time.sleep(0.1)
            continue
        if size < pos:
            pos = 0
        if size > pos:
            try:
                with LOG.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                for line in chunk.splitlines():
                    hit = next((v for k, v in KEYS.items() if k in line), None)
                    if not hit:
                        continue
                    now = time.time()
                    gap = (now - last_t) * 1000 if last_t else 0
                    last_t = now
                    counts[hit] = counts.get(hit, 0) + 1
                    print(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]:>12}  "
                          f"{gap:>10.0f}  {hit}")
            except OSError:
                pass
        time.sleep(0.005)

    print()
    print("统计:", {k: n for k, n in counts.items() if n})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
