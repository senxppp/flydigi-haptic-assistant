"""评估用服务日志作为扳机震动信号源的可行性（延迟/吞吐）。

用法:
    python tools/probe_log_latency.py [秒数]
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

LOG = Path("D:/Flydigi Space Station/Logs/service_log_20260925.txt")
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
KEY = "ForceTriggerControllerCommandNewXInput"


def ts_of(line: str) -> float | None:
    """从 '2026-09-25 15:19:34.377 +08:00' 解析 epoch 秒。"""
    try:
        import datetime as dt
        s = line[:23]
        t = dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")
        return t.timestamp()
    except Exception:
        return None


def main() -> int:
    if not LOG.exists():
        print(f"日志不存在: {LOG}")
        return 1
    pos = LOG.stat().st_size
    print(f"起点 offset={pos}，跟踪 {DUR:.0f}s")
    print(">>> 请在游戏里复现动作（触发扳机震动）<<<\n")
    print(f"{'发现时刻':>10} {'日志时间戳':>14} {'延迟(ms)':>9}  原文")
    print("-" * 80)

    lat = []
    t_end = time.time() + DUR
    while time.time() < t_end:
        try:
            size = LOG.stat().st_size
        except OSError:
            time.sleep(0.05)
            continue
        if size < pos:
            print("[日志轮转]")
            pos = 0
        if size > pos:
            try:
                with LOG.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                for line in chunk.splitlines():
                    if KEY not in line:
                        continue
                    now = time.time()
                    ts = ts_of(line)
                    d = (now - ts) * 1000 if ts else -1
                    if d >= 0:
                        lat.append(d)
                    print(f"{now % 100000:>10.3f} {line[11:23]:>14} {d:>9.0f}  {line[40:120]}")
            except OSError:
                pass
        time.sleep(0.01)

    print()
    if lat:
        import statistics
        lat.sort()
        n = len(lat)
        print(f"共 {n} 条 ForceTrigger 事件")
        print(f"延迟: 最小 {lat[0]:.0f}ms  中位 {lat[n//2]:.0f}ms  "
              f"90% {lat[9*n//10]:.0f}ms  最大 {lat[-1]:.0f}ms")
    else:
        print("未捕获到事件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
