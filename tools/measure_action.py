"""滑索时长实测 —— 按空格标记开始/结束，统计真实时长分布。

用法:
    python tools/measure_action.py

操作：
    - 滑索开始时按一次【回车】
    - 滑索结束时再按一次【回车】
    - 重复多次；输入 q 回车结束

输出：每次时长 + 统计（最小/中位/最大/均值），用于标定握把震动时长。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def main() -> int:
    print("=" * 56)
    print("滑索时长实测")
    print("=" * 56)
    print("操作：滑索【开始】按回车 → 滑索【结束】按回车，反复多次")
    print("      输入 q 回车退出并看统计\n")

    durs: list[float] = []
    mark: float | None = None
    try:
        while True:
            s = input("  [开始] " if mark is None else "  [结束] ")
            now = time.time()
            if s.strip().lower() == "q":
                break
            if mark is None:
                mark = now
                print("      ▸ 计时中…", flush=True)
            else:
                d = now - mark
                durs.append(d)
                n = len(durs)
                print(f"      ■ 第 {n} 次：{d:.2f} 秒", flush=True)
                mark = None
    except (EOFError, KeyboardInterrupt):
        pass

    if not durs:
        print("\n没有记录到任何动作。")
        return 0

    import statistics as st
    print(f"\n{'='*56}")
    print(f"共 {len(durs)} 次")
    print(f"  最小 {min(durs):.2f}s   最大 {max(durs):.2f}s")
    print(f"  中位 {st.median(durs):.2f}s   均值 {st.mean(durs):.2f}s")
    print(f"\n全部：")
    for i, d in enumerate(durs, 1):
        print(f"  {i:2d}. {d:6.2f}s  {'█' * int(d*4)}")
    print("\n把这份结果发给助手，用于标定握把震动时长。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
