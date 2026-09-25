"""验证「呼呼声 = 扳机震动」假设。

同时监听两路：
  1) 虚拟 DualSense / 手柄的 HID 状态（看扳机数据是否可读）
  2) 空间站服务日志（看 ForceTrigger 何时触发）

用法:
    python tools/verify_trigger_corr.py [秒数]
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import hid  # noqa: E402

LOG = Path("D:/Flydigi Space Station/Logs/service_log_20260925.txt")
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0


def list_hid():
    """列出所有 USB HID 设备，标出 Sony/虚拟手柄。"""
    print("=== HID 设备枚举（找 Sony 虚拟 DualSense）===")
    for d in hid.enumerate():
        vid, pid = d.get("vendor_id"), d.get("product_id")
        name = d.get("product_string") or ""
        mfg = d.get("manufacturer_string") or ""
        up = d.get("usage_page", 0)
        ui = d.get("usage", 0)
        if vid == 0x054C or "ony" in mfg or "Dual" in name or "Wireless" in name:
            print(f"  VID={vid:04X} PID={pid:04X} up=0x{up:04X} usage=0x{ui:04X} "
                  f"if={d.get('interface_number')} | {mfg} {name}")
    print()


def tail_worker(stop: threading.Event, out: list) -> None:
    """后台线程：跟踪服务日志中的 ForceTrigger。"""
    try:
        pos = LOG.stat().st_size
    except OSError:
        pos = 0
    while not stop.is_set():
        try:
            size = LOG.stat().st_size
        except OSError:
            time.sleep(0.1)
            continue
        if size < pos:
            pos = 0
        if size > pos:
            try:
                with LOG.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                for line in chunk.splitlines():
                    if "ForceTrigger" in line or "Trigger" in line:
                        out.append((time.time(), line[:160]))
            except OSError:
                pass
        time.sleep(0.05)


def main() -> int:
    list_hid()

    # 尝试打开虚拟 DualSense 读取输入报告
    devs = [d for d in hid.enumerate()
            if d.get("vendor_id") == 0x054C and d.get("product_id") == 0x0CE6]
    print(f"=== 虚拟 DualSense 设备数: {len(devs)} ===")
    for d in devs:
        print(f"  if={d.get('interface_number')} up=0x{d.get('usage_page',0):04X} "
              f"path={d['path'][:60]!r}")

    reader = None
    for d in devs:
        try:
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(1)
            reader = (h, d)
            print(f"  ✓ 已打开 if={d.get('interface_number')} 用于读取")
            break
        except Exception as e:
            print(f"  ✗ 打开失败 if={d.get('interface_number')}: {e}")

    stop = threading.Event()
    log_events: list = []
    t = threading.Thread(target=tail_worker, args=(stop, log_events), daemon=True)
    t.start()

    print(f"\n监听 {DUR:.0f}s：请复现动作（冲击 + 呼呼声，注意扳机震动）\n")
    print(f"{'t':>7} {'HID 数据':<44} {'日志'}")
    print("-" * 76)

    t0 = time.time()
    hid_reports = 0
    try:
        while time.time() - t0 < DUR:
            if reader:
                data = reader[0].read(64)
                if data:
                    s = " ".join(f"{b:02X}" for b in data[:24])
                    mark = "  <<< 非零" if any(data[:24]) else ""
                    print(f"{time.time()-t0:>6.1f}s {s}{mark}")
                    hid_reports += 1
            # 打印新日志事件
            while log_events:
                ts, line = log_events.pop(0)
                print(f"{time.time()-t0:>6.1f}s {'':<44} {line}")
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if reader:
            reader[0].close()

    print(f"\nHID 报告数: {hid_reports}，日志事件数: {len(log_events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
