"""验证：能否在输出层持有句柄的同时，以共享模式读取 0xFFA0。

背景：
    输出层 flydigi_vib.FlydigiVibration 用 CreateFileA(共享=3) 持有 0xFFA0 写句柄。
    之前 trigger 用 hid.device() 打开失败（hidapi 独占）。
    本脚本改走 CreateFileA(共享=3) 只读，验证是否可行。

用法:
    python tools/test_shared_read.py [秒数]
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time

import hid

VID, PID, UPAGE = 0x37D7, 0x2501, 0xFFA0
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
STATE = (4, 5, 6, 7, 8, 9, 10, 11)


def find_path():
    for d in hid.enumerate():
        if (d["vendor_id"] == VID and d["product_id"] == PID
                and d["usage_page"] == UPAGE):
            p = d["path"]
            return p.decode(errors="replace") if isinstance(p, bytes) else p
    return None


def main() -> int:
    path = find_path()
    if path is None:
        print("未找到 0xFFA0")
        return 1
    print(f"路径: {path[:70]}...")

    k = ctypes.WinDLL("kernel32")
    h = k.CreateFileA(path.encode(), 0x80000000, 3, None, 3, 0, None)
    if h in (-1, 0xFFFFFFFFFFFFFFFF):
        print(f"✗ 共享模式打开失败，err={ctypes.GetLastError()}")
        return 1
    print("✓ 共享模式打开成功（可在输出层占用时读取）")

    buf = ctypes.create_string_buffer(64)
    n = 0
    nz = 0
    samples = []
    t0 = time.time()
    print(f"\n读取 {DUR:.0f}s（请做滑索）...\n")
    last = 0.0

    while time.time() - t0 < DUR:
        nr = wt.DWORD(0)
        ok = k.ReadFile(h, buf, 64, ctypes.byref(nr), None)
        if ok and nr.value:
            n += 1
            data = buf.raw[:nr.value]
            if any(data[i] for i in STATE if i < len(data)):
                nz += 1
            now = time.time() - t0
            if now - last >= 1.0:
                last = now
                vals = " ".join(f"{data[i]:02X}" for i in STATE)
                print(f"  {now:6.1f}s  byte4~11: {vals}")
        else:
            time.sleep(0.002)

    k.CloseHandle(h)
    print(f"\n读到 {n} 帧，其中 byte4~11 非零 {nz} 帧（{nz/max(1,n)*100:.1f}%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
