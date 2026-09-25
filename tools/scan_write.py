"""带播报的握把/扳机命令扫描器（第二轮，针对写命令族）。

设计要点：
  - 每轮明确播报【第 N 轮】+ cmd + 参数，方便用户定位
  - 每轮 1.2s 震动 + 0.6s 间隔
  - 覆盖写命令候选 0x11/0x12/0x13/0x14/0x15，各自多组参数布局
  - 每轮结束后清震动，避免串扰

用法:
    python tools/scan_write.py r3        # 扫写命令族 + 参数布局
"""

import ctypes
import ctypes.wintypes as wt
import sys
import time

sys.path.insert(0, "vib_out")
from flydigi_vib import find_vendor_path  # noqa: E402

OUT_REPORT_ID = 0x03
FRAME_LEN = 32


class Raw:
    def __init__(self):
        self.k = ctypes.WinDLL("kernel32")
        self.written = wt.DWORD(0)
        path = find_vendor_path()
        h = self.k.CreateFileA(path.encode(), 0xC0000000, 3, None, 3, 0, None)
        if h in (-1, 0xFFFFFFFFFFFFFFFF):
            raise OSError("打开失败")
        self.h = h

    def send(self, frame: bytes):
        buf = bytearray(FRAME_LEN)
        n = min(len(frame), FRAME_LEN)
        buf[:n] = frame[:n]
        return bool(self.k.WriteFile(self.h, bytes(buf), FRAME_LEN,
                                     ctypes.byref(self.written), None))

    def hold(self, frame: bytes, seconds=1.2, period=0.03):
        t_end = time.time() + seconds
        while time.time() < t_end:
            self.send(frame)
            time.sleep(period)

    def close(self):
        self.k.CloseHandle(self.h)


def mk(cmd, sub, a=0, b=0, c=0, d=0):
    return bytes([OUT_REPORT_ID, 0x5A, 0xA5, cmd, sub, a, b, c, d])


def r3(r: Raw):
    # (cmd, sub, 参数布局名, a,b,c,d)
    trials = []
    for cmd in (0x11, 0x12, 0x13, 0x14, 0x15):
        for sub in (0x01, 0x06):
            trials.append((cmd, sub, "扳机满(00 00 FF FF)", 0x00, 0x00, 0xFF, 0xFF))
            trials.append((cmd, sub, "四路满(FF FF FF FF)", 0xFF, 0xFF, 0xFF, 0xFF))

    print("=" * 62)
    print(" 扫描开始：共 %d 轮，每轮 1.2 秒" % len(trials))
    print(" 请【只关注扳机】！握把震属正常（可能是 0x12）")
    print(" 记住【第几轮】扳机有反应")
    print("=" * 62)
    for i, (cmd, sub, layout, a, b, c, d) in enumerate(trials, 1):
        print(f"\n>>> 【第 {i:2d} 轮】 cmd=0x{cmd:02X} sub=0x{sub:02X}  {layout}", flush=True)
        r.hold(mk(cmd, sub, a, b, c, d), seconds=1.2)
        r.send(mk(0x12, 0x06, 0, 0, 0, 0))   # 清场
        time.sleep(0.6)

    print("\n" + "=" * 62)
    print(" 扫描结束！告诉我扳机在第几轮有反应（有的话）")
    print("=" * 62)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "r3"
    r = Raw()
    try:
        if mode == "r3":
            r3(r)
        else:
            print(__doc__)
    finally:
        r.send(mk(0x12, 0x06, 0, 0, 0, 0))
        r.close()


if __name__ == "__main__":
    main()
