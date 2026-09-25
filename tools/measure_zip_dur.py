"""正确测量：单次滑索的音频持续时长。

纠错：
    8 组信号，每组内部间隔 90ms = 「按下 / 松开」。
    8 组 = 8 次滑索（不是 4 次）。
    之前的"拖尾 6.9s"是因为回落检测撞上了下一个配对，属算法假象。

本脚本：
    以每个信号组为起点，逐帧跟踪低频能量，
    找它回落到基线以下的精确时刻 → 即滑索真实结束点。
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

# 按 0.5s 间隔分组 → 8 组
groups = []
cur = [sig_idx[0]]
for i in sig_idx[1:]:
    if T[i] - T[cur[-1]] < 0.5:
        cur.append(i)
    else:
        groups.append(cur)
        cur = [i]
groups.append(cur)
print(f"共 {len(groups)} 组信号 = {len(groups)} 次滑索\n")

# 基线（远离信号处）
far = np.ones(len(T), dtype=bool)
for i in sig_idx:
    far[max(0, i - 30):i + 300] = False
base_lo = np.percentile(LO[far], 50)
base_rms = np.percentile(RMS[far], 50)
print(f"基线: 低频 P50={base_lo:.5f}  RMS P50={base_rms:.5f}\n")

print(f"{'#':>2} {'起始':>7} {'峰值低频':>9} {'峰值RMS':>9} "
      f"{'低频回落':>9} {'RMS回落':>9} {'持续(低)':>9} {'持续(RMS)':>10}")
print("-" * 82)

results = []
for gi, g in enumerate(groups, 1):
    t0 = T[g[0]]
    w = np.where((T >= t0) & (T <= t0 + 12))[0]
    if len(w) < 20:
        continue

    # 峰值（信号后 1.5s 内）
    w_peak = w[T[w] <= t0 + 1.5]
    pk_lo = LO[w_peak].max()
    pk_rms = RMS[w_peak].max()

    # 回落到基线的 1.5 倍以下，且持续 300ms
    def find_drop(arr, th):
        run = 0
        for k in w:
            if arr[k] < th:
                run += 1
                if run >= 15:
                    return T[k - 14]
            else:
                run = 0
        return None

    d_lo = find_drop(LO, base_lo * 1.5)
    d_rms = find_drop(RMS, base_rms * 1.5)

    dur_lo = (d_lo - t0) if d_lo else None
    dur_rms = (d_rms - t0) if d_rms else None
    results.append((t0, pk_lo, pk_rms, d_lo, d_rms, dur_lo, dur_rms))

    def f(v, fmt="{:.2f}"):
        return fmt.format(v) if v is not None else "  --  "
    print(f"{gi:>2} {t0:>7.2f} {pk_lo:>9.5f} {pk_rms:>9.5f} "
          f"{f(d_lo):>9} {f(d_rms):>9} {f(dur_lo):>9} {f(dur_rms):>10}")

dl = [r[5] for r in results if r[5]]
dr = [r[6] for r in results if r[6]]
print(f"\n低频判据持续时长: min={min(dl):.2f}s max={max(dl):.2f}s "
      f"avg={sum(dl)/len(dl):.2f}s  (n={len(dl)})")
print(f"RMS 判据持续时长: min={min(dr):.2f}s max={max(dr):.2f}s "
      f"avg={sum(dr)/len(dr):.2f}s  (n={len(dr)})")

print(f"\n峰值低频/基线 = {np.mean([r[1] for r in results])/base_lo:.1f}x")
print(f"峰值RMS /基线 = {np.mean([r[2] for r in results])/base_rms:.1f}x")
