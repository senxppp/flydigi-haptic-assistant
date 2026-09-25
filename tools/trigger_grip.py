"""扳机联动握把震动 —— 实时演示。

监听服务日志的 ForceTrigger 事件，按策略驱动握把震动。

用法:
    python tools/trigger_grip.py [秒数] [模式]
    模式: pulse  = 每次扳机信号点动一下（跟随）
          hold   = 首次信号后持续震动，直到超时无新信号
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "vib_out"))

from flydigi_vib import FlydigiVibration  # noqa: E402

LOG = Path("D:/Flydigi Space Station/Logs/service_log_20260925.txt")
KEY = "ForceTriggerControllerCommandNewXInput"

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
MODE = sys.argv[2] if len(sys.argv) > 2 else "hold"
DRIVE = 140          # 握把力度（不盖过冲击的 190~240）
HOLD_MS = 400        # hold 模式：无新信号多久后停震


def main() -> int:
    pos = LOG.stat().st_size if LOG.exists() else 0
    dev = FlydigiVibration()
    dev.open()
    print(f"扳机联动演示：{DUR:.0f}s  模式={MODE}  力度={DRIVE}")
    print(f"日志 offset={pos}  hold 超时={HOLD_MS}ms")
    print(">>> 去游戏里触发扳机震动 <<<\n")

    stop = threading.Event()
    last_event = 0.0
    n_events = 0
    cur = 0

    def write(v: int) -> None:
        nonlocal cur
        if v != cur:
            dev.set(v, v)
            cur = v
            sys.stdout.write(f"\r握把 {v:3d} ")
            sys.stdout.flush()

    t_end = time.time() + DUR
    try:
        while time.time() < t_end:
            # 读日志新内容
            try:
                size = LOG.stat().st_size
            except OSError:
                size = pos
            if size < pos:
                pos = 0
            if size > pos:
                try:
                    with LOG.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    cnt = chunk.count(KEY)
                    if cnt:
                        n_events += cnt
                        last_event = time.time()
                        print(f"\n[{time.strftime('%H:%M:%S')}] 扳机信号 ×{cnt} "
                              f"(累计 {n_events})")
                except OSError:
                    pass

            # 策略
            if MODE == "hold":
                if last_event and (time.time() - last_event) * 1000 < HOLD_MS:
                    write(DRIVE)
                else:
                    write(0)
            else:  # pulse
                if last_event and (time.time() - last_event) * 1000 < 120:
                    write(DRIVE)
                else:
                    write(0)

            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            dev.set(0, 0)
            dev.close()
        except Exception:
            pass
    print(f"\n\n结束：共 {n_events} 次扳机信号")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
