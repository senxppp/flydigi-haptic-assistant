"""时间线抓取 0xFFA0 —— 把字节变化和「扳机震动开/关」对齐。

目的：找滑索的**结束信号**。
     之前三条路都失败（日志只在开头出 2 行、CallGripVibration 是 UI 通道、
     音频 RMS 在样本里是 0）。剩下唯一希望：手柄固件回传的扳机马达状态。

用法:
    python tools/timeline_trigger_state.py [秒数]

操作：运行后做 **3 次滑索**，长短各不同（比如 1 短、1 长、1 中），
      每次之间停 3 秒以上，方便区分。

输出：
    1) 每 50ms 一行的字节快照（只记录有字节变化的行），文件写到 tools/_timeline.csv
    2) 控制台实时打印关键字节 18..29 的数值变化
    3) 结束时给出每个字节的变化次数排行
"""
from __future__ import annotations

import csv
import sys
import time
from collections import defaultdict

import hid

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
VID, PID, UPAGE = 0x37D7, 0x2501, 0xFFA0
WATCH = list(range(12, 32))          # 重点观察区
CSV_PATH = "tools/_timeline.csv"


def find_device():
    return [d for d in hid.enumerate()
            if d.get("vendor_id") == VID and d.get("product_id") == PID
            and d.get("usage_page") == UPAGE]


def main() -> int:
    cands = find_device()
    if not cands:
        print(f"未找到 {VID:04X}:{PID:04X} usage_page 0x{UPAGE:04X}")
        return 1

    print(f"找到 {len(cands)} 个候选接口：")
    for d in cands:
        print(f"   interface={d.get('interface_number')} path={d['path']}")

    for d in cands:
        try:
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(1)
        except Exception as e:
            print(f"  x 打开失败 if={d.get('interface_number')}: {e}")
            continue

        print(f"\n=== 监听 interface={d.get('interface_number')} {DUR:.0f}s ===")
        print(">>> 请做 3 次滑索：短 / 长 / 中，中间各停 3 秒以上 <<<\n")

        rows: list = []
        changes = defaultdict(int)
        prev = None
        n = 0
        first_ts = None
        t_end = time.time() + DUR
        last_print = 0.0

        while time.time() < t_end:
            try:
                data = h.read(64)
            except Exception:
                break
            if not data:
                time.sleep(0.001)
                continue
            n += 1
            now = time.time()
            if first_ts is None:
                first_ts = now
            cur = list(data[:32])

            if prev is not None and len(cur) == len(prev):
                diff = [i for i, (a, b) in enumerate(zip(prev, cur)) if a != b]
                if diff:
                    for i in diff:
                        changes[i] += 1
                    rows.append([round(now - first_ts, 3)] + cur)

            # 实时打印（限流 200ms，避免刷屏）
            if now - last_print >= 0.2:
                last_print = now
                vals = " ".join(f"{cur[i]:02X}" for i in WATCH)
                print(f"  {now - first_ts:7.2f}s  {vals}")

            prev = cur

        h.close()

        print(f"\n读到 {n} 个报告，有变化的行 {len(rows)} 条")
        if changes:
            print(f"\n{'byte':>5} {'变化次数':>10}  占比")
            for i in sorted(changes, key=lambda k: -changes[k])[:24]:
                pct = changes[i] / max(1, n) * 100
                print(f"{i:>5} {changes[i]:>10}  {pct:>5.1f}%")

        if rows:
            with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["t"] + [f"b{i}" for i in range(32)])
                w.writerows(rows)
            print(f"\n时间线已写入 {CSV_PATH}（{len(rows)} 行）")
        else:
            print("\n（没有捕获到任何字节变化）")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
