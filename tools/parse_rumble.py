# -*- coding: utf-8 -*-
"""
parse_rumble.py — 解析 USBPcap 抓包文件，提取发往后柄的震动/输出指令。

USBPcap 链路层格式 (LINKTYPE_USBPCAP = 249)，每包 27 字节头部：
  uint16 headerLen | uint64 irpId | uint32 status | uint16 function |
  uint8  info (bit0=1 表示 设备->主机 IN; bit0=0 表示 主机->设备 OUT) |
  uint16 bus | uint16 device | uint8 endpoint | uint8 transfer | uint32 dataLength
OUT 包（主机->设备）其后紧跟 dataLength 字节的有效载荷。

用法：
  python parse_rumble.py <pcap文件> [--device N] [--all] [--follow]
    --device N  只显示 USB 地址为 N 的设备（默认自动统计所有设备）
    --all       同时显示 IN(上行)包，默认只显示 OUT(下行，即发给手柄的指令)
    --follow    持续跟踪文件增长，实时打印新到的 OUT 指令（Ctrl+C 退出）
"""
import argparse
import struct
import sys
import time

X360_REPORTS = {
    0x00: "RUMBLE(震动)",
    0x01: "LED",
}

def decode_x360(payload: bytes) -> str:
    """尝试按 Xbox360 输出报告解码"""
    if len(payload) >= 5 and payload[0] == 0x00 and payload[1] == 0x08:
        return f"X360震动 左马达={payload[3]} 右马达={payload[4]} ({payload[3]/255:.0%}/{payload[4]/255:.0%})"
    if len(payload) >= 3 and payload[0] == 0x01:
        return "X360 LED 设置"
    return ""

def parse_packets(path, offset=0):
    """生成器：从 offset 开始产出 (ts, device, endpoint, transfer, direction, payload)"""
    with open(path, "rb") as f:
        if offset == 0:
            gh = f.read(24)
            if len(gh) < 24:
                return
            magic = gh[:4]
            if magic == b"\xd4\xc3\xb2\xa1":
                endian = "<"
            elif magic == b"\xa1\xb2\xc3\xd4":
                endian = ">"
            else:
                print(f"[!] 不是 pcap 文件 (magic={magic.hex()})", file=sys.stderr)
                return
            linktype = struct.unpack(endian + "I", gh[20:24])[0]
            if linktype != 249:
                print(f"[!] linktype={linktype}，不是 USBPcap(249)，解析可能不正确", file=sys.stderr)
        else:
            f.seek(offset)
        while True:
            ph = f.read(16)
            if len(ph) < 16:
                return
            ts_sec, ts_usec, incl, orig = struct.unpack("<IIII", ph)
            if incl == 0 or incl > 65535 * 4:
                return
            data = f.read(incl)
            if len(data) < 27:
                return
            (hlen, irp, status, func, info, bus, dev, ep, xfer, dlen) = struct.unpack(
                "<HQIHBHHBBI", data[:27])
            direction = "IN" if (info & 0x01) else "OUT"
            payload = data[hlen:hlen + dlen] if dlen else b""
            yield (ts_sec + ts_usec / 1e6, dev, ep, xfer, direction, payload), f.tell()

def fmt_xfer(t):
    return {0: "CTRL", 1: "ISOC", 2: "BULK", 3: "INTR"}.get(t, str(t))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap")
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--follow", action="store_true")
    args = ap.parse_args()

    offset = 0
    t0 = None
    stats = {}
    while True:
        new_offset = offset
        for pkt, end in parse_packets(args.pcap, offset):
            ts, dev, ep, xfer, direction, payload = pkt
            new_offset = end
            if t0 is None:
                t0 = ts
            stats[dev] = stats.get(dev, 0) + 1
            if args.device is not None and dev != args.device:
                continue
            if direction == "IN" and not args.all:
                continue
            if direction == "IN" and not payload:
                continue
            note = decode_x360(payload) if direction == "OUT" else ""
            hexs = payload.hex(" ") if payload else "(无数据)"
            print(f"[{ts - t0:10.3f}s] dev={dev:3d} ep=0x{ep:02X} {fmt_xfer(xfer):4s} {direction:3s} len={len(payload):3d} {hexs}  {note}")
        offset = new_offset
        if not args.follow:
            break
        time.sleep(0.2)

    if not args.follow and args.device is None:
        print("\n=== 各设备包数统计 ===")
        for dev, cnt in sorted(stats.items()):
            print(f"  USB地址 {dev}: {cnt} 包")

if __name__ == "__main__":
    main()
