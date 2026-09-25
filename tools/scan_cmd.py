"""APEX5 命令字扫描器：找"扳机震动"对应的命令。

原理：
  - 0xFFA0 Col01 是已知可写接口，byte3=命令字，byte4=子命令，byte5..8=参数
  - 已知 0x12 是握把震动（byte5=左握把 byte6=右握把，byte7/8 无效）
  - 扳机震动可能：① 另一个命令字 ② 0x12 的另一个子命令 ③ 需要触发模式设置

策略（分三轮，每轮你只需反馈"有感/无感"）：
  R1: 只改命令字 byte3 = 0x00..0x3F，byte4=0x06，byte5..8 全 0xFF
  R2: 固定 byte3=0x12，改 byte4 子命令 0x00..0x0F
  R3: 针对 R1/R2 有反应的候选，改参数布局

用法:
    python tools/scan_cmd.py r1          # 第一轮
    python tools/scan_cmd.py r2
    python tools/scan_cmd.py frame 03 5a a5 12 06 ff ff ff ff   # 发自定义帧
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
        return bool(self.k.WriteFile(self.h, bytes(buf), FRAME_LEN, ctypes.byref(self.written), None))

    def hold(self, frame: bytes, seconds=1.0, period=0.03):
        t_end = time.time() + seconds
        while time.time() < t_end:
            self.send(frame)
            time.sleep(period)

    def close(self):
        self.k.CloseHandle(self.h)


def mk(cmd, sub, a=0, b=0, c=0, d=0):
    return bytes([OUT_REPORT_ID, 0x5A, 0xA5, cmd, sub, a, b, c, d])


def r1(r: Raw):
    print("=== R1：扫命令字 byte3 = 0x00..0x3F ===")
    print("每个命令字持续 0.8s，参数 byte5..8 = 0xFF（四路满）")
    print("注意感受【扳机】是否震动！握把震属正常（可能是已知的震动命令）\n")
    for cmd in range(0x00, 0x40):
        print(f"  cmd=0x{cmd:02X} ...", end="", flush=True)
        r.hold(mk(cmd, 0x06, 0xFF, 0xFF, 0xFF, 0xFF), seconds=0.8)
        r.send(mk(0x12, 0x06, 0, 0, 0, 0))  # 清
        time.sleep(0.35)
        print(" done")
    print("\nR1 完成。哪些 cmd 号让扳机震了？告诉我编号。")


def r2(r: Raw):
    print("=== R2：固定 cmd=0x12，扫子命令 byte4 = 0x00..0x1F ===")
    print("注意感受【扳机】！\n")
    for sub in range(0x00, 0x20):
        print(f"  sub=0x{sub:02X} ...", end="", flush=True)
        r.hold(mk(0x12, sub, 0xFF, 0xFF, 0xFF, 0xFF), seconds=0.8)
        r.send(mk(0x12, 0x06, 0, 0, 0, 0))
        time.sleep(0.35)
        print(" done")
    print("\nR2 完成。哪些 sub 让扳机震了？")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "r1"
    r = Raw()
    try:
        if mode == "r1":
            r1(r)
        elif mode == "r2":
            r2(r)
        elif mode == "frame":
            vals = [int(x, 16) for x in sys.argv[2:]]
            f = bytes(vals)
            print("发送:", f.hex(" "))
            r.hold(f, seconds=float(sys.argv[2 + len(vals)]) if len(sys.argv) > 2 + len(vals) else 2.0)
            print("完成")
        else:
            print(__doc__)
    finally:
        r.send(mk(0x12, 0x06, 0, 0, 0, 0))
        r.close()


if __name__ == "__main__":
    main()
