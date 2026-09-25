"""分析滑索音频指纹：把日志信号与多频段能量精确对齐。

问题：用户澄清「滑索是按一下松开，之后滑索自己跑 3~5 秒」。
      → 滑索进行中用户不碰手柄，音频是唯一线索。

本脚本回答三个问题：
  1) 信号对（按下/松开）与音频响度的对应关系
  2) 松开之后音频还响多久（拖尾）
  3) 哪个频段最能区分「滑索」与「平常游玩」
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
MID = np.array([r[3] for r in rows])
HI = np.array([r[4] for r in rows])
AIR = np.array([r[5] for r in rows])
SIG = np.array([int(r[6]) for r in rows])

sig_idx = np.where(SIG > 0)[0]
sig_t = T[sig_idx]
print(f"共 {len(sig_idx)} 个信号，{len(sig_idx)//2} 组\n")

# ---- 静音基线（无信号时段） ----
quiet = np.ones(len(T), dtype=bool)
for i in sig_idx:
    quiet[max(0, i - 50):i + 250] = False    # 信号前 1s 到后 5s 排除

print("=== 基线段（远离信号的时段）统计 ===")
for name, arr in (("RMS", RMS), ("低<300", LO), ("中1k", MID),
                  ("高5k", HI), ("风3.2k", AIR)):
    q = arr[quiet]
    if len(q) == 0:
        print(f"  {name:>8}: 无基线样本")
        continue
    print(f"  {name:>8}: P50={np.percentile(q,50):.5f} "
          f"P90={np.percentile(q,90):.5f} P99={np.percentile(q,99):.5f}")

print("\n=== 每次动作：信号对之后 8 秒的音频演变 ===")
groups = []
cur = [sig_idx[0]]
for i in sig_idx[1:]:
    if T[i] - T[cur[-1]] < 0.5:
        cur.append(i)
    else:
        groups.append(cur)
        cur = [i]
groups.append(cur)

for gi, g in enumerate(groups, 1):
    t_sig = T[g[0]]
    t_last = T[g[-1]]
    win = (T >= t_sig - 0.3) & (T <= t_sig + 8.0)
    if not win.any():
        continue
    print(f"\n-- 组{gi}: 信号 {t_sig:.2f}~{t_last:.2f}s "
          f"(间隔 {(t_last-t_sig)*1000:.0f}ms) --")
    print(f"   {'t':>6} {'RMS':>8} {'低':>8} {'中':>8} {'高':>8} {'风':>8}")
    idxs = np.where(win)[0]
    for j in idxs[::10]:          # 每 200ms 一行
        mark = " <<SIG" if SIG[j] else ""
        print(f"   {T[j]:6.2f} {RMS[j]:8.5f} {LO[j]:8.5f} {MID[j]:8.5f} "
              f"{HI[j]:8.5f} {AIR[j]:8.5f}{mark}")

print("\n\n=== 松开信号之后，音频何时回落 ===")
for gi, g in enumerate(groups, 1):
    t_last = T[g[-1]]
    after = np.where((T > t_last + 0.3))[0]
    if len(after) < 20:
        continue
    # 找第一个持续 300ms 低于基线的点
    base50 = np.percentile(RMS[quiet], 50)
    th = base50 * 1.15
    dropped = None
    for k in after:
        window = RMS[k:k + 15]
        if len(window) >= 15 and np.all(window < th):
            dropped = T[k]
            break
    if dropped:
        print(f"  组{gi}: 松开={t_last:6.2f}s → 音频回落={dropped:6.2f}s "
              f"拖尾={dropped - t_last:5.2f}s")
    else:
        print(f"  组{gi}: 松开={t_last:6.2f}s → 8秒内未回落")
