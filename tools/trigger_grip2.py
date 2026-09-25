"""扳机联动握把震动 —— 完整实现（动作间有明显分割）。

逻辑:
  1. 扳机信号出现 → 握把立即可见地开始震（力度 drive）
  2. 停止条件（先到者生效）:
     a) 音频能量低于阈值持续 quiet_ms  → 呼呼声/动作结束
     b) 距最后一次扳机信号超过 max_ms   → 兜底超时
  3. 停止后进入 cooldown_ms 冷却，避免同一动作被拆成多段

用法:
    python tools/trigger_grip2.py [秒数] [力度] [模式]
    模式: seg = 有分割（默认）  hold = 持续到超时
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "vib_out"))

from flydigi_vib import FlydigiVibration                     # noqa: E402
from src.audio.loopback import LoopbackCapture                # noqa: E402
from src.core.config import Config                            # noqa: E402

LOG = Path("D:/Flydigi Space Station/Logs/service_log_20260925.txt")
KEY = "ForceTriggerControllerCommandNewXInput"

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
DRIVE = int(sys.argv[2]) if len(sys.argv) > 2 else 140
MODE = sys.argv[3] if len(sys.argv) > 3 else "seg"

QUIET_MS = 700        # 音频安静多久判定"动作结束"（动作时长 1~10s 不定，取宽容值）
MAX_MS = 12000        # 兜底：单次动作最长震多久（覆盖 10 秒的长动作）
COOLDOWN_MS = 250     # 停止后冷却，防止抖动误启
SILENCE_RMS = 0.0025  # 音频静默阈值（实测呼呼声 RMS≈0.0024~0.0044）


def main() -> int:
    cfg = Config.load()
    sr = cfg.data["audio"]["sample_rate"]

    dev = FlydigiVibration()
    dev.open()

    cap = LoopbackCapture(frame_ms=20, device_hint=None,
                          sample_rate=sr, queue_seconds=0.5)
    cap.start()

    pos = LOG.stat().st_size if LOG.exists() else 0
    print(f"扳机联动 v2：{DUR:.0f}s  力度={DRIVE}  模式={MODE}")
    print(f"  静音判定 {QUIET_MS}ms / 超时 {MAX_MS}ms / 冷却 {COOLDOWN_MS}ms")
    print(f"  音频静默阈值 RMS < {SILENCE_RMS}")
    print(">>> 请完整做几个动作（每个动作之间停顿一下）<<<\n")

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
    last_trigger = 0.0        # 最后一次扳机信号时刻
    last_loud = 0.0           # 最后一次"有声"时刻
    cooldown_until = 0.0
    active = False
    n_actions = 0
    n_trigger = 0

    try:
        while time.time() - t0 < DUR:
            now = time.time()

            # 1) 读扳机信号
            with lock:
                while log_buf:
                    _, cnt = log_buf.pop(0)
                    n_trigger += cnt
                    last_trigger = time.time()
                    if now >= cooldown_until:
                        active = True
                        n_actions += 1
                        print(f"[{time.strftime('%H:%M:%S')}] ▶ 动作开始 "
                              f"(信号 #{n_trigger})")
                    else:
                        # 冷却期内的信号：延长当前动作
                        last_trigger = time.time()

            # 2) 读音频能量
            fr = cap.read_frame()
            rms = float(abs(fr).mean())
            if rms > SILENCE_RMS:
                last_loud = now

            # 3) 停止判定
            if active:
                quiet_for = (now - last_loud) * 1000 if last_loud else 0
                since_trigger = (now - last_trigger) * 1000
                if MODE == "seg":
                    done = quiet_for > QUIET_MS and since_trigger > 400
                else:
                    done = since_trigger > MAX_MS
                if done:
                    active = False
                    cooldown_until = now + COOLDOWN_MS / 1000.0
                    print(f"[{time.strftime('%H:%M:%S')}] ■ 动作结束 "
                          f"(静音 {quiet_for:.0f}ms)")

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

    print(f"\n\n汇总：扳机信号 {n_trigger} 次，识别动作 {n_actions} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
