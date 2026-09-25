"""监听/探测飞智服务的 UDP 端口 7878（AdapterTriggerService）。

目标：
  1. 看这个端口在收什么（游戏可能往这发扳机数据）
  2. 尝试主动发数据看反应

注意：如果服务用 UDP 做单向广播（发给游戏插件），我们只需 bind 同端口
      或用 SO_REUSEADDR 抓包。
"""

import socket
import struct
import sys
import time

PORT = 7878
ALT = 53787


def sniff(port, duration=15.0):
    """尝试绑定端口抓包。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except OSError:
        pass
    try:
        s.bind(("0.0.0.0", port))
        print(f"★ 成功绑定 UDP {port}")
    except OSError as e:
        print(f"绑定 {port} 失败: {e}")
        s.close()
        return

    s.settimeout(0.3)
    print(f"监听 {duration:.0f}s ... 请去游戏里扣扳机！", flush=True)
    t_end = time.time() + duration
    n = 0
    peers = {}
    while time.time() < t_end:
        try:
            data, addr = s.recvfrom(4096)
            n += 1
            peers[addr] = peers.get(addr, 0) + 1
            if n <= 20:
                print(f"  [{addr}] len={len(data)}: {data[:64].hex(' ')}")
        except socket.timeout:
            continue
        except OSError as e:
            print("  recv err:", e)
            break
    s.close()
    print(f"\n共收到 {n} 个包")
    if peers:
        print("来源统计:")
        for a, c in sorted(peers.items(), key=lambda x: -x[1]):
            print(f"   {a}: {c} 个")


def probe_send(port, payload):
    """向端口发一个测试包（用 socket 的 SO_REUSEADDR 可能不行，试试普通发送）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1.0)
    try:
        s.sendto(payload, ("127.0.0.1", port))
        print(f"已发送 {len(payload)} 字节到 127.0.0.1:{port}")
        try:
            data, addr = s.recvfrom(4096)
            print(f"  收到响应 [{addr}]: {data[:64].hex(' ')}")
        except socket.timeout:
            print("  无响应")
    finally:
        s.close()


def main():
    args = sys.argv[1:]
    if args and args[0] == "send":
        payload = b"FDG_PROTOCOL\n" + struct.pack("<i", 2) + b"\x08\x01"
        probe_send(PORT, payload)
        return
    dur = float(args[0]) if args else 15.0
    print(f"=== 抓 UDP {PORT} ===")
    sniff(PORT, dur)


if __name__ == "__main__":
    main()
