"""
Flydigi APEX5 (八爪鱼5) 私有协议震动输出驱动
============================================

通过实体手柄的厂商 HID 接口（usage page 0xFFA0）直接发送 32 字节命令帧驱动马达，
不依赖飞智空间站，DS 模式 / 普通模式下均可工作。

帧格式（逆向自 SpaceStationService.exe 的 Flydigi.ControllerSDK）:
    byte[0]  HID 输出报文 ID = 0x03（0xFFA0 接口描述符最后一个 ReportId 项）
    byte[1]  0x5A  魔数
    byte[2]  0xA5  魔数
    byte[3]  命令 ID（震动 = 0x12）
    byte[4]  0x06  子命令
    byte[5]  左握把马达 0-255
    byte[6]  右握把马达 0-255
    byte[7]  左扳机震动 0-255（IsSupportTriggerVibration 且 VibrationType ∈ {0,2} 时生效）
    byte[8]  右扳机震动 0-255
    byte[9..31] 0x00 填充

命令为即发即弃（fire-and-forget），控制器不回 ack。

用法:
    from flydigi_vib import FlydigiVibration
    vib = FlydigiVibration()
    vib.open()
    vib.set(left=255, right=255)      # 双握把全开
    vib.stop()
    vib.close()

命令行自测:
    python flydigi_vib.py test      # 三段脉冲：左 / 右 / 双
    python flydigi_vib.py sweep     # 双马达渐强 0->255
"""

import ctypes
import ctypes.wintypes as wt
import sys
import time

import hid  # hidapi，仅用于设备枚举

VID_FLYDIGI = 0x37D7
PID_APEX5 = 0x2501
VENDOR_USAGE_PAGE = 0xFFA0

OUT_REPORT_ID = 0x03
FRAME_LEN = 32
CMD_VIBRATION = 0x12


def find_vendor_path() -> str:
    """返回 APEX5 厂商接口（0xFFA0, MI_02 Col01）的 HID 设备路径。"""
    for d in hid.enumerate():
        if (d["vendor_id"] == VID_FLYDIGI and d["product_id"] == PID_APEX5
                and d["usage_page"] == VENDOR_USAGE_PAGE):
            path = d["path"]
            return path.decode(errors="replace") if isinstance(path, bytes) else path
    raise RuntimeError("未找到 APEX5 厂商接口（0xFFA0）。请确认手柄已连接、空间站服务在运行。")


class FlydigiVibration:
    """APEX5 震动马达低层驱动。线程不安全；持续震动需要周期性重发或按需 set(0)。"""

    def __init__(self):
        self._kernel32 = ctypes.WinDLL("kernel32")
        self._written = wt.DWORD(0)
        self._handle = None

    def open(self):
        k = self._kernel32
        path = find_vendor_path()
        h = k.CreateFileA(path.encode(), 0xC0000000, 3, None, 3, 0, None)
        if h in (-1, 0xFFFFFFFFFFFFFFFF):
            raise OSError(f"打开 HID 设备失败: {ctypes.GetLastError()} ({path[:60]}...)")
        self._handle = h
        return self

    def close(self):
        if self._handle is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        try:
            self.stop()
        finally:
            self.close()

    def set(self, left=0, right=0, trigger_left=0, trigger_right=0) -> bool:
        """设置四路马达强度（0-255）。0 即停止。"""
        if self._handle is None:
            raise RuntimeError("设备未打开，先调用 open()")
        frame = bytearray(FRAME_LEN)
        frame[0] = OUT_REPORT_ID
        frame[1] = 0x5A
        frame[2] = 0xA5
        frame[3] = CMD_VIBRATION
        frame[4] = 0x06
        frame[5] = max(0, min(255, int(left)))
        frame[6] = max(0, min(255, int(right)))
        frame[7] = max(0, min(255, int(trigger_left)))
        frame[8] = max(0, min(255, int(trigger_right)))
        ok = self._kernel32.WriteFile(self._handle, bytes(frame), FRAME_LEN,
                                      ctypes.byref(self._written), None)
        return bool(ok)

    def stop(self) -> bool:
        return self.set(0, 0, 0, 0)

    def pulse(self, left=255, right=255, trigger_left=0, trigger_right=0, duration=0.5):
        """震动指定时长后归零（阻塞）。"""
        self.set(left, right, trigger_left, trigger_right)
        time.sleep(duration)
        self.stop()


def _cli():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    with FlydigiVibration() as vib:
        if cmd == "test":
            for label, kw in [("仅左握把", dict(left=255)),
                              ("仅右握把", dict(right=255)),
                              ("双握把", dict(left=255, right=255))]:
                print(f"{label} ...", flush=True)
                vib.pulse(duration=1.2, **kw)
                time.sleep(0.8)
        elif cmd == "sweep":
            for v in range(0, 256, 17):
                vib.set(v, v)
                time.sleep(0.12)
            vib.stop()
        elif cmd == "left":
            vib.pulse(left=int(sys.argv[2]) if len(sys.argv) > 2 else 255, duration=2)
        elif cmd == "right":
            vib.pulse(right=int(sys.argv[2]) if len(sys.argv) > 2 else 255, duration=2)
        else:
            print(__doc__)
        print("完成")


if __name__ == "__main__":
    _cli()
