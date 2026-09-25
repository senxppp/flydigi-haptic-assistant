"""精确定位 AdapterTriggerService 的端口号。"""

import re

EXE = "D:/Flydigi Space Station/SpaceStationService.exe"
data = open(EXE, "rb").read()

# 在二进制里定位字符串的原始字节位置，看附近的整数
for target in ["AdapterTriggerService Start Adapter Trigger Service on port:",
               "AdapterTriggerService StartListen on port:",
               "AdapterTriggerService StartListen on port: "]:
    tb = target.encode("utf-16-le")
    print(f"===== {target} =====")
    for m in re.finditer(re.escape(tb), data):
        a = max(0, m.start() - 120)
        b = min(len(data), m.end() + 120)
        chunk = data[a:b]
        print("  offset:", m.start())
        # 附近的小整数（4 字节 LE，值在 1024~65535）
        for off in range(a, b - 4):
            v = int.from_bytes(data[off:off+4], "little")
            if 1024 <= v <= 65535:
                print(f"    候选端口 @ {off}: {v}")
        # 附近的 ascii/utf16 串
        print("    UTF16 附近:", repr(data[max(0,m.start()-300):m.start()].decode("utf-16-le", errors="replace")[-120:]))
        print()

print("===== 全局搜 127.0.0.1 / localhost 附近的端口 =====")
for pat in ["127.0.0.1", "localhost"]:
    for enc in ("utf-16-le", "ascii"):
        tb = pat.encode(enc)
        for m in re.finditer(re.escape(tb), data):
            a = max(0, m.start() - 60)
            b = min(len(data), m.end() + 80)
            s = data[a:b].decode(enc, errors="replace")
            if "port" in s.lower() or ":" in s:
                print(f"  [{enc}] {s!r}")
