"""从空间站日志里挖出所有真实的 HID 命令帧，并归类。

日志里已知会打帧的命令：
    5A-A5-A3-2A-xx-...   ReadMappingConfig 的 ack
    5A-A5-A7-13-xx-...   ReadRgbConfig 的 ack

目标：找到 5A-A5-XX-... 里 XX 的全部取值，形成命令字全集。
"""

import re
from collections import defaultdict

LOG = "D:/Flydigi Space Station/Logs/service_log_20260925.txt"
data = open(LOG, "rb").read().decode("utf-8", errors="replace")

# 抓形如 5A-A5-A3-2A-06-00-7F-...  的帧
pat = re.compile(r"((?:[0-9A-F]{2}-){3,}[0-9A-F]{2})")
frames = []
for line in data.splitlines():
    # 只抓 ack: 或 cmd 相关的行
    if "ack:" not in line and "cmdId" not in line and "5A-A5" not in line:
        continue
    for m in pat.finditer(line):
        s = m.group(1)
        parts = s.split("-")
        if len(parts) < 4:
            continue
        if parts[0] == "5A" and parts[1] == "A5":
            frames.append(parts)

print("抓到帧数:", len(frames))

# 按 byte3 (命令字) 归类
by_cmd = defaultdict(list)
for p in frames:
    if len(p) >= 4:
        by_cmd[p[2]].append(p)

print()
print("=== 命令字 byte3 分布 ===")
for cmd in sorted(by_cmd):
    lst = by_cmd[cmd]
    print(f"  cmd=0x{cmd}  出现 {len(lst)} 次")
    # 打印前 3 个样本
    for p in lst[:3]:
        print("      " + "-".join(p))

# 也按 byte4 归类看看
print()
print("=== byte4 (子命令/长度) 分布 ===")
by_sub = defaultdict(int)
for p in frames:
    if len(p) >= 5:
        by_sub[p[3]] += 1
for sub in sorted(by_sub):
    print(f"  sub=0x{sub}  {by_sub[sub]} 次")
