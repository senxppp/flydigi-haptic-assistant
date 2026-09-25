"""对照实验：同时记录 HID 字节快照 + 日志扳机事件，找相关性。

输出每个时刻的「关键字节值」，并在日志事件发生的瞬间打标记。
用法: python tools/corr_hid_log.py [秒数]
"""
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import hid

ROOT = Path(__file__).resolve().parents[1]
LOG = Path("D:/Flydigi Space Station/Logs/service_log_20260925.txt")
KEY = "ForceTriggerControllerCommandNewXInput"
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0

TARGET = None
for d in hid.enumerate():
    if d.get("vendor_id") == 0x054C and d.get("product_id") == 0x0CE6:
        TARGET = d
        break

WATCH = [16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]


def main() -> int:
    if TARGET is None:
        print("未找到虚拟 DualSense")
        return 1
    h = hid.device()
    h.open_path(TARGET["path"])
    h.set_nonblocking(1)

    log_events: list[float] = []
    stop = threading.Event()

    def tail() -> None:
        pos = LOG.stat().st_size if LOG.exists() else 0
        while not stop.is_set():
            try:
                size = LOG.stat().st_size
            except OSError:
                time.sleep(0.05)
                continue
            if size < pos:
                pos = 0
            if size > pos:
                try:
                    with LOG.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for _ in range(chunk.count(KEY)):
                        log_events.append(time.time())
                except OSError:
                    pass
            time.sleep(0.005)

    threading.Thread(target=tail, daemon=True).start()
    print(f"对照实验 {DUR:.0f}s")
    print(">>> 请反复做那个动作 <<<\n")
    print(f"{'t':>6}  {'字节16-27的值':<44} 事件")
    print("-" * 74)

    t0 = time.time()
    last_print = 0.0
    last_evt = 0
    while time.time() - t0 < DUR:
        data = h.read(64)
        now = time.time()
        evt = ""
        if len(log_events) > last_evt:
            evt = f"<<< {len(log_events)-last_evt} 次扳机"
            last_evt = len(log_events)
        if data and (now - last_print > 0.15 or evt):
            vals = " ".join(f"{data[i]:02X}" for i in WATCH if i < len(data))
            print(f"{now-t0:>5.1f}s  {vals:<44} {evt}")
            last_print = now
        if not data:
            time.sleep(0.003)

    stop.set()
    h.close()
    print(f"\n日志事件总数: {len(log_events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
