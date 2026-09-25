"""双通道对齐抓取：一次性确定滑索的**结束信号**到底来自哪一路。

思路：
    之前三条路都被单独试过，但从未**同时**测过，所以无法判断
    "音频掉落" 和 "HID 字节变化" 哪个才是真正的动作结束。

    本脚本在同一进程、同一时钟下同时记录：
      1) 音频 RMS 时间线（20ms 一帧，来自 WASAPI Loopback）
      2) 0xFFA0 私有接口字节时间线（有变化才记）
      3) 飞智日志的 ForceTrigger 时刻（每 50ms 扫一次文件增量）

用法:
    python tools/dual_probe.py [秒数]

操作：运行后做 **4 次滑索**，顺序固定为 长 → 短 → 短 → 长，
      每次之间停 3 秒以上。

输出：
    tools/_dual.csv        时间线（type, t, 数据）
    tools/_dual_rms.csv    纯音频 RMS 逐帧
    控制台实时打印三路关键事件
"""
from __future__ import annotations

import csv
import os
import re
import sys
import time
from collections import deque

import numpy as np
import pyaudiowpatch as pyaudio

try:
    import hid
    HAVE_HID = True
except Exception:
    HAVE_HID = False

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
LOG = "D:/Flydigi Space Station/Logs/service_log_20260925.txt"
LOG_KEY = "ForceTriggerControllerCommandNewXInput"
VID, PID, UPAGE = 0x37D7, 0x2501, 0xFFA0
WATCH = list(range(10, 32))

RATE = 48000
BLOCK = 960          # 20ms


# ---------------- 音频 ----------------
def open_loopback(pa):
    dev = pa.get_default_wasapi_loopback()
    st = pa.open(format=pyaudio.paInt16, channels=2,
                 rate=int(dev["defaultSampleRate"]),
                 input=True, input_device_index=dev["index"],
                 frames_per_buffer=BLOCK)
    return st, dev


# ---------------- HID ----------------
def open_hid():
    if not HAVE_HID:
        return None
    for d in hid.enumerate():
        if (d.get("vendor_id") == VID and d.get("product_id") == PID
                and d.get("usage_page") == UPAGE):
            try:
                h = hid.device()
                h.open_path(d["path"])
                h.set_nonblocking(1)
                return h
            except Exception as e:
                print(f"  HID 打开失败: {e}")
    return None


# ---------------- 日志 ----------------
class LogTail:
    def __init__(self, path):
        self.path = path
        self.pos = 0
        self.hits: deque = deque()
        try:
            self.pos = os.path.getsize(path)
        except OSError:
            pass

    def poll(self):
        try:
            sz = os.path.getsize(self.path)
        except OSError:
            return
        if sz < self.pos:
            self.pos = 0
        if sz == self.pos:
            return
        with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(self.pos)
            chunk = f.read()
            self.pos = f.tell()
        for line in chunk.splitlines():
            if LOG_KEY in line:
                self.hits.append(time.time())


def main() -> int:
    pa = pyaudio.PyAudio()
    try:
        st, dev = open_loopback(pa)
    except Exception as e:
        print(f"音频设备打开失败: {e}")
        pa.terminate()
        return 1
    print(f"音频: {dev['name']} {int(dev['defaultSampleRate'])}Hz")

    h = open_hid()
    print(f"HID : {'已连接 0xFFA0' if h else '未连接（跳过 HID 路）'}")

    tail = LogTail(LOG)
    print(f"日志: 从 {tail.pos} 字节处开始跟踪\n")

    rms_rows = []      # (t, rms)
    evt_rows = []      # (t, type, payload)
    t0 = time.perf_counter()
    t_end = t0 + DUR
    last_hid_print = 0.0
    prev_hid = None
    n_sig = 0
    last_print_line = 0.0

    print(">>> 请做 4 次滑索：长 -> 短 -> 短 -> 长，每次间隔 3 秒 <<<\n")

    while time.perf_counter() < t_end:
        # --- 1) 音频 ---
        try:
            raw = st.read(BLOCK, exception_on_overflow=False)
        except Exception:
            continue
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if arr.size:
            rms = float(np.sqrt(np.mean(arr ** 2)))
        else:
            rms = 0.0
        now = time.perf_counter()
        t = now - t0
        rms_rows.append((round(t, 3), round(rms, 6)))

        # --- 2) HID ---
        if h is not None:
            try:
                data = h.read(64)
            except Exception:
                data = None
            if data:
                cur = list(data[:32])
                if prev_hid is not None and len(cur) == len(prev_hid):
                    diff = [i for i, (a, b) in enumerate(zip(prev_hid, cur)) if a != b]
                    if diff:
                        evt_rows.append([round(t, 3), "hid", ",".join(map(str, diff))] + cur)
                        if now - last_hid_print >= 0.15:
                            last_hid_print = now
                            vals = " ".join(f"{cur[i]:02X}" for i in WATCH)
                            print(f"  [HID] {t:7.2f}s  {vals}   改={diff[:8]}")
                prev_hid = cur

        # --- 3) 日志 ---
        tail.poll()
        while tail.hits:
            ht = tail.hits.popleft()
            n_sig += 1
            evt_rows.append([round(t, 3), "log", f"sig#{n_sig}"])
            print(f"  [LOG] {t:7.2f}s  信号 #{n_sig}")

        # --- 4) 实时 RMS（限流） ---
        if t - last_print_line >= 0.5:
            last_print_line = t
            bar = "#" * min(40, int(rms * 400))
            print(f"  [RMS] {t:7.2f}s  {rms:.5f} {bar}")

    st.stop_stream()
    st.close()
    pa.terminate()
    if h is not None:
        h.close()

    total = time.perf_counter() - t0

    # ---------- 输出 ----------
    with open("tools/_dual_rms.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "rms"])
        w.writerows(rms_rows)
    with open("tools/_dual.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "type", "info"] + [f"b{i}" for i in range(32)])
        for r in evt_rows:
            w.writerow(r + [""] * (35 - len(r)))

    print(f"\n{'-'*60}")
    print(f"采集 {total:.1f}s：音频帧 {len(rms_rows)}  事件 {len(evt_rows)}  日志信号 {n_sig}")

    rms_arr = np.array([r[1] for r in rms_rows]) if rms_rows else np.array([0.0])
    print(f"RMS 分布: P50={np.percentile(rms_arr,50):.5f} "
          f"P90={np.percentile(rms_arr,90):.5f} "
          f"P99={np.percentile(rms_arr,99):.5f} max={rms_arr.max():.5f}")

    # 找音频活跃段（连续 >0.0015，>=0.2s）
    th = 0.0015
    segs = []
    cur = None
    for t, r in rms_rows:
        if r > th:
            if cur is None:
                cur = [t, t]
            else:
                cur[1] = t
        else:
            if cur is not None:
                if cur[1] - cur[0] >= 0.2:
                    segs.append(tuple(cur))
                cur = None
    if cur is not None and cur[1] - cur[0] >= 0.2:
        segs.append(tuple(cur))
    print(f"\n音频活跃段(>{th}, >=0.2s): {len(segs)} 个")
    for a, b in segs[:30]:
        print(f"   {a:7.2f} ~ {b:7.2f}s   时长 {b-a:5.2f}s")

    logs = [r[0] for r in evt_rows if r[1] == "log"]
    print(f"\n日志信号时刻: {['%.2f' % x for x in logs]}")

    print(f"\n已写入 tools/_dual.csv 与 tools/_dual_rms.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
