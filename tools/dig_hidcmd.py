"""在服务 exe 里找 HID 命令帧的字节结构。

.NET 里如果命令是硬编码字节数组，会以初始化数组的形式出现。
我们找 triggerType / vibration 相关的数值常量。

已知参数模型:
    triggerTypeVibration { scale, block, stroke, frequency }
    triggerType: 5 (振动), 0 (普通)
"""

import re

EXE = "D:/Flydigi Space Station/SpaceStationService.exe"
data = open(EXE, "rb").read()

# 找 "DefaultTriggerParam - Command: " 附近的代码（日志格式串）
for target in ["DefaultTriggerParam - Command: ", "LeftTriggerValue", "RightTriggerValue",
               "triggerTypeVibration", "TriggerTypeVibration"]:
    tb = target.encode("utf-16-le")
    hits = list(re.finditer(re.escape(tb), data))
    print(f"===== {target} ({len(hits)} 处) =====")
    for m in hits[:2]:
        a = max(0, m.start() - 400)
        b = min(len(data), m.end() + 600)
        chunk = data[a:b]
        # 只打可读部分
        s = chunk.decode("utf-16-le", errors="replace")
        printable = "".join(ch if 32 <= ord(ch) < 0x3000 else "." for ch in s)
        print("   ", repr(printable[:400]))
    print()

print("===== 搜索可能的 HID 帧常量数组 (5A A5 .. 形式) =====")
# .NET 字节数组常以 01 00 00 00 + len + data 形式
for pat in [b"\x5a\x00\xa5\x00", b"\x12\x00\x06\x00", b"\xa5\x00"]:
    n = data.count(pat)
    print(f"  {pat.hex(' ')}: {n} 次")
