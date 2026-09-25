"""参数扫描：在真实抓取数据上找出一组能正确匹配滑索时长的判定参数。

背景：
    滑索音频是锯齿状的（起手高峰 → 回落 → 再起），
    短基准窗口 + 比例判定会把中间回落误判成结束，
    导致所有动作都在 0.4~0.8s 被秒杀（离线重放已证实）。

    因此需要扫描 (fall_ratio, base_win_s, arm_peak) 的组合，
    找出能同时覆盖 4 个真实音频活跃段的参数。

评价标准：
    用「动作时长 / 真实段时长」的偏差衡量。理想是 0.85~1.15 之间。
"""
from __future__ import annotations

import csv
import itertools
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.trigger.source import TriggerGripConfig, TriggerGripSource   # noqa: E402

LOG_SIGNALS = [4.74, 4.83, 11.17, 11.29, 13.93, 14.06, 17.52, 17.61,
               19.38, 19.47, 22.98, 23.09, 24.98, 25.10, 31.45, 31.58]
TRUE = [(13.85, 18.54), (19.47, 23.73), (24.98, 30.02), (30.16, 32.09)]


def load():
    rows = []
    with open("tools/_dual_rms.csv", newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r, None)
        for a, b in r:
            rows.append((float(a), float(b)))
    return rows


def run(rows, fall, win, guard, arm, quiet_f, abs_q):
    cfg = TriggerGripConfig(enabled=True, drive=75, fall_ratio=fall,
                            base_win_s=win, attack_guard_ms=guard,
                            arm_peak=arm, quiet_frames=quiet_f, abs_quiet=abs_q)
    src = TriggerGripSource(cfg)
    sig = {}
    for s in LOG_SIGNALS:
        i = min(range(len(rows)), key=lambda k: abs(rows[k][0] - s))
        sig[i] = sig.get(i, 0) + 1

    acts = []
    st, prev = None, False
    for i, (t, rms) in enumerate(rows):
        if i in sig:
            with src._lock:
                src._buf.append((t, sig[i]))
        src.update(t, rms)
        if src._active and not prev:
            st = t
        elif not src._active and prev and st is not None:
            acts.append((st, t, t - st))
        prev = src._active
    return acts


def score(acts):
    """把动作与真实段做单向匹配，返回平均相对偏差（越小越好）+ 匹配数。"""
    if not acts:
        return 9.9, 0
    devs = []
    used = set()
    for a, b in TRUE:
        best, bi = 9.9, None
        for i, (x, y, d) in enumerate(acts):
            if i in used:
                continue
            # 起点接近
            if abs(x - a) > 1.2:
                continue
            rd = abs(d - (b - a)) / (b - a)
            if rd < best:
                best, bi = rd, i
        if bi is not None:
            used.add(bi)
            devs.append(best)
    if not devs:
        return 9.9, 0
    return sum(devs) / len(devs), len(devs)


def main():
    rows = load()
    print(f"载入 {len(rows)} 帧\n")

    grid_fall = [0.40, 0.45, 0.50, 0.55]
    grid_win = [0.60, 0.90, 1.20, 1.80]
    grid_arm = [0.0030, 0.0045, 0.0060]

    results = []
    for fall, win, arm in itertools.product(grid_fall, grid_win, grid_arm):
        acts = run(rows, fall, win, 700.0, arm, 4, 0.0012)
        sc, nmatch = score(acts)
        durs = [d for _, _, d in acts]
        results.append((sc, nmatch, fall, win, arm, len(acts), durs))

    results.sort(key=lambda x: (x[0], -x[1]))
    print(f"{'偏差':>6} {'匹配':>4} {'fall':>5} {'win':>5} {'arm':>7} "
          f"{'动作数':>6}  时长")
    print("-" * 78)
    for sc, nm, fall, win, arm, na, durs in results[:18]:
        ds = " ".join(f"{d:.2f}" for d in durs[:8])
        print(f"{sc:>6.3f} {nm:>4} {fall:>5.2f} {win:>5.2f} {arm:>7.4f} "
              f"{na:>6}  {ds}")

    print("\n参照真实段时长: " + " ".join(f"{b-a:.2f}" for a, b in TRUE))


if __name__ == "__main__":
    main()
