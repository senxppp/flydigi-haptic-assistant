"""找 AdapterTriggerService 监听的端口号，以及相关网络配置。"""

import re

EXE = "D:/Flydigi Space Station/SpaceStationService.exe"
data = open(EXE, "rb").read()

uni = re.findall(rb"(?:[ -~]\x00){4,}", data)
uni_s = [s.decode("utf-16-le", errors="replace") for s in uni]

kws = ["port", "Port", "Port:", "Listen", "socket", "Socket", "tcp", "TCP",
       "127.0.0.1", "localhost", "bind", "Bind"]
print("=== 含端口/监听关键字的串 ===")
seen = set()
for s in uni_s:
    if s in seen:
        continue
    if any(k in s for k in kws) and 3 < len(s) < 150:
        seen.add(s)
        print("   ", s)

print()
print("=== 数字端口候选（在 port 附近） ===")
# 找 ...on port: 附近的数字
for m in re.finditer(rb"(?:[ -~]\x00){4,}", data):
    s = m.group(0).decode("utf-16-le", errors="replace")
    if "port" in s.lower() and len(s) < 200:
        print("   ", repr(s))

print()
print("=== adapterTriggerGames.json 位置 ===")
for m in re.finditer(re.escape("adapterTriggerGames.json".encode("utf-16-le")), data):
    a = max(0, m.start() - 200)
    b = min(len(data), m.end() + 200)
    print(repr(data[a:b].decode("utf-16-le", errors="replace")))
