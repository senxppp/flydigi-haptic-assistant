"""扳机联动握把震动 v5 —— 极速响应版（<50ms）。

v4 结束延迟 1.5~1.9s 的根因:
  - QUIET_MS=120 的确认窗口
  - PEAK_WIN=0.6s 的峰值滑窗：要等峰值滑出窗口，阈值才降下来

v5 换思路：不靠"降到峰值比例以下"，改用**能量骤降检测**
（当前 RMS 相对前 200ms 的均值突然下降一个比例，立刻判结束），
并把确认窗口压到 1~2 帧（20~40ms）。

用法:
    python tools/trigger_grip5.py [秒数] [力度] [骤降比例]
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "vib_out"))

import numpy as np                                          # noqa: E402
from flydigi_vib import FlydigiVibration                     # noqa: E402
from src.audio.loopback import LoopbackCapture                # noqa: E402
from src.core.config import Config                            # noqa: E402

LOG = Path("D:/Flydigi Space Station/Logs/service_log_20260925.txt")
KEY = "ForceTriggerControllerCommandNewXInput"

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
DRIVE = int(sys.argv[2]) if len(sys.argv) > 2 else 90
FALL_RATIO = float(sys.argv[3]) if len(sys.argv) > 3 else 0.55

ATTACK_GUARD_MS = 400   # 动作开头保护期
CONFIRM_FRAMES = 2      # 连续多少帧满足"骤降"才结束（2帧=40ms）
MAX_MS = 20000
COOLDOWN_MS = 120
ABS_FLOOR = 0.0009
BASE_WIN_S = 0.25       # 基准窗口：用它算"正常电平"


def main() -> int:
    cfg = Config.load()
    sr = cfg.data["audio"]["sample_rate"]

    dev = FlydigiVibration()
    dev.open()
    cap = LoopbackCapture(frame_ms=20, device_hint=None,
                          sample_rate=sr, queue_seconds=0.5)
    cap.start()

    pos = LOG.stat().st_size if LOG.exists() else 0
    print(f"扳机联动 v5（极速）：{DUR:.0f}s  力度={DRIVE}  骤降={FALL_RATIO:.0%}")
    print(f"  保护期 {ATTACK_GUARD_MS}ms / 确认 {CONFIRM_FRAMES}帧 "
          f"/ 基准窗 {BASE_WIN_S}s")
    print(">>> 请做几个动作，注意感受结束响应 <<<\n")

    stop_evt = threading.Event()
    log_buf: list = []
    lock = threading.Lock()

    def tail() -> None:
        p = pos
        while not stop_evt.is_set():
            try:
                size = LOG.stat().st_size
            except OSError:
                time.sleep(0.05)
                continue
            if size < p:
                p = 0
            if size > p:
                try:
                    with LOG.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(p)
                        chunk = f.read()
                        p = f.tell()
                    cnt = chunk.count(KEY)
                    if cnt:
                        with lock:
                            log_buf.append((time.time(), cnt))
                except OSError:
                    pass
            time.sleep(0.004)

    threading.Thread(target=tail, daemon=True).start()

    cur = 0

    def write(v: int) -> None:
        nonlocal cur
        if v != cur:
            dev.set(v, v)
            cur = v

    t0 = time.time()
    cooldown_until = 0.0
    active = False
    n_actions = n_trigger = 0
    t_start_act = 0.0
    hist: deque[tuple[float, float]] = deque()
    fall_cnt = 0

    try:
        while time.time() - t0 < DUR:
            now = time.time()

            with lock:
                while log_buf:
                    _, cnt = log_buf.pop(0)
                    n_trigger += cnt
                    if now >= cooldown_until and not active:
                        active = True
                        hist.clear()
                        fall_cnt = 0
                        t_start_act = now
                        n_actions += 1
                        print(f"[{time.strftime('%H:%M:%S')}] ▶ 动作开始 "
                              f"(信号#{n_trigger})")

            fr = cap.read_frame()
            rms = float(np.sqrt(np.mean(np.asarray(fr, dtype=np.float64) ** 2)))

            hist.append((now, rms))
            while hist and now - hist[0][0] > BASE_WIN_S:
                hist.popleft()
            base = float(np.mean([v for _, v in hist])) if hist else 0.0

            if active:
                age_ms = (now - t_start_act) * 1000
                if age_ms < ATTACK_GUARD_MS:
                    fall_cnt = 0
                else:
                    # 骤降判定：当前 RMS 低于近期基准的一个比例
                    if base > ABS_FLOOR and rms < base * FALL_RATIO:
                        fall_cnt += 1
                        if fall_cnt >= CONFIRM_FRAMES:
                            dur = now - t_start_act
                            active = False
                            cooldown_until = now + COOLDOWN_MS / 1000.0
                            print(f"[{time.strftime('%H:%M:%S')}] ■ 动作结束 "
                                  f"时长 {dur:.1f}s (基准{base:.4f}→{rms:.4f})")
                            fall_cnt = 0
                    else:
                        fall_cnt = 0

                    if active and age_ms > MAX_MS:
                        active = False
                        cooldown_until = now + COOLDOWN_MS / 1000.0
                        print(f"[{time.strftime('%H:%M:%S')}] ■ 超时结束")

            write(DRIVE if active else 0)
            time.sleep(0.003)
    except KeyboardInterrupt:
        pass
    finally:
        stop_evt.set()
        try:
            dev.set(0, 0)
            dev.close()
        except Exception:
            pass
        cap.stop()

    print(f"\n\n汇总：信号 {n_trigger} 次，动作 {n_actions} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
