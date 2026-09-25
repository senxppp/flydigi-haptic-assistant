"""对照实验：静止 vs 滑索 —— 判定 0xFFA0 字节能否识别滑索状态。

设计（三阶段，每段 12 秒，用蜂鸣提示切换）：
    A 静止 : 手离开手柄，完全不动
    B 滑索 : 持续做滑索
    C 静止 : 手离开手柄，完全不动

判读：
    逐帧记录 32 字节 + 音频 RMS。事后统计每段各字节的：
      - 变化率（有多少帧该字节与上帧不同）
      - 值域（min~max）
      - 相邻帧差分的绝对均值（"抖动强度"）
    若 B 段某字节的抖动强度显著高于 A/C，则它就是候选状态字节。
    若三段几乎相同，则 0xFFA0 不含滑索状态，此路不通。

用法:
    python tools/ab_probe.py [每段秒数]
输出:
    tools/_ab.csv   逐帧 (t, phase, rms, b0..b31)
"""
from __future__ import annotations

import csv
import sys
import time

import numpy as np
import pyaudiowpatch as pyaudio

import hid

SEG = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
VID, PID, UPAGE = 0x37D7, 0x2501, 0xFFA0
BLOCK = 960
PHASES = [("静止A", SEG), ("滑索B", SEG), ("静止C", SEG)]


def beep(times=1):
    """极简提示音（Windows）"""
    try:
        import winsound
        for _ in range(times):
            winsound.Beep(880, 150)
            time.sleep(0.08)
    except Exception:
        print("\a", end="", flush=True)


def main() -> int:
    pa = pyaudio.PyAudio()
    dev = pa.get_default_wasapi_loopback()
    st = pa.open(format=pyaudio.paInt16, channels=2,
                 rate=int(dev["defaultSampleRate"]),
                 input=True, input_device_index=dev["index"],
                 frames_per_buffer=BLOCK)
    print(f"音频: {dev['name']}")

    h = None
    for d in hid.enumerate():
        if (d.get("vendor_id") == VID and d.get("product_id") == PID
                and d.get("usage_page") == UPAGE):
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(1)
            break
    if h is None:
        print("未找到 0xFFA0 接口")
        pa.terminate()
        return 1
    print("HID : 0xFFA0 已连接\n")

    rows = []
    t0 = time.perf_counter()
    prev = None

    for name, dur in PHASES:
        print(f"\n{'='*54}")
        print(f"  阶段 {name} —— 持续 {dur:.0f} 秒")
        if "滑索" in name:
            print("  >>> 请现在开始持续做滑索 <<<")
        else:
            print("  >>> 请把手离开手柄，完全不要动 <<<")
        print(f"{'='*54}")
        beep(2 if "滑索" in name else 1)

        t_end = t0 + sum(d for _, d in PHASES[:PHASES.index((name, dur)) + 1])
        last = 0.0
        sig = 0.0
        while time.perf_counter() < t_end:
            try:
                raw = st.read(BLOCK, exception_on_overflow=False)
            except Exception:
                continue
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(arr ** 2))) if arr.size else 0.0

            data = None
            try:
                data = h.read(64)
            except Exception:
                pass
            cur = list(data[:32]) if data else (prev or [0] * 32)

            now = time.perf_counter()
            rows.append([round(now - t0, 3), name[2], round(rms, 6)] + cur)

            sig = max(sig, rms)
            if now - last >= 2.0:
                last = now
                bar = "#" * min(30, int(rms * 400))
                print(f"    {now-t0:6.1f}s  rms={rms:.5f} {bar}")
            prev = cur

        print(f"  —— {name} 结束（峰值 rms={sig:.5f}）")

    st.stop_stream(); st.close(); pa.terminate(); h.close()

    with open("tools/_ab.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "phase", "rms"] + [f"b{i}" for i in range(32)])
        w.writerows(rows)

    print(f"\n{'='*54}\n已写入 tools/_ab.csv（{len(rows)} 帧）\n")

    # ---- 分析 ----
    import collections
    by = collections.defaultdict(list)
    for r in rows:
        by[r[1]].append(r)

    print("各阶段统计：")
    for k in ["A", "B", "C"]:
        if k not in by:
            continue
        g = by[k]
        rr = np.array([x[2] for x in g])
        print(f"  阶段{k}: {len(g)} 帧  rms P50={np.percentile(rr,50):.5f} "
              f"P90={np.percentile(rr,90):.5f}")

    print(f"\n{'byte':>5} {'A抖动':>8} {'B抖动':>8} {'C抖动':>8}   B/A比值")
    print("-" * 46)
    def jitter(g, bi):
        v = np.array([x[3 + bi] for x in g], dtype=np.float64)
        return float(np.mean(np.abs(np.diff(v)))) if len(v) > 1 else 0.0

    score = []
    for bi in range(32):
        ja = jitter(by.get("A", []), bi)
        jb = jitter(by.get("B", []), bi)
        jc = jitter(by.get("C", []), bi)
        ref = max(ja, jc, 1e-9)
        score.append((jb / ref, bi, ja, jb, jc))
    score.sort(reverse=True)
    for ratio, bi, ja, jb, jc in score[:16]:
        flag = "  <<<" if ratio > 2.0 else ""
        print(f"{bi:>5} {ja:>8.3f} {jb:>8.3f} {jc:>8.3f}   {ratio:>6.2f}{flag}")

    top = score[0]
    print(f"\n最强候选：byte {top[1]}，B段抖动是静止段的 {top[0]:.2f} 倍")
    if top[0] > 2.0:
        print("=> 有区分度！0xFFA0 可用于识别滑索状态。")
    else:
        print("=> 无区分度。0xFFA0 不含滑索状态，此路不通。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
