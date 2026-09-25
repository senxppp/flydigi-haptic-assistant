"""裸脉冲诊断：绕过中间层，直接持续重发震动帧。

用途：判断"手柄不震"到底是
  (a) 没写到对的 HID 接口 / 帧不对
  (b) 空间站占用接口
  (c) 马达本身没反应

用法:
    python tools/raw_pulse.py            # 默认序列
    python tools/raw_pulse.py 255 3      # 强度255 持续3秒（双握把）
    python tools/raw_pulse.py 255 3 L    # 仅左
    python tools/raw_pulse.py 255 3 R    # 仅右
    python tools/raw_pulse.py 255 3 T    # 仅扳机（左右）
"""

import sys
import time

sys.path.insert(0, "vib_out")
from flydigi_vib import FlydigiVibration, find_vendor_path  # noqa: E402


def hold(vib, left=0, right=0, tl=0, tr=0, seconds=3.0, period=0.03):
    """以 33Hz 持续重发，避免手柄端超时归零。"""
    t_end = time.time() + seconds
    n = 0
    while time.time() < t_end:
        vib.set(left, right, tl, tr)
        n += 1
        time.sleep(period)
    vib.stop()
    return n


def main():
    print("HID 接口:", find_vendor_path())
    vib = FlydigiVibration().open()
    try:
        args = sys.argv[1:]
        if args and args[0].isdigit():
            v = int(args[0])
            sec = float(args[1]) if len(args) > 1 else 3.0
            which = (args[2].upper() if len(args) > 2 else "B")
            kw = {"B": dict(left=v, right=v),
                  "L": dict(left=v),
                  "R": dict(right=v),
                  "T": dict(tl=v, tr=v)}.get(which, dict(left=v, right=v))
            print(f"发送 {which} 强度={v} 时长={sec}s ...", flush=True)
            n = hold(vib, seconds=sec, **kw)
            print(f"完成，共发 {n} 帧")
            return

        seq = [
            ("双握把 255", dict(left=255, right=255)),
            ("左扳机 255", dict(tl=255, tr=255)),
            ("四路全开 255", dict(left=255, right=255, tl=255, tr=255)),
        ]
        for label, kw in seq:
            print(f"→ {label}（1.5s）", flush=True)
            hold(vib, seconds=1.5, **kw)
            time.sleep(0.6)
        print("完成：如果你一次都没感觉到，说明不是强度问题")
    finally:
        vib.stop()
        vib.close()


if __name__ == "__main__":
    main()
