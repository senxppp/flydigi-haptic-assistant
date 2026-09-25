"""APEX5 接口探测：列出两个厂商接口的能力，并尝试在 0xFFEF 上发命令。

目的：判断"扳机震动"走哪个接口 / 哪条命令。

用法:
    python tools/probe_iface.py            # 只探测能力
    python tools/probe_iface.py send       # 在 0xFFEF 上试发一组命令
"""

import sys
import time

import hid

VID, PID = 0x37D7, 0x2501


def get_paths():
    out = {}
    for d in hid.enumerate():
        if d["vendor_id"] == VID and d["product_id"] == PID:
            p = d["path"].decode(errors="replace") if isinstance(d["path"], bytes) else d["path"]
            key = f"{d['usage_page']:#06x}&{d['usage']:#06x}"
            out[key] = p
    return out


def describe(path, label):
    print(f"\n=== {label} ===")
    print("path:", path)
    try:
        dev = hid.device()
        dev.open_path(path.encode() if isinstance(path, str) else path)
    except Exception as e:
        print("  打开失败:", e)
        return None
    try:
        m = dev.get_manufacturer_string()
        p = dev.get_product_string()
        print("  mfg:", m, "| product:", p)
        dev.set_nonblocking(1)
        got = 0
        for _ in range(3):
            data = dev.read(64)
            if data:
                print(f"  read: len={len(data)} {bytes(data[:24]).hex(' ')}")
                got += 1
        if got == 0:
            print("  read: 无数据（正常，这是只写接口）")
    finally:
        dev.close()
    return True


def send_test(path):
    print("\n=== 在 0xFFEF 上试发命令 ===")
    dev = hid.device()
    dev.open_path(path.encode() if isinstance(path, str) else path)
    try:
        trials = [
            ("0x12 震动 同0xFFA0", bytes([0x03, 0x5A, 0xA5, 0x12, 0x06, 0, 0, 255, 255] + [0] * 23)),
            ("0x13 试", bytes([0x03, 0x5A, 0xA5, 0x13, 0x06, 0, 0, 255, 255] + [0] * 23)),
            ("0x14 试", bytes([0x03, 0x5A, 0xA5, 0x14, 0x06, 0, 0, 255, 255] + [0] * 23)),
            ("0x20 试", bytes([0x03, 0x5A, 0xA5, 0x20, 0x06, 0, 0, 255, 255] + [0] * 23)),
        ]
        for label, frame in trials:
            print(f"  发 {label} ...", end="", flush=True)
            try:
                # 注意：HID 写需要把 report id 作为第一个字节，hidapi 要求包含
                n = dev.write(frame)
                print(f" ok({n})")
            except Exception as e:
                print(f" 失败: {e}")
            time.sleep(0.6)
    finally:
        dev.write(bytes([0x03, 0x5A, 0xA5, 0x12, 0x06] + [0] * 27))
        dev.close()


def main():
    paths = get_paths()
    for k, v in paths.items():
        print(f"{k} -> {v}")

    if "0xffa0&0x0001" in paths:
        describe(paths["0xffa0&0x0001"], "0xFFA0 Col01（震动写入）")
    if "0xffef&0x0001" in paths:
        describe(paths["0xffef&0x0001"], "0xFFEF Col02（上传通道）")

    if len(sys.argv) > 1 and sys.argv[1] == "send" and "0xffef&0x0001" in paths:
        send_test(paths["0xffef&0x0001"])
        print("\n完成。刚才 255 强度打的是扳机，感觉到了吗？")


if __name__ == "__main__":
    main()
