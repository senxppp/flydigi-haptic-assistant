"""重新分析对照实验：以「用户真实操作」为分界，而不是蜂鸣分段。

用户澄清：
    第 3 声哔（24s）之后**并没有立刻放下手柄**，而是等滑索结束才放下。
    所以真实的「滑索结束」时刻在 24~28s 之间的某处，不是 24s。

本脚本的目标：**自动找出 byte4~11 的归零时刻**，并验证它是否就是滑索结束点。

判据：
    定义「手柄活动量」act(t) = sum(|byte_i - byte_{i-1}|) for i in 4..11
    静止时 act ≈ 0；滑索时 act 很大。
    找出 act 从大变小（越过阈值）的那个时刻 = 滑索结束时刻。
"""
from __future__ import annotations

import csv
import numpy as np

rows = []
with open("tools/_ab.csv", newline="", encoding="utf-8") as f:
    r = csv.reader(f)
    next(r, None)
    for x in r:
        rows.append(x)

T = np.array([float(x[0]) for x in rows])
PH = [x[1] for x in rows]
B = np.array([[int(x[3 + b]) for b in range(32)] for x in rows], dtype=np.int32)

# 手柄活动量：byte4~11 的逐帧变化绝对值之和
IMU = B[:, 4:12]
act = np.zeros(len(IMU))
act[1:] = np.sum(np.abs(np.diff(IMU, axis=0)), axis=1)

# 平滑（5 帧 = 100ms）
k = 5
smooth = np.convolve(act, np.ones(k) / k, mode="same")

print("时刻(s)  活动量(平滑)   ph")
print("-" * 38)
for i in range(0, len(rows), 25):
    bar = "#" * min(50, int(smooth[i] / 4))
    print(f"{T[i]:>7.2f} {smooth[i]:>11.1f}   {PH[i]}  {bar}")

# ---- 自动检测活动区间 ----
th = 2.0          # 活动阈值
active = smooth > th

segs = []
st = None
for i, a in enumerate(active):
    if a and st is None:
        st = i
    elif not a and st is not None:
        if T[i] - T[st] >= 0.3:
            segs.append((T[st], T[i], T[i] - T[st]))
        st = None
if st is not None:
    segs.append((T[st], T[-1], T[-1] - T[st]))

print(f"\n阈值={th}，检测到的手柄活动段：")
for a, b, d in segs:
    print(f"   {a:7.2f} ~ {b:7.2f}s   时长 {d:5.2f}s")

# ---- 看 byte4~11 归零的精确时刻 ----
print("\nbyte4~11 全零 vs 非零 的时间线（每 20 帧）：")
for i in range(0, len(rows), 20):
    nz = np.count_nonzero(B[i, 4:12])
    mark = "非零" if nz else "全零"
    print(f"  {T[i]:7.2f}s  {mark}  ({nz}/8 字节非零)")

# ---- 关键：找最后一个非零帧 ----
nz_any = np.array([np.count_nonzero(B[i, 4:12]) > 0 for i in range(len(rows))])
idx = np.where(nz_any)[0]
if len(idx):
    print(f"\n第一次非零: {T[idx[0]]:.2f}s")
    print(f"最后一次非零: {T[idx[-1]]:.2f}s")
    # 找中间的空档
    gaps = []
    for a, b in zip(idx, idx[1:]):
        if T[b] - T[a] > 0.3:
            gaps.append((T[a], T[b], T[b] - T[a]))
    print(f"\n中间的空档（非零 → 归零 → 再非零），共 {len(gaps)} 处：")
    for a, b, d in gaps:
        print(f"   归零 {a:7.2f} → 恢复 {b:7.2f}   断开 {d:5.2f}s")
