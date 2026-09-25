"""挖掘 SpaceStationService.exe 里与扳机/震动相关的字符串与帧格式。

.NET 程序集的字符串以 UTF-16 为主，也会有 ASCII。
"""

import re
import sys

EXE = "D:/Flydigi Space Station/SpaceStationService.exe"

print("读取 exe ...")
data = open(EXE, "rb").read()
print("大小:", len(data))

# UTF-16LE 字符串
uni = re.findall(rb"(?:[ -~]\x00){4,}", data)
uni_s = [s.decode("utf-16-le", errors="replace") for s in uni]
uni_set = set(uni_s)

asc = re.findall(rb"[ -~]{5,}", data)
asc_s = [s.decode("ascii", errors="replace") for s in asc]
asc_set = set(asc_s)

print(f"UTF16 串: {len(uni_set)}  ASCII 串: {len(asc_set)}")
print()

kws = ["Trigger", "Vibration", "Rumble", "Force", "Ack", "Cmd", "Grip",
       "NewXInput", "Adapter", "PS5", "DualSense", "0x12", "5A", "A5"]
for kw in kws:
    hits_u = sorted(s for s in uni_set if kw in s and len(s) < 120)
    hits_a = sorted(s for s in asc_set if kw in s and len(s) < 120)
    allh = hits_u + hits_a
    if not allh:
        continue
    print(f"--- 含 '{kw}' 的串 ({len(allh)}) ---")
    for s in allh[:25]:
        print("   ", s)
    print()
