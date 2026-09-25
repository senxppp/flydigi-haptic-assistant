"""离线验证 HID 判据：用真实对照数据重放，看动作时长是否与 HID 活跃段一致。

数据来源 tools/_ab.csv（静止A / 滑索B / 静止C，用户实际是「滑索一直做到 28s」）。

预期：
    HID 活跃段应为 13.41s ~ 28.25s（14.84s）。
    本脚本把该 CSV 当成 HID 帧流喂给判定逻辑，看输出的动作区间是否吻合。
"""
from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

rows = []
with open("tools/_ab.csv", newline="", encoding="utf-8") as f:
    r = csv.reader(f)
    next(r, None)
    for x in r:
        rows.append(x)

STATE = (4, 5, 6, 7, 8, 9, 10, 11)

# 直接用判定规则模拟：连续 N 帧全零 → 结束
def simulate(clear_frames: int, poll_ms: float = 2.0):
    active = False
    t_start = None
    last_nz = 0.0
    armed = False
    acts = []
    for x in rows:
        t = float(x[0])
        vals = [int(x[3 + b]) for b in STATE]
        nz = any(vals)

        if nz:
            last_nz = t
            armed = True
            if not active:          # 首次非零 = 动作开始
                active = True
                t_start = t
        elif active and armed and (t - last_nz) * 1000.0 > poll_ms * clear_frames * 1.5:
            acts.append((t_start, last_nz, last_nz - t_start))
            active = False
            armed = False
    if active:
        acts.append((t_start, last_nz, last_nz - t_start))
    return acts


print(f"{'clear_frames':>13} {'时长(ms)':>10}   判定出的动作区间")
print("-" * 62)
for cf in (3, 6, 12, 20, 30, 50):
    acts = simulate(cf)
    ds = " | ".join(f"{a:.2f}~{b:.2f}({d:.2f}s)" for a, b, d in acts)
    print(f"{cf:>13} {cf*2:>10}   {ds}")

print("\n真实 HID 活跃段：13.41s ~ 28.25s（14.84s），中间断档 0 处")
print("=> clear_frames 越小越容易把动作中的瞬时停顿当成结束；")
print("   越大越迟钝。需要根据实际滑索时的字节连续性选择。")
