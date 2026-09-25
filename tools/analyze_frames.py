"""分析录制的帧序列，定位「冲击 → 绵长呼啸」这类事件。

用法:
    python tools/analyze_frames.py logs/frames_whoosh.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k: float(v) for k, v in r.items()} for r in csv.DictReader(f)]


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("logs/frames_whoosh.csv")
    rows = load(path)
    if not rows:
        print("无数据")
        return 1

    print(f"总帧数 {len(rows)}，时长 {rows[-1]['t']:.1f}s\n")

    # 1) 找瞬态事件（onset 峰值）
    events = []
    for i, r in enumerate(rows):
        o = max(r["onset_l"], r["onset_r"])
        if o > 0.25:
            # 局部峰值判定：前后 3 帧内最大
            lo, hi = max(0, i - 3), min(len(rows), i + 4)
            if o >= max(max(rows[j]["onset_l"], rows[j]["onset_r"])
                        for j in range(lo, hi)):
                if not events or r["t"] - events[-1]["t"] > 1.5:
                    events.append(r)

    print(f"=== 检出 {len(events)} 个冲击事件 ===")
    for e in events:
        print(f"  t={e['t']:6.2f}s  onset={max(e['onset_l'],e['onset_r']):.2f}  "
              f"RMS={max(e['rms_l'],e['rms_r']):.4f}  "
              f"low={e['band_low_l']:.4f}  zcr={e['zcr_l']:.3f}  "
              f"驱动={int(max(e['drive_l'],e['drive_r']))}")

    # 2) 逐事件分析"尾随段"（冲击后 3 秒）
    print(f"\n=== 冲击后的尾随段（每 100ms 一采样点） ===")
    for e in events:
        t0 = e["t"]
        seg = [r for r in rows if t0 - 0.05 <= r["t"] <= t0 + 3.0]
        if not seg:
            continue
        print(f"\n--- 冲击 t={t0:.2f}s 之后 ---")
        print(f"{'Δt':>6} {'RMS':>8} {'onset':>6} {'low':>8} {'zcr':>7} {'驱动':>5}")
        last_print = -1.0
        for r in seg:
            dt = r["t"] - t0
            if dt - last_print < 0.1:
                continue
            last_print = dt
            rms = max(r["rms_l"], r["rms_r"])
            print(f"{dt:>5.2f}s {rms:>8.4f} {max(r['onset_l'],r['onset_r']):>6.2f} "
                  f"{r['band_low_l']:>8.4f} {r['zcr_l']:>7.3f} "
                  f"{int(max(r['drive_l'],r['drive_r'])):>5}")
            if dt > 2.5:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
