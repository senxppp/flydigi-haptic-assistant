import re

f = 'D:/Flydigi Space Station/resources/app.asar'
data = open(f, 'rb').read()

# protobufjs 生成的类通常长这样: (function(){ ... }) 里带 fields: {cmdId:{type:"string",id:1},...}
# 或 minified: {cmdId:{type:"string",id:1},category:...}
pats = [
    rb'cmdId:\{type:"[^"]*",id:\d+',
    rb'\bcmdId\b[^,}]{0,40}\bid:\d+',
    rb'leftTriggerValue[^}]{0,80}',
    rb'leftGripValue[^}]{0,80}',
]
for p in pats:
    print(f'##### {p} #####')
    c = 0
    for m in re.finditer(p, data):
        a = max(0, m.start() - 260)
        b = min(len(data), m.end() + 460)
        t = data[a:b].decode('utf-8', errors='replace')
        print(repr(t))
        print('---')
        c += 1
        if c >= 4:
            break
    print()
