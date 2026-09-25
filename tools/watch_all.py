"""监视飞智服务的 UDP 端口流量变化 + 日志变化。

在用户于空间站 UI 触发扳机测试时，观察：
  1. UDP 7878/53787 是否有流量
  2. 日志是否出现新的命令
"""

import os
import re
import socket
import struct
import sys
import time

LOG = "D:/Flydigi Space Station/Logs/service_log_20260925.txt"
PORTS = [7878, 53787]


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
    logpos = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    print(f"=== 监视开始（{dur:.0f}s）===")
    print(f"日志起点 offset={logpos}")
    print(">>> 现在去空间站点扳机测试 <<<\n", flush=True)

    # 尝试 sniFF UDP（绑不上就跳过）
    socks = []
    for p in PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", p))
            s.settimeout(0.2)
            socks.append((p, s))
            print(f"  UDP {p}: 已绑定，可监听")
        except OSError as e:
            print(f"  UDP {p}: 绑定失败 ({e.errno}) — 跳过")
            s.close()
    print()

    t_end = time.time() + dur
    udp_hits = 0
    while time.time() < t_end:
        # UDP
        for p, s in socks:
            try:
                d, a = s.recvfrom(4096)
                udp_hits += 1
                print(f"[UDP {p}] {a} len={len(d)}: {d[:80].hex(' ')}", flush=True)
            except socket.timeout:
                pass
            except OSError:
                pass

        # 日志
        try:
            size = os.path.getsize(LOG)
        except OSError:
            size = logpos
        if size > logpos:
            with open(LOG, "r", encoding="utf-8", errors="replace") as f:
                f.seek(logpos)
                chunk = f.read()
                logpos = f.tell()
            for line in chunk.splitlines():
                if any(k in line for k in ["Trigger", "Vibration", "CallGrip", "CallTrigger",
                                           "take ", "Receive command"]):
                    # 只打有信息量的
                    if "take " in line or "cmdId" in line or "Vibration" in line or "Trigger" in line:
                        ts = line[:26].strip()
                        body = line[27:].strip() if len(line) > 27 else line
                        print(f"[LOG] {ts} {body[:200]}", flush=True)
        time.sleep(0.1)

    for _, s in socks:
        s.close()
    print(f"\n监视结束。UDP 收到 {udp_hits} 个包。")


if __name__ == "__main__":
    main()
