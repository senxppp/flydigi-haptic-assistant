"""验证「双信号组」判据：信号组1=进入滑索，信号组2=脱离滑索。

用户澄清 + 实测确认：
    一次滑索在日志中产生 **两组** ForceTrigger（每组 2 行，组内间隔 ~90ms）。
      组1 = 触发滑索（按下）
      组2 = 脱离滑索（再按一次）
    两组之间 = 滑索持续时段，实测 6.4~8.2 秒。

本脚本用 tools/_zp.csv 的真实信号序列验证：
    按「组1→组2」圈出的时段，是否与音频活跃段吻合。
"""
from __future__ import annotations

import csv
import numpy as np

rows = []
with open("tools/_zp.csv", newline="", encoding="utf-8") as f:
    r = csv.reader(f)
    next(r, None)
    for x in r:
        rows.append([float(v) for v in x])

T = np.array([r[0] for r in rows])
RMS = np.array([r[1] for r in rows])
LO = np.array([r[2] for r in rows])
SIG = np.array([int(r[6]) for r in rows])
sig_t = T[np.where(SIG > 0)[0]]

# 分组（0.5s 内算同组）
groups = [[sig_t[0]]]
for t in sig_t[1:]:
    if t - groups[-1][-1] < 0.5:
        groups[-1].append(t)
    else:
        groups.append([t])

print(f"共 {len(groups)} 组信号\n")
print("每组：")
for i, g in enumerate(groups, 1):
    print(f"  {i}: {g[0]:6.2f}s  ({len(g)} 行, 跨度 {(g[-1]-g[0])*1000:.0f}ms)")

# 配对：奇数组=进入，偶数组=脱离
print("\n按「组1→组2」配对为一次滑索：")
base_lo = np.percentile(LO, 50)
pair_info = []
for i in range(0, len(groups) - 1, 2):
    a, b = groups[i][0], groups[i + 1][0]
    dur = b - a
    # 该时段的音频统计
    w = np.where((T >= a) & (T <= b))[0]
    m_lo = LO[w].mean() if len(w) else 0
    m_rms = RMS[w].mean() if len(w) else 0
    pair_info.append((a, b, dur, m_lo, m_rms))
    print(f"  滑索{i//2+1}: {a:6.2f} → {b:6.2f}s  时长 {dur:5.2f}s  "
          f"段内低频均值 {m_lo:.5f}  RMS均值 {m_rms:.5f}")

# 对比：非滑索时段的音频
zip_mask = np.zeros(len(T), dtype=bool)
for a, b, *_ in pair_info:
    zip_mask[(T >= a) & (T <= b)] = True
other = ~zip_mask

print(f"\n{'指标':>10} {'滑索段均值':>12} {'非滑索均值':>12} {'分离比':>8}")
print("-" * 46)
for name, arr in (("RMS", RMS), ("低频", LO)):
    zm = arr[zip_mask].mean()
    om = arr[other].mean()
    print(f"{name:>10} {zm:>12.5f} {om:>12.5f} {zm/max(om,1e-9):>7.2f}x")

print(f"\n滑索时长: min={min(p[2] for p in pair_info):.2f}s "
      f"max={max(p[2] for p in pair_info):.2f}s "
      f"avg={np.mean([p[2] for p in pair_info]):.2f}s")
print("\n=> 若分离比 > 2，说明「组1→组2」圈出的时段确实是滑索时段。")
