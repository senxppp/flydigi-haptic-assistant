import re

f = 'D:/Flydigi Space Station/resources/app.asar'
data = open(f, 'rb').read()

kws = [b'14206e7a', b'localStorage.getItem("uid', b'getUid', b'setUid', b'deviceCode']
for kw in kws:
    print(f'##### {kw.decode(errors="replace")} #####')
    c = 0
    for m in re.finditer(re.escape(kw), data):
        a = max(0, m.start() - 250)
        b = min(len(data), m.end() + 350)
        t = data[a:b].decode('utf-8', errors='replace')
        print(repr(t))
        print('---')
        c += 1
        if c >= 3:
            break
    print()
