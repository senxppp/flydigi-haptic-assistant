"""扳机联动握把震动 v4 —— 修复峰值串扰 + 大幅降低结束延迟。

v3 的两个缺陷:
  1) 「长→短→长」时后面的长动作提前结束
     根因: peak 在动作刚开始时会被前一动作残留的能量抬得虚高
     （触发瞬间声音还在上升，peak 一两帧就冲很高），
     导致阈值 peak*ratio 偏高，动作刚开始就被判"降到阈值以下"。
     修法: 动作开始后给一段 ATTACK_GUARD_MS 保护期，期内只更新 peak
     不判定结束；并且对 peak 做滑动窗口的"近期峰值"而非历史最大值。
  2) 结束延迟大
     修法: QUIET_MS 降低, 且用"能量已低于阈值 + 已过保护期"双条件。

用法:
    python tools/trigger_grip4.py [秒数] [力度] [下降比例]
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
DROP_RATIO = float(sys.argv[3]) if len(sys.argv) > 3 else 0.20

ATTACK_GUARD_MS = 500   # 动作开始后的保护期：只更新峰值，不判结束
QUIET_MS = 120          # 确认结束所需时长（低延迟）
MAX_MS = 20000
COOLDOWN_MS = 150
ABS_FLOOR = 0.0010
PEAK_WIN = 0.6          # 峰值滑动窗口（秒）——取"近期峰值"而非历史最大


def main() -> int:
    cfg = Config.load()
    sr = cfg.data["audio"]["sample_rate"]

    dev = FlydigiVibration()
    dev.open()
    cap = LoopbackCapture(frame_ms=20, device_hint=None,
                          sample_rate=sr, queue_seconds=0.5)
    cap.start()

    pos = LOG.stat().st_size if LOG.exists() else 0
    print(f"扳机联动 v4：{DUR:.0f}s  力度={DRIVE}  比例={DROP_RATIO:.0%}")
    print(f"  保护期 {ATTACK_GUARD_MS}ms / 确认 {QUIET_MS}ms / 峰值窗 {PEAK_WIN}s")
    print(">>> 请按「长→短→长」的顺序做动作，验证不再提前结束 <<<\n")

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
            time.sleep(0.005)

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
    n_actions = 0
    n_trigger = 0
    t_start_act = 0.0
    peak_hist: deque[float] = deque()   # (ts, rms)
    below_since = 0.0

    try:
        while time.time() - t0 < DUR:
            now = time.time()

            # --- 扳机信号 ---
            with lock:
                while log_buf:
                    _, cnt = log_buf.pop(0)
                    n_trigger += cnt
                    if now >= cooldown_until and not active:
                        active = True
                        peak_hist.clear()
                        below_since = 0.0
                        t_start_act = now
                        n_actions += 1
                        print(f"[{time.strftime('%H:%M:%S')}] ▶ 动作开始 "
                              f"(信号#{n_trigger})")

            # --- 音频包络 ---
            fr = cap.read_frame()
            rms = float(np.sqrt(np.mean(np.asarray(fr, dtype=np.float64) ** 2)))

            # 维护峰值窗口
            peak_hist.append((now, rms))
            while peak_hist and now - peak_hist[0][0] > PEAK_WIN:
                peak_hist.popleft()
            recent_peak = max((v for _, v in peak_hist), default=0.0)

            if active:
                age_ms = (now - t_start_act) * 1000
                in_guard = age_ms < ATTACK_GUARD_MS

                # 保护期内：只积累峰值，绝不判结束
                if in_guard:
                    below_since = 0.0
                else:
                    thresh = max(recent_peak * DROP_RATIO, ABS_FLOOR)
                    if rms < thresh:
                        if below_since == 0.0:
                            below_since = now
                        elif (now - below_since) * 1000 >= QUIET_MS:
                            dur = now - t_start_act
                            active = False
                            cooldown_until = now + COOLDOWN_MS / 1000.0
                            print(f"[{time.strftime('%H:%M:%S')}] ■ 动作结束 "
                                  f"时长 {dur:.1f}s (峰值{recent_peak:.4f}→"
                                  f"{rms:.4f})")
                            below_since = 0.0
                    else:
                        below_since = 0.0

                    if active and age_ms > MAX_MS:
                        active = False
                        cooldown_until = now + COOLDOWN_MS / 1000.0
                        print(f"[{time.strftime('%H:%M:%S')}] ■ 超时结束")

            write(DRIVE if active else 0)
            time.sleep(0.005)
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
