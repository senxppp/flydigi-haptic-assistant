"""实时跟踪空间站服务日志，抓取新出现的命令帧。

用途：用户在游戏里触发扳机震动时，看服务日志里冒出什么命令。

用法:
    python tools/tail_log.py            # 跟踪 30 秒
    python tools/tail_log.py 60         # 跟踪 60 秒
"""

import os
import re
import sys
import time

LOG = "D:/Flydigi Space Station/Logs/service_log_20260925.txt"
FRAME_RE = re.compile(r"((?:[0-9A-F]{2}-){3,}[0-9A-F]{2})")

# 关心的关键词
KEYS = ["ForceTrigger", "Trigger", "Vibration", "Rumble", "Adapter", "ack:", "cmdId"]


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    pos = os.path.getsize(LOG)
    print(f"开始跟踪（{dur:.0f}s），起点 offset={pos}")
    print(">>> 现在去游戏里扣扳机 / 制造震动 <<<\n", flush=True)

    t_end = time.time() + dur
    seen_frames = set()
    n_lines = 0
    while time.time() < t_end:
        try:
            size = os.path.getsize(LOG)
        except OSError:
            time.sleep(0.2)
            continue
        if size < pos:            # 日志被轮转
            print("[日志轮转，重置 offset]")
            pos = 0
        if size > pos:
            with open(LOG, "r", encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            for line in chunk.splitlines():
                n_lines += 1
                if not any(k in line for k in KEYS):
                    continue
                ts = line[:26].strip()
                # 提取命令名
                m = re.search(r"(take (\w+) from queue|Receive command from client|cmdId: (0x[0-9A-F]+))", line)
                tag = m.group(0) if m else ""
                fr = FRAME_RE.search(line)
                if fr:
                    fstr = fr.group(1)
                    if fstr not in seen_frames:
                        seen_frames.add(fstr)
                        head = "-".join(fstr.split("-")[:6])
                        print(f"[{ts}] {tag}  帧: {fstr[:80]}", flush=True)
                elif "ForceTrigger" in line or "Vibration" in line or "Trigger" in line:
                    print(f"[{ts}] {line[:180]}", flush=True)
        time.sleep(0.15)

    print(f"\n跟踪结束。共扫描 {n_lines} 行新日志，抓到 {len(seen_frames)} 个新帧。")


if __name__ == "__main__":
    main()
