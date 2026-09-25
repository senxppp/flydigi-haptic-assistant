"""直读飞智私有接口 0xFFA0，找扳机震动状态。

背景：扳机震动指令发给 37D7:2501 usage_page 0xFFA0 这个接口。
      该接口**可读**（实测能 read 到数据）。若固件在扳机震动时回传状态，
      我们就能自动知道"滑索开始了/结束了"，不再依赖音频或日志。

用法:
    python tools/sniff_trigger_state.py [秒数]

操作：运行后请做几次滑索（长短都做），保持每次 2 秒以上间隔。
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict

import hid

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
VID, PID, UPAGE = 0x37D7, 0x2501, 0xFFA0


def find_device():
    cands = []
    for d in hid.enumerate():
        if (d.get("vendor_id") == VID and d.get("product_id") == PID
                and d.get("usage_page") == UPAGE):
            cands.append(d)
    return cands


def main() -> int:
    cands = find_device()
    if not cands:
        print(f"未找到 {VID:04X}:{PID:04X} usage_page 0x{UPAGE:04X}")
        return 1

    print(f"找到 {len(cands)} 个候选接口：")
    for d in cands:
        print(f"   interface={d.get('interface_number')} path={d['path']}")

    # 逐个尝试读取
    for d in cands:
        try:
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(1)
        except Exception as e:
            print(f"  ✗ 打开失败 if={d.get('interface_number')}: {e}")
            continue

        print(f"\n=== 监听 interface={d.get('interface_number')} {DUR:.0f}s ===")
        print(">>> 请做几次滑索（长短都做），每次间隔 2 秒以上 <<<\n")

        n = 0
        nonzero = 0
        changes = defaultdict(int)
        prev = None
        samples: list = []
        t_end = time.time() + DUR
        first_ts = None

        while time.time() < t_end:
            try:
                data = h.read(64)
            except Exception:
                break
            if not data:
                time.sleep(0.002)
                continue
            n += 1
            if first_ts is None:
                first_ts = time.time()
            if any(data):
                nonzero += 1
                if len(samples) < 40:
                    samples.append((time.time() - first_ts, list(data[:32])))
            if prev is not None and len(data) == len(prev):
                for i, (a, b) in enumerate(zip(prev, data)):
                    if a != b:
                        changes[i] += 1
            prev = list(data)

        h.close()
        print(f"\n读到 {n} 个报告（其中非零 {nonzero} 个）")
        if changes:
            print(f"{'byte':>5} {'变化次数':>10}  占比")
            for i in sorted(changes, key=lambda k: -changes[k])[:24]:
                print(f"{i:>5} {changes[i]:>10}  {changes[i]/max(1,n)*100:>5.1f}%")
        else:
            print("（没有任何字节变化 / 没有读到数据）")

        if samples:
            print("\n前若干个非零样本（byte 0..31）:")
            for ts, s in samples[:20]:
                print(f"  {ts:6.2f}s  " + " ".join(f"{b:02X}" for b in s))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
