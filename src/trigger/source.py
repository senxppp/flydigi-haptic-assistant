"""扳机联动信号源 — 双信号组判定滑索起止。
=================================================================

★ 核心结论（阶段八，实测确认）
------------------------------
游戏日志 `ForceTriggerControllerCommandNewXInput` 的每一次**滑索**会
产生 **两组** 信号（每组 2 行，组内间隔 ~90ms）：

    组1（进入滑索）→ 滑索持续 6.4 秒左右 → 组2（脱离滑索）

实测 4 次滑索的"组1→组2"间隔：
    6.43s / 6.49s / 6.43s / 6.44s    ← 波动仅 0.06s

因此判定规则非常简单可靠：
    **奇数号组 = 开始震动，偶数号组 = 停止震动。**

组内去重：间隔 < dedup_ms（默认 300ms）的信号视为同一组。

为什么不用音频/HID：
    - 音频：滑索音频与 BGM 混在一起，分离比仅 1.3~1.4x，切不干净
    - HID 0xFFA0 byte4~11：反映的是"手柄输入活动"，
      用户"只移动视角"时也会非零 → 会把动作无限拖长（实测撞 20s 超时）
    - 日志信号：延迟仅 7ms，且是游戏引擎的真实意图，最可靠

兜底：
    A. 超时 max_ms（默认 20s）—— 防止漏掉"脱离"信号导致一直震动
    B. 可选音频静音线（abs_quiet）—— 极端情况下的安全网

用法:
    from src.trigger.source import TriggerGripSource, TriggerGripConfig
    src = TriggerGripSource(TriggerGripConfig(drive=75))
    src.start()
    ...  # 每帧
    drive = src.update(now, rms)     # 返回 0 或 drive
    src.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .logpath import resolve_log_path

log = logging.getLogger("trigger")


# ---------------------------------------------------------------- 配置

@dataclass
class TriggerGripConfig:
    """扳机联动参数（已按实测标定，改动前请先看模块 docstring）。"""

    enabled: bool = True
    drive: int = 75                 # 握把力度（冲击约 190~240，故不盖过）

    # --- 信号源：飞智服务日志（{date} 自动替换为当天 YYYYMMDD）---
    log_path: str = "D:/Flydigi Space Station/Logs/service_log_{date}.txt"
    log_key: str = "ForceTriggerControllerCommandNewXInput"
    poll_ms: float = 4.0            # 日志轮询间隔

    # --- 双信号组判定 ---
    dedup_ms: float = 300.0         # 组内去重窗口：间隔小于此值算同一组
    max_ms: float = 20000.0         # 单次动作兜底超时（防漏"脱离"信号）
    min_ms: float = 150.0           # 最短动作时长（防误触发的瞬时抖动）

    # --- 可选音频安全网（默认关闭）---
    use_audio_guard: bool = False
    abs_quiet: float = 0.0008       # 低于此值且持续 quiet_frames 帧则强制结束
    quiet_frames: int = 25          # 25 帧 = 500ms


# ---------------------------------------------------------------- 信号源

class TriggerGripSource:
    """日志尾随 + 双信号组奇偶判定，输出握把驱动值。"""

    def __init__(self, cfg: TriggerGripConfig | None = None):
        self.cfg = cfg or TriggerGripConfig()
        self._buf: list[tuple[float, int]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._log_path = Path(self.cfg.log_path)   # start() 会解析成实际日期路径

        # 运行时状态
        self._active = False
        self._t_start = 0.0
        self._last_sig_t = 0.0          # 上一个信号的到达时刻（用于组内去重）
        self._quiet_cnt = 0
        self._last_reason = ""

        # 统计
        self.n_trigger = 0              # 信号行数
        self.n_groups = 0               # 信号组数
        self.n_actions = 0              # 动作次数

    # ---------- 生命周期 ----------

    def start(self) -> None:
        if not self.cfg.enabled:
            return
        # 解析日志路径（自动匹配当天日期，找不到则回退最近一份）
        self._log_path = resolve_log_path(self.cfg.log_path)
        try:
            self._pos = self._log_path.stat().st_size
        except OSError:
            self._pos = 0
            log.warning("扳机日志不存在，扳机联动将不可用：%s", self._log_path)
        self._stop.clear()
        self._thread = threading.Thread(target=self._tail_loop, daemon=True,
                                        name="trigger-tail")
        self._thread.start()
        log.info("扳机联动已启动：力度=%d 判据=双信号组 去重=%.0fms 超时=%.0fs 日志=%s",
                 self.cfg.drive, self.cfg.dedup_ms, self.cfg.max_ms / 1000.0,
                 self._log_path.name)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None

    # ---------- 日志尾随 ----------

    def _tail_loop(self) -> None:
        p = self._pos
        last_date_check = 0.0
        while not self._stop.is_set():
            now = time.time()

            # 每 30 秒检查一次：是否跨天（日志文件需要切换）
            if now - last_date_check > 30.0:
                last_date_check = now
                try:
                    cur = resolve_log_path(self.cfg.log_path)
                except Exception:
                    cur = self._log_path
                if cur != self._log_path:
                    log.info("检测到日期变化，切换日志：%s → %s",
                             self._log_path.name, cur.name)
                    self._log_path = cur
                    p = 0          # 新文件从头读

            try:
                size = self._log_path.stat().st_size
            except OSError:
                time.sleep(0.05)
                continue
            if size < p:               # 日志被轮转/截断
                p = 0
            if size > p:
                try:
                    with self._log_path.open("r", encoding="utf-8",
                                             errors="replace") as f:
                        f.seek(p)
                        chunk = f.read()
                        p = f.tell()
                    cnt = chunk.count(self.cfg.log_key)
                    if cnt:
                        with self._lock:
                            self._buf.append((time.time(), cnt))
                except OSError:
                    pass
            self._stop.wait(self.cfg.poll_ms / 1000.0)

    # ---------- 每帧更新 ----------

    def update(self, now: float, rms: float) -> int:
        """喂入当前帧的时间与音频 RMS，返回应输出的握把驱动值（0 或 drive）。"""
        cfg = self.cfg
        if not cfg.enabled:
            return 0

        # 1) 消费信号，按组去重后做奇偶翻转
        pending = 0
        with self._lock:
            while self._buf:
                t_sig, cnt = self._buf.pop(0)
                pending += cnt
                # 组内去重：与上一个信号间隔 < dedup_ms 视为同一组，忽略
                if t_sig - self._last_sig_t < cfg.dedup_ms / 1000.0:
                    continue
                self._last_sig_t = t_sig
                self._on_group(now, t_sig)

        if pending:
            self.n_trigger += pending

        if not self._active:
            return 0

        # 2) 最短时长保护（防误触发的瞬时抖动）
        age_ms = (now - self._t_start) * 1000.0
        if age_ms < cfg.min_ms:
            return cfg.drive

        # 3) 可选音频安全网
        if cfg.use_audio_guard:
            if rms < cfg.abs_quiet:
                self._quiet_cnt += 1
                if self._quiet_cnt >= cfg.quiet_frames:
                    self._end(now, f"音频静音(rms={rms:.4f})")
                    return 0
            else:
                self._quiet_cnt = 0

        # 4) 兜底超时
        if age_ms > cfg.max_ms:
            self._end(now, "超时")
            return 0

        return cfg.drive

    def _on_group(self, now: float, t_sig: float) -> None:
        """处理一个「信号组」。奇数号组开始，偶数号组结束。"""
        self.n_groups += 1
        if not self._active:
            self._active = True
            self._t_start = t_sig
            self._quiet_cnt = 0
            self.n_actions += 1
            log.info("滑索开始 (第%d组信号)", self.n_groups)
        else:
            self._end(now, f"脱离信号(第{self.n_groups}组)", t=t_sig)

    def _end(self, now: float, reason: str, t: float | None = None) -> None:
        dur = (t if t is not None else now) - self._t_start
        self._active = False
        self._quiet_cnt = 0
        self._last_reason = reason
        log.info("滑索结束 时长 %.2fs  %s", dur, reason)

    # ---------- 状态 ----------

    @property
    def active(self) -> bool:
        return self._active

    def status(self) -> dict:
        return {
            "trigger_active": self._active,
            "trigger_drive": self.cfg.drive if self._active else 0,
            "trigger_events": self.n_trigger,
            "trigger_groups": self.n_groups,
            "trigger_actions": self.n_actions,
            "trigger_reason": self._last_reason,
        }

