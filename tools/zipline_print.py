"""滑索音频指纹抓取：日志信号 + 多频段能量 + RMS，同时对齐。

目的：
    用户澄清「滑索是按一下松开，之后滑索自己跑 3~5 秒」。
    因此「滑索进行中」这段时间**用户不碰手柄**，音频是唯一线索。

    需要弄清：
      1) 日志信号对（按下/松开）与滑索音频段的精确关系
      2) 滑索音效的频段特征（是否集中在某个频段，可与 BGM 区分）
      3) 松开之后音频还要响多久（拖尾长度是否稳定）

用法:
    python tools/zipline_print.py [秒数]

操作：运行后做 **4 次滑索**，每次之间停 4 秒以上。
      按照平时的操作即可（按一下松开）。

输出:
    tools/_zp.csv   逐帧 (t, rms, b_low, b_mid, b_high, b_air, sig)
"""
from __future__ import annotations

import csv
import os
import sys
import time

import numpy as np
import pyaudiowpatch as pyaudio

SEG = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
LOG = "D:/Flydigi Space Station/Logs/service_log_20260925.txt"
LOG_KEY = "ForceTriggerControllerCommandNewXInput"
RATE = 48000
BLOCK = 960          # 20ms


def biquad_bp(x, f0, q, rate):
    """简单带通（RBJ），返回滤波后信号。"""
    w0 = 2 * np.pi * f0 / rate
    alpha = np.sin(w0) / (2 * q)
    b0, b1, b2 = alpha, 0.0, -alpha
    a0, a1, a2 = 1 + alpha, -2 * np.cos(w0), 1 - alpha
    b = np.array([b0, b1, b2]) / a0
    a = np.array([1.0, a1 / a0, a2 / a0])
    y = np.zeros_like(x)
    x1 = x2 = y1 = y2 = 0.0
    for i, xi in enumerate(x):
        yi = b[0] * xi + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2
        x2, x1 = x1, xi
        y2, y1 = y1, yi
        y[i] = yi
    return y


class LogTail:
    def __init__(self, path):
        self.path, self.pos, self.n = path, 0, 0
        try:
            self.pos = os.path.getsize(path)
        except OSError:
            pass

    def poll(self) -> int:
        try:
            sz = os.path.getsize(self.path)
        except OSError:
            return 0
        if sz < self.pos:
            self.pos = 0
        if sz == self.pos:
            return 0
        with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(self.pos)
            chunk = f.read()
            self.pos = f.tell()
        c = chunk.count(LOG_KEY)
        self.n += c
        return c


def main() -> int:
    pa = pyaudio.PyAudio()
    dev = pa.get_default_wasapi_loopback()
    st = pa.open(format=pyaudio.paInt16, channels=2,
                 rate=int(dev["defaultSampleRate"]),
                 input=True, input_device_index=dev["index"],
                 frames_per_buffer=BLOCK)
    print(f"音频: {dev['name']}")
    tail = LogTail(LOG)
    print(f"日志: 从 {tail.pos} 开始\n")
    print(">>> 请做 4 次滑索（按一下松开即可），每次间隔 4 秒以上 <<<\n")

    rows = []
    t0 = time.perf_counter()
    t_end = t0 + SEG
    last = 0.0
    n_sig = 0
    sig_times = []

    while time.perf_counter() < t_end:
        try:
            raw = st.read(BLOCK, exception_on_overflow=False)
        except Exception:
            continue
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        mono = arr.reshape(-1, 2).mean(axis=1) if arr.size > 1 else arr
        rms = float(np.sqrt(np.mean(mono ** 2))) if mono.size else 0.0

        # 频段能量
        if mono.size:
            lo = np.sqrt(np.mean(biquad_bp(mono, 120, 0.9, RATE) ** 2))
            mid = np.sqrt(np.mean(biquad_bp(mono, 1000, 1.0, RATE) ** 2))
            hi = np.sqrt(np.mean(biquad_bp(mono, 5000, 1.0, RATE) ** 2))
            air = np.sqrt(np.mean(biquad_bp(mono, 3200, 0.7, RATE) ** 2))
        else:
            lo = mid = hi = air = 0.0

        c = tail.poll()
        if c:
            n_sig += c
            sig_times.append(round(time.perf_counter() - t0, 2))

        t = time.perf_counter() - t0
        rows.append([round(t, 3), round(rms, 6), round(lo, 6),
                     round(mid, 6), round(hi, 6), round(air, 6), c])

        if t - last >= 0.4:
            last = t
            print(f"  {t:6.1f}s rms={rms:.5f} 低={lo:.5f} 中={mid:.5f} "
                  f"高={hi:.5f} 风={air:.5f}{'  <<SIG' if c else ''}")

    st.stop_stream(); st.close(); pa.terminate()

    with open("tools/_zp.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "rms", "lo", "mid", "hi", "air", "sig"])
        w.writerows(rows)

    print(f"\n{'='*56}")
    print(f"已写入 tools/_zp.csv（{len(rows)} 帧）")
    print(f"日志信号共 {n_sig} 个，时刻：{sig_times}")

    r = np.array([x[1] for x in rows])
    print(f"\nRMS: P50={np.percentile(r,50):.5f} P90={np.percentile(r,90):.5f} "
          f"max={r.max():.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
