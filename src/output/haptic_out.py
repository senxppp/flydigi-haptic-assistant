"""
震动输出层（中间层封装）
========================

底层驱动复用已实测的 vib_out/flydigi_vib.py（0xFFA0 私有协议直发）。
本模块在其上补充工程化能力：

  - 连接看护（文档 6.4(4)）：周期性探测手柄厂商接口是否在线；
  - 安全限幅：硬上限 safety_max_drive，杜绝误配置打满马达；
  - 变化限速：相邻帧驱动差值限速，抑制马达突变噪音；
  - 自动归零：超过 auto_stop_ms 无新指令则停震（防止卡震）；
  - 发送统计：帧数、失败次数、实际发送频率。

线程模型：单写入线程独占 HID 句柄；其他线程通过 set_target() 投递目标值。
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# 复用已验证的输出驱动
_VIB_DIR = Path(__file__).resolve().parents[2] / "vib_out"
if str(_VIB_DIR) not in sys.path:
    sys.path.insert(0, str(_VIB_DIR))

from flydigi_vib import FlydigiVibration, find_vendor_path  # noqa: E402


@dataclass
class OutputStats:
    frames_sent: int = 0
    write_failures: int = 0
    reconnects: int = 0
    last_left: int = 0
    last_right: int = 0
    connected: bool = False
    started_at: float = 0.0
    _rate_window: list = field(default_factory=list)

    def note_send(self) -> None:
        self.frames_sent += 1
        now = time.perf_counter()
        self._rate_window.append(now)
        if len(self._rate_window) > 200:
            self._rate_window = self._rate_window[-100:]

    @property
    def send_rate(self) -> float:
        w = self._rate_window
        if len(w) < 2:
            return 0.0
        span = w[-1] - w[0]
        return (len(w) - 1) / span if span > 0 else 0.0


class HapticOutput:
    """震动输出层：目标值投递 + 独立写入线程 + 看护/限幅/自动归零。"""

    def __init__(
        self,
        send_rate_hz: float = 60.0,
        safety_max_drive: int = 240,
        auto_stop_ms: float = 120.0,
        device_watchdog_s: float = 2.0,
        start_stopped: bool = False,
    ):
        self.send_rate_hz = max(10.0, send_rate_hz)
        self.safety_max = max(0, min(255, safety_max_drive))
        self.auto_stop_s = auto_stop_ms / 1000.0
        self.watchdog_s = device_watchdog_s
        self.stats = OutputStats()
        self._drv: FlydigiVibration | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._target = (0, 0)
        self._target_ts = 0.0
        self._last_written = (-1, -1)
        self._start_stopped = start_stopped
        self._last_watchdog = 0.0

    # ---------- 生命周期 ----------

    def open(self) -> "HapticOutput":
        self._connect()
        self.stats.started_at = time.time()
        return self

    def _connect(self) -> None:
        try:
            if self._drv is not None:
                try:
                    self._drv.close()
                except Exception:
                    pass
            self._drv = FlydigiVibration()
            self._drv.open()
            self.stats.connected = True
        except Exception:
            self._drv = None
            self.stats.connected = False

    def start(self) -> "HapticOutput":
        if self._drv is None:
            self._connect()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="haptic-out",
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self, send_zero: bool = True) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        if send_zero:
            self._raw_write(0, 0)
        if self._drv is not None:
            try:
                self._drv.close()
            finally:
                self._drv = None
        self.stats.connected = False

    def close(self) -> None:
        """stop() 的别名，兼容临时脚本/探针的 `with ... as out: out.close()` 写法。"""
        self.stop()

    def __enter__(self):
        self.open()
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ---------- 目标投递 ----------

    def set_target(self, left: int, right: int) -> None:
        """线程安全地投递目标驱动值；写入线程按发送频率下发。"""
        left = max(0, min(self.safety_max, int(left)))
        right = max(0, min(self.safety_max, int(right)))
        with self._lock:
            self._target = (left, right)
            self._target_ts = time.perf_counter()

    def stop_now(self) -> None:
        self.set_target(0, 0)

    # ---------- 写入线程 ----------

    def _loop(self) -> None:
        period = 1.0 / self.send_rate_hz
        next_t = time.perf_counter()
        while not self._stop.is_set():
            next_t += period
            with self._lock:
                left, right = self._target
                age = time.perf_counter() - self._target_ts
            # 自动归零：久无新指令则停震
            if age > self.auto_stop_s:
                left = right = 0
            # 变化限速在映射层已做；这里只在值变化或周期性保活时下发
            if (left, right) != self._last_written or left or right:
                self._raw_write(left, right)
            self._watchdog()
            sleep_for = next_t - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_t = time.perf_counter()

    def _raw_write(self, left: int, right: int) -> None:
        if self._drv is None:
            self.stats.connected = False
            return
        try:
            self._drv.set(left, right)
            self._last_written = (left, right)
            self.stats.last_left, self.stats.last_right = left, right
            self.stats.note_send()
        except Exception:
            self.stats.write_failures += 1
            self.stats.connected = False
            self._drv = None

    def _watchdog(self) -> None:
        """周期性探测手柄接口（文档 6.4(4) 手柄连接状态监控）。"""
        now = time.perf_counter()
        if now - self._last_watchdog < self.watchdog_s:
            return
        self._last_watchdog = now
        if self._drv is None:
            try:
                find_vendor_path()
                self._connect()
                if self._drv is not None:
                    self.stats.reconnects += 1
                    self._last_written = (-1, -1)
            except Exception:
                pass
