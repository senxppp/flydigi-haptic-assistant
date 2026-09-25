"""扳机联动握把震动 v7 —— 修正 v6 的"起势误杀"。

v6 实测（骤降 70% / 保护期 350ms）：
  8 个动作全部只活了 0.4~0.6s —— 全被误杀。
  根因：动作起势期（保护期刚过）RMS 还在 0.0040~0.0057 爬升，
        而 70% 线在 0.0053~0.0063，直接把爬升中的电平判成"骤降"。

v7 修正：
  1. 保护期 350ms → 700ms：给动作足够的起势时间，不误杀。
  2. 骤降比例 0.70 → 0.62：阈值落在起势电平(0.0048~0.0057)
     与结束尾巴(0.0024~0.0057)之间的分界区。
  3. 保留静音快线（ABS_QUIET），但门槛略降，只在真正静音时触发。
  4. 确认 1 帧(20ms) 保留 —— 这是极速响应的关键。

  保护期内的策略：只允许"静音快线"触发（真静音一定是结束），
  不打比例判定，避免起势爬升被误判。

用法:
    python tools/trigger_grip7.py [秒数] [力度] [骤降比例]
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
DRIVE = int(sys.argv[2]) if len(sys.argv) > 2 else 80
FALL_RATIO = float(sys.argv[3]) if len(sys.argv) > 3 else 0.62

ATTACK_GUARD_MS = 700   # 动作开头保护期：只允许静音线，不打比例判定
CONFIRM_FRAMES = 1      # 1 帧 = 20ms 确认
MAX_MS = 20000
COOLDOWN_MS = 120
ABS_QUIET = 0.0015      # 静音快线：跌破即结束（保护期内也生效）
ABS_FLOOR = 0.0009      # 基准有效下限（低于此不参与比例判定）
BASE_WIN_S = 0.25       # 基准窗口


def main() -> int:
    cfg = Config.load()
    sr = cfg.data["audio"]["sample_rate"]

    dev = FlydigiVibration()
    dev.open()
    cap = LoopbackCapture(frame_ms=20, device_hint=None,
                          sample_rate=sr, queue_seconds=0.5)
    cap.start()

    pos = LOG.stat().st_size if LOG.exists() else 0
    print(f"扳机联动 v7（修正起势误杀）：{DUR:.0f}s  力度={DRIVE}  "
          f"骤降={FALL_RATIO:.0%}  静音线={ABS_QUIET}")
    print(f"  保护期 {ATTACK_GUARD_MS}ms（仅静音线生效）/ "
          f"确认 {CONFIRM_FRAMES}帧(20ms) / 基准窗 {BASE_WIN_S}s")
    print(f"  A.静音快线 RMS<{ABS_QUIET}  B.骤降线 RMS<基准×{FALL_RATIO:.2f}")
    print(">>> 请做几个动作（长短都试试），注意感受结束响应 <<<\n")

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
                reason = None
                if age_ms < ATTACK_GUARD_MS:
                    # 保护期内：只认静音快线（真静音一定是动作结束），
                    # 不打比例判定，避免起势爬升被误判。
                    if rms < ABS_QUIET:
                        reason = f"静音(rms={rms:.4f})"
                else:
                    # A. 静音快线
                    if rms < ABS_QUIET:
                        reason = f"静音(rms={rms:.4f})"
                    # B. 骤降线
                    elif base > ABS_FLOOR and rms < base * FALL_RATIO:
                        reason = f"骤降(基准{base:.4f}→{rms:.4f})"

                if reason is not None:
                    fall_cnt += 1
                    if fall_cnt >= CONFIRM_FRAMES:
                        dur = now - t_start_act
                        active = False
                        cooldown_until = now + COOLDOWN_MS / 1000.0
                        print(f"[{time.strftime('%H:%M:%S')}] ■ 动作结束 "
                              f"时长 {dur:.1f}s  {reason}")
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
