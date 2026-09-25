"""滑索诊断 —— 同时记录扳机信号与音频能量，输出时间线。

用途：搞清楚"滑索到底持续多久、期间有什么信号"。
运行后请做几次滑索，脚本会把每一次扳机信号和随后的音频活动都列出来，
方便和你的主观时长对照。

用法:
    python tools/diag_zipslide.py [秒数]
"""
from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import numpy as np                                          # noqa: E402
from src.audio.loopback import LoopbackCapture                # noqa: E402
from src.core.config import Config                            # noqa: E402

LOG = Path("D:/Flydigi Space Station/Logs/service_log_20260925.txt")
KEY = "take ForceTriggerControllerCommandNewXInput"
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0

TPAT = re.compile("[0-9]{2}:[0-9]{2}:[0-9]{2}[.][0-9]+")


def main() -> int:
    cfg = Config.load()
    sr = cfg.data["audio"]["sample_rate"]
    cap = LoopbackCapture(frame_ms=20, device_hint=None,
                          sample_rate=sr, queue_seconds=0.5)
    cap.start()
    pos = LOG.stat().st_size if LOG.exists() else 0

    print(f"滑索诊断 {DUR:.0f}s")
    print(">>> 请做几次滑索，每次做完停顿 2 秒 <<<\n")

    stop = threading.Event()
    events: list = []
    lock = threading.Lock()

    def tail():
        p = pos
        while not stop.is_set():
            try:
                size = LOG.stat().st_size
            except OSError:
                time.sleep(0.05); continue
            if size < p: p = 0
            if size > p:
                try:
                    with LOG.open("r", encoding="utf-8",
                                  errors="replace") as f:
                        f.seek(p); chunk = f.read(); p = f.tell()
                    for line in chunk.splitlines():
                        if KEY in line:
                            m = TPAT.search(line)
                            with lock:
                                events.append(("TRIG", time.time(),
                                               m.group(0) if m else "?"))
                except OSError:
                    pass
            stop.wait(0.003)

    threading.Thread(target=tail, daemon=True).start()

    t0 = time.time()
    t_start = t0
    # 记录每 100ms 的音频电平摘要
    timeline: list = []
    last_tick = 0.0
    peak_in_window = 0.0

    try:
        while time.time() - t0 < DUR:
            fr = cap.read_frame()
            rms = float(np.sqrt(np.mean(np.asarray(fr, dtype=np.float64) ** 2)))
            now = time.time()
            peak_in_window = max(peak_in_window, rms)
            if now - last_tick >= 0.1:
                timeline.append((now, peak_in_window))
                peak_in_window = 0.0
                last_tick = now
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        cap.stop()

    with lock:
        ev = list(events)

    print(f"\n{'='*66}")
    print(f"扳机信号 {len(ev)} 条")
    print(f"{'='*66}")
    if ev:
        print(f"{'#':>3} {'相对':>8} {'绝对时刻':>14}   距上条")
        prev = None
        for i, (_, ts, abs_t) in enumerate(ev):
            rel = ts - t0
            gap = f"+{(ts-prev)*1000:7.0f}ms" if prev else "—"
            print(f"{i:>3} {rel:7.2f}s {abs_t:>14}   {gap}")
            prev = ts

    # 每 0.5 秒一行：信号标记 + 该段音频峰值
    print(f"\n{'='*66}")
    print("时间线（T=扳机信号所在的那 0.5 秒段，峰值=该段音频最大 RMS）")
    print(f"{'='*66}")
    buckets: dict[int, list] = {}
    for _, ts, _ in ev:
        buckets.setdefault(int((ts - t0) / 0.5), []).append("T")
    aud: dict[int, float] = {}
    for ts, pk in timeline:
        k = int((ts - t0) / 0.5)
        aud[k] = max(aud.get(k, 0.0), pk)

    n = int(DUR / 0.5)
    for k in range(n):
        marks = "T" * len(buckets.get(k, []))
        pk = aud.get(k, 0.0)
        bar = "█" * min(20, int(pk / 0.001))
        if marks or pk > 0.0005:
            print(f"  {k*0.5:6.1f}s [{marks:<4}] {pk:.4f} {bar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
