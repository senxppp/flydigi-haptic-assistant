"""监听虚拟 DualSense 的输入报告，找出随动作变化的字节。

用法: python tools/sniff_ds_bytes.py [秒数]
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict

import hid

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0

TARGET = None
for d in hid.enumerate():
    if d.get("vendor_id") == 0x054C and d.get("product_id") == 0x0CE6:
        TARGET = d
        break

if TARGET is None:
    print("未找到虚拟 DualSense")
    raise SystemExit(1)


def main() -> int:
    h = hid.device()
    h.open_path(TARGET["path"])
    h.set_nonblocking(1)
    print(f"监听 {DUR:.0f}s")
    print(">>> 请反复做那个动作（触发扳机震动）<<<\n")

    # 统计每个字节位的取值分布
    bit_stats = defaultdict(lambda: defaultdict(int))
    n = 0
    t_end = time.time() + DUR
    prev = None
    changes = defaultdict(int)

    while time.time() < t_end:
        data = h.read(64)
        if not data:
            time.sleep(0.005)
            continue
        n += 1
        if prev is not None and len(data) == len(prev):
            for i, (a, b) in enumerate(zip(prev, data)):
                if a != b:
                    changes[i] += 1
        prev = list(data)

    h.close()
    print(f"\n共读到 {n} 个报告\n")
    print("各字节变化次数（只列 >0 的）:")
    print(f"{'byte':>5} {'变化次数':>10}  占比")
    for i in sorted(changes, key=lambda k: -changes[k]):
        print(f"{i:>5} {changes[i]:>10}  {changes[i]/max(1,n)*100:>5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
