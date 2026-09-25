"""用低频段能量做滑索判据的可行性验证。

发现：
    滑索触发瞬间，低频(<300Hz)能量从基线 P50=0.00115 跳到 0.00590（6.7 倍），
    比 RMS 的跳幅（4.5 倍）更显著，且低频不易被 BGM 掩盖。

    信号结构：一次滑索 = **两组信号**（进入 / 离开），间距约 6.4 秒。

本脚本：
    用不同阈值 + 确认帧数，看能否把滑索起止切干净。
    同时对比「滑索段」与「平常游玩段」的分离度。
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
sig_idx = np.where(SIG > 0)[0]

# 用户说"按一下松开"，实际 8 组信号 = 4 次滑索（两两配对）
pairs = [(sig_idx[i], sig_idx[i + 1]) for i in range(0, len(sig_idx) - 1, 2)]
print("滑索配对（进入 → 离开）：")
for a, b in pairs:
    print(f"   {T[a]:6.2f}s → {T[b]:6.2f}s   时长 {T[b]-T[a]:5.2f}s")

# 滑索期间的音频 vs 其他时间
zip_mask = np.zeros(len(T), dtype=bool)
for a, b in pairs:
    zip_mask[a:b + 12] = True       # 信号到离开 +0.2s

other = ~zip_mask
print(f"\n{'指标':>8} {'滑索段 P50':>12} {'滑索段 P90':>12} "
      f"{'其他 P50':>10} {'其他 P90':>10} {'分离比':>8}")
print("-" * 68)
for name, arr in (("RMS", RMS), ("低频<300", LO)):
    z = arr[zip_mask]
    o = arr[other]
    z50, z90 = np.percentile(z, 50), np.percentile(z, 90)
    o50, o90 = np.percentile(o, 50), np.percentile(o, 90)
    print(f"{name:>8} {z50:>12.5f} {z90:>12.5f} {o50:>10.5f} "
          f"{o90:>10.5f} {z50/max(o50,1e-9):>8.2f}x")

# ---- 用低频阈值切段 ----
print("\n=== 用低频阈值切段（确认帧数=10，即 200ms）===")
base_lo = np.percentile(LO[other], 50)
print(f"基线低频 P50 = {base_lo:.5f}\n")
print(f"{'倍数':>6} {'阈值':>9} {'段数':>5}   段落")
print("-" * 70)
for mult in (2.0, 2.5, 3.0, 3.5, 4.0):
    th = base_lo * mult
    segs = []
    run = 0
    st = None
    for i, v in enumerate(LO):
        if v > th:
            run += 1
            if run >= 10 and st is None:
                st = T[max(0, i - 9)]
        else:
            if st is not None and run >= 10:
                segs.append((st, T[i - 1]))
            run = 0
            st = None
    if st is not None:
        segs.append((st, T[-1]))
    txt = "  ".join(f"{a:.1f}~{b:.1f}({b-a:.1f}s)" for a, b in segs[:6])
    print(f"{mult:>6.1f} {th:>9.5f} {len(segs):>5}   {txt}")

print("\n真实滑索时段（按信号对）：")
for a, b in pairs:
    print(f"   {T[a]:6.2f} ~ {T[b]:6.2f}s  ({T[b]-T[a]:.2f}s)")
