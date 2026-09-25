"""离线重放：用真实抓取数据验证扳机联动的结束判定。

为什么需要它：
    每次改判定逻辑都上机测，一轮就是 1 分钟人力，且结果不可复现。
    这份脚本把 `tools/_dual_rms.csv`（真实音频 RMS 逐帧）和日志信号时刻
    一起喂给 TriggerGripSource.update()，离线跑一遍，直接看动作时长。

用法:
    python tools/replay_trigger.py
    python tools/replay_trigger.py --arm-peak 0.004 --fall-ratio 0.62

判读标准：
    输出的每个动作时长，应与 `_dual.csv` 里音频活跃段长度接近
    （长滑索 4~5s，短滑索 0.5~1s）。
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.trigger.source import TriggerGripConfig, TriggerGripSource   # noqa: E402

# 本次抓取（16:05 左右）日志信号相对抓取起点的时刻
LOG_SIGNALS = [4.74, 4.83, 11.17, 11.29, 13.93, 14.06, 17.52, 17.61,
               19.38, 19.47, 22.98, 23.09, 24.98, 25.10, 31.45, 31.58]

# 音频活跃段（来自 dual_probe 输出），作为"真值"参照
TRUE_SEGS = [(13.85, 18.54), (19.47, 23.73), (24.98, 30.02), (30.16, 32.09)]


def load_rms(path="tools/_dual_rms.csv"):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r, None)
        for a, b in r:
            rows.append((float(a), float(b)))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", type=int, default=75)
    ap.add_argument("--fall-ratio", type=float, default=0.62)
    ap.add_argument("--guard", type=float, default=700.0)
    ap.add_argument("--arm-peak", type=float, default=0.0050)
    ap.add_argument("--abs-quiet", type=float, default=0.0015)
    ap.add_argument("--quiet-frames", type=int, default=3)
    args = ap.parse_args()

    rows = load_rms()
    print(f"载入 {len(rows)} 帧 RMS（{rows[-1][0]:.1f}s）\n")

    cfg = TriggerGripConfig(
        enabled=True, drive=args.drive,
        fall_ratio=args.fall_ratio, attack_guard_ms=args.guard,
        arm_peak=args.arm_peak, abs_quiet=args.abs_quiet,
        quiet_frames=args.quiet_frames,
    )
    src = TriggerGripSource(cfg)

    # 把日志信号按帧号注入（模拟 4ms 轮询线程已投递）
    sig_by_frame = {}
    for s in LOG_SIGNALS:
        idx = min(range(len(rows)), key=lambda i: abs(rows[i][0] - s))
        sig_by_frame.setdefault(idx, 0)
        sig_by_frame[idx] += 1

    print(f"{'t(s)':>8} {'rms':>9} {'驱动':>5}  事件")
    print("-" * 52)

    actions = []
    st = None
    prev_active = False
    for i, (t, rms) in enumerate(rows):
        if i in sig_by_frame:
            with src._lock:                       # 模拟尾随线程投递
                src._buf.append((t, sig_by_frame[i]))
        out = src.update(t, rms)
        if src._active and not prev_active:
            st = t
            print(f"{t:>8.2f} {rms:>9.5f} {out:>5}  ▶ 动作开始")
        elif not src._active and prev_active:
            d = t - st
            actions.append((st, t, d))
            print(f"{t:>8.2f} {rms:>9.5f} {out:>5}  ■ 动作结束  "
                  f"时长 {d:.2f}s  ({src._last_reason})")
        prev_active = src._active

    print(f"\n{'#':>3} {'开始':>8} {'结束':>8} {'时长':>8}")
    for k, (a, b, d) in enumerate(actions, 1):
        print(f"{k:>3} {a:>8.2f} {b:>8.2f} {d:>7.2f}s")

    print(f"\n总动作数: {len(actions)}   信号数: {src.n_trigger}")
    dur = [d for _, _, d in actions]
    if dur:
        print(f"时长: min={min(dur):.2f}s  max={max(dur):.2f}s  "
              f"avg={sum(dur)/len(dur):.2f}s")

    print("\n参照——真实音频活跃段：")
    for a, b in TRUE_SEGS:
        print(f"    {a:7.2f} ~ {b:7.2f}s   时长 {b-a:5.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
