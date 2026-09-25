"""找前端发送 IPC 的具体实现（怎么把 JSON 送到服务）。"""

import re

f = 'D:/Flydigi Space Station/resources/app.asar'
data = open(f, 'rb').read()

# 找 sendMessage / write 的实现
for kw in [b'sendMessage', b'FDG_PROTOCOL', b'writeMessage', b'sendRequest']:
    print(f'===== {kw.decode()} =====')
    c = 0
    for m in re.finditer(re.escape(kw), data):
        a = max(0, m.start() - 500)
        b = min(len(data), m.end() + 900)
        t = data[a:b].decode('utf-8', errors='replace')
        # 跳过之前看过的
        if 'pipePath' in t and 'createConnection' in t:
            continue
        # 只要含编码逻辑的
        if 'write' in t.lower() or 'encode' in t.lower() or 'Buffer' in t:
            print(repr(t))
            print('-' * 90)
            c += 1
            if c >= 3:
                break
    print()
