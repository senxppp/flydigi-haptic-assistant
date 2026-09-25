"""探测虚拟 DualSense 的 HID 端点，找可读的扳机数据通道。

用法: python tools/probe_dualsense.py
"""
from __future__ import annotations

import sys
import time

import hid


def main() -> int:
    devs = hid.enumerate()
    print(f"=== 全部 HID 设备（{len(devs)} 个）===\n")
    targets = []
    for d in devs:
        vid = d.get("vendor_id", 0)
        pid = d.get("product_id", 0)
        up = d.get("usage_page", 0)
        ui = d.get("usage", 0)
        ifn = d.get("interface_number", -1)
        mfg = (d.get("manufacturer_string") or "")[:22]
        prd = (d.get("product_string") or "")[:26]
        mark = ""
        if vid == 0x054C or "ony" in mfg or "Dual" in prd:
            mark = "  <<< Sony/虚拟手柄"
            targets.append(d)
        if "37D7" in f"{vid:04X}" or "飞智" in mfg or "Flydigi" in mfg:
            mark = "  <<< 飞智"
        print(f"  {vid:04X}:{pid:04X} if={ifn:<2} up=0x{up:04X} us=0x{ui:04X} "
              f"{mfg:<22} {prd}{mark}")

    print(f"\n=== 探测 {len(targets)} 个 Sony/虚拟手柄端点的可读性 ===")
    for d in targets:
        print(f"\n--- if={d.get('interface_number')} up=0x{d.get('usage_page',0):04X} "
              f"path={d['path'][:70]!r}")
        try:
            h = hid.device()
            h.open_path(d["path"])
            print("    打开 ✓")
            h.set_nonblocking(1)
            got = 0
            for _ in range(60):   # 1.2 秒
                data = h.read(64)
                if data:
                    if got < 5:
                        print(f"    读: {' '.join(f'{b:02X}' for b in data[:20])}")
                    got += 1
                time.sleep(0.02)
            print(f"    1.2s 内读到 {got} 个报告")
            # 尝试写（看是否接受 Output Report）
            try:
                h.write([0x02] + [0] * 47)
                print("    写 ✓（接受 Output Report）")
            except Exception as e:
                print(f"    写 ✗: {e}")
            h.close()
        except Exception as e:
            print(f"    打开 ✗: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
