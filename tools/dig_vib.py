"""在服务 exe 里找 VibParams / VibType 的处理逻辑与相关 HID 命令字。"""

import re

EXE = "D:/Flydigi Space Station/SpaceStationService.exe"
data = open(EXE, "rb").read()

print("=== 含 Vib 的 UTF16 串 ===")
uni = re.findall(rb"(?:[ -~]\x00){3,}", data)
uni_s = []
seen = set()
for s in uni:
    t = s.decode("utf-16-le", errors="replace")
    if t in seen:
        continue
    seen.add(t)
    if "Vib" in t and len(t) < 100:
        uni_s.append(t)
for t in sorted(uni_s):
    print("   ", t)

print()
print("=== 含 Trigger / Pwm 的串（HID 相关） ===")
for t in sorted(seen):
    if ("Pwm" in t or "Trigger" in t) and len(t) < 100:
        print("   ", t)

print()
print("=== 找 HID 命令字常量上下文（0x12/0x13/0x14 附近） ===")
# .NET 里命令可能以字节数组形式出现
for pat in [b"TriggerVibration", b"TriggerControllerCommand"]:
    print(f"--- {pat} ---")
    for m in re.finditer(re.escape(pat), data):
        a = max(0, m.start() - 100)
        b = min(len(data), m.end() + 200)
        print("   ", repr(data[a:b][:300]))
        break
