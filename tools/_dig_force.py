import re

f = 'D:/Flydigi Space Station/resources/app.asar'
data = open(f, 'rb').read()

for kw in [b'ForceTriggerControllerCommand', b'forceTrigger', b'ForceTrigger']:
    print(f'===== {kw.decode()} =====')
    c = 0
    for m in re.finditer(re.escape(kw), data):
        a = max(0, m.start() - 400)
        b = min(len(data), m.end() + 1200)
        t = data[a:b].decode('utf-8', errors='replace')
        # 过滤纯枚举列表
        if t.count('IpcCommandEnum') > 3:
            continue
        print(repr(t))
        print('-' * 90)
        c += 1
        if c >= 3:
            break
    print()
