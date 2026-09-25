"""扳机联动握把震动 v3 —— 相对包络下降检测。

针对 v2 的两个问题改进：
  1) 「长动作中途结束」→ 阈值 0.0025 太高，呼呼声自身低谷被误判
  2) 「结束后延迟~1s」  → QUIET_MS=700 是固有延迟

新判据（自适应，不看绝对电平）:
  记录触发后 RMS 的峰值 peak，当 RMS < peak * DROP_RATIO 且持续 QUIET_MS
  → 判定动作结束。同时对峰谷做平滑，避免单帧抖动。

用法:
    python tools/trigger_grip3.py [秒数] [力度] [下降比例]
"""
from __future__ import annotations

import sys
import threading
import time
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

QUIET_MS = 250        # 需持续多久才确认结束（低延迟）
MAX_MS = 15000        # 兜底超时
COOLDOWN_MS = 200
ABS_FLOOR = 0.0012    # 绝对地板：低于此直接忽略（避免纯底噪）


def main() -> int:
    cfg = Config.load()
    sr = cfg.data["audio"]["sample_rate"]

    dev = FlydigiVibration()
    dev.open()
    cap = LoopbackCapture(frame_ms=20, device_hint=None,
                          sample_rate=sr, queue_seconds=0.5)
    cap.start()

    pos = LOG.stat().st_size if LOG.exists() else 0
    print(f"扳机联动 v3：{DUR:.0f}s  力度={DRIVE}")
    print(f"  下降比例 {DROP_RATIO:.0%} / 确认 {QUIET_MS}ms / 超时 {MAX_MS}ms")
    print(">>> 做几个动作，长短都试试，动作间停顿一下 <<<\n")

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
    last_trigger = 0.0
    peak = 0.0                 # 本动作的 RMS 峰值
    below_since = 0.0          # 首次低于阈值的时刻
    cooldown_until = 0.0
    active = False
    n_actions = 0
    n_trigger = 0
    t_start_act = 0.0

    try:
        while time.time() - t0 < DUR:
            now = time.time()

            # --- 扳机信号 ---
            with lock:
                while log_buf:
                    _, cnt = log_buf.pop(0)
                    n_trigger += cnt
                    last_trigger = time.time()
                    if now >= cooldown_until and not active:
                        active = True
                        peak = 0.0
                        below_since = 0.0
                        t_start_act = now
                        n_actions += 1
                        print(f"[{time.strftime('%H:%M:%S')}] ▶ 动作开始  "
                              f"(信号#{n_trigger})")
                    else:
                        # 动作进行中的新信号：扩展
                        pass

            # --- 音频包络 ---
            fr = cap.read_frame()
            rms = float(np.sqrt(np.mean(np.asarray(fr, dtype=np.float64) ** 2)))

            if active:
                if rms > peak:
                    peak = rms
                thresh = max(peak * DROP_RATIO, ABS_FLOOR)

                if rms < thresh:
                    if below_since == 0.0:
                        below_since = now
                    elif (now - below_since) * 1000 >= QUIET_MS:
                        dur = now - t_start_act
                        active = False
                        cooldown_until = now + COOLDOWN_MS / 1000.0
                        print(f"[{time.strftime('%H:%M:%S')}] ■ 动作结束  "
                              f"时长 {dur:.1f}s  (峰值{peak:.4f}→"
                              f"{rms:.4f})")
                        below_since = 0.0
                else:
                    below_since = 0.0

                # 兜底超时
                if active and (now - t_start_act) * 1000 > MAX_MS:
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
