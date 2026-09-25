"""
中间层主管线 — 捕获 → 分析 → 映射 → 输出
========================================

对应开发文档 1.4 核心信号链路、2.3 三层架构、6.1 多线程/异步处理架构。

线程模型（文档 6.1(4)）:
  [WASAPI 读线程]  LoopbackCapture 内部   —— 持续把 PCM 塞进有界队列
  [主处理线程]     Pipeline.run()         —— 按 20ms 节拍 取帧→分析→映射→投递
  [HID 写线程]     HapticOutput 内部      —— 按发送频率下发震动帧

数据经有界队列传递，处理线程不阻塞在音频读上（见 audio/loopback.py 的说明）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass


from ..analysis.features import FeatureExtractor, FrameFeatures
from ..audio.loopback import LoopbackCapture
from ..core.config import Config
from ..mapping.mapper import AdsrEnvelope, HapticMapper
from ..output.haptic_out import HapticOutput
from ..trigger.source import TriggerGripConfig, TriggerGripSource

log = logging.getLogger("pipeline")


@dataclass
class PipelineStats:
    frames: int = 0
    avg_process_ms: float = 0.0
    max_process_ms: float = 0.0
    avg_analysis_ms: float = 0.0
    started_at: float = 0.0
    _proc_sum: float = 0.0
    _ana_sum: float = 0.0

    def note(self, total_ms: float, analysis_ms: float) -> None:
        self.frames += 1
        self._proc_sum += total_ms
        self._ana_sum += analysis_ms
        self.avg_process_ms = self._proc_sum / self.frames
        self.avg_analysis_ms = self._ana_sum / self.frames
        self.max_process_ms = max(self.max_process_ms, total_ms)


class HapticPipeline:
    """把三层粘合成一条实时管线。"""

    def __init__(self, config: Config | None = None):
        self.config = config or Config.load()
        self.cfg = self.config
        d = self.cfg.data
        self.frame_ms = int(d["audio"]["frame_ms"])
        self.stats = PipelineStats()

        # --- 分析引擎 ---
        ana_cfg = self.cfg.build_analysis_config()
        env_cfg = self.cfg.build_envelope_config()
        self.extractor = FeatureExtractor(
            sample_rate=d["audio"]["sample_rate"], config=ana_cfg
        )

        # --- 映射层 ---
        mcfg = self.cfg.build_mapping_config()
        self.mapper = HapticMapper(mcfg, frame_ms=self.frame_ms)
        self._apply_envelope(env_cfg)

        # --- 捕获层 ---
        self.capture = LoopbackCapture(
            frame_ms=self.frame_ms,
            device_hint=d["audio"]["device_hint"],
            sample_rate=d["audio"]["sample_rate"],
            queue_seconds=d["audio"]["capture_queue_seconds"],
        )

        # --- 输出层 ---
        o = d["output"]
        self.output = HapticOutput(
            send_rate_hz=o["send_rate_hz"],
            safety_max_drive=o["safety_max_drive"],
            auto_stop_ms=o["auto_stop_ms"],
            device_watchdog_s=o["device_watchdog_s"],
        )

        # --- 扳机联动层（可选）---
        # 从飞智服务日志读扳机触发，驱动握把持续震动；输出与音频驱动取 max。
        tg = d.get("trigger", {})
        self.trigger = TriggerGripSource(TriggerGripConfig(
            enabled=bool(tg.get("enabled", False)),
            drive=int(tg.get("drive", 75)),
            log_path=str(tg.get("log_path", TriggerGripConfig.log_path)),
            log_key=str(tg.get("log_key", TriggerGripConfig.log_key)),
            poll_ms=float(tg.get("poll_ms", 4.0)),
            dedup_ms=float(tg.get("dedup_ms", 300.0)),
            max_ms=float(tg.get("max_ms", 20000.0)),
            min_ms=float(tg.get("min_ms", 150.0)),
            use_audio_guard=bool(tg.get("use_audio_guard", False)),
            abs_quiet=float(tg.get("abs_quiet", 0.0008)),
            quiet_frames=int(tg.get("quiet_frames", 25)),
        ))
        self._trigger_drive = 0

        self._running = False
        self._last_frame: FrameFeatures | None = None
        self._last_drive = None
        self._on_frame_cb = None

    # ---------- 配置热更新 ----------

    def _apply_envelope(self, env_cfg: dict) -> None:
        for key in ("L", "R"):
            e: AdsrEnvelope = self.mapper._env[key]
            e.attack_ms = env_cfg.get("attack_ms", e.attack_ms)
            e.decay_ms = env_cfg.get("decay_ms", e.decay_ms)
            e.release_ms = env_cfg.get("release_ms", e.release_ms)
            e.sustain_level = env_cfg.get("sustain_level", e.sustain_level)

    def set_preset(self, name: str) -> None:
        """运行时切换预设（文档 6.2(5)）。"""
        self.cfg.set_preset(name)
        ana_cfg = self.cfg.build_analysis_config()
        env_cfg = self.cfg.build_envelope_config()
        self.extractor = FeatureExtractor(
            sample_rate=self.cfg.data["audio"]["sample_rate"], config=ana_cfg
        )
        self.mapper = HapticMapper(self.cfg.build_mapping_config(),
                                   frame_ms=self.frame_ms)
        self._apply_envelope(env_cfg)
        log.info("已切换预设: %s", name)

    def set_master_gain(self, gain: float) -> None:
        self.cfg.data["mapping"]["master_gain"] = max(0.0, min(1.0, gain))
        self.mapper.cfg.master_gain = self.cfg.data["mapping"]["master_gain"]

    # ---------- 运行 ----------

    def run(self, on_frame=None, max_seconds: float | None = None,
            stop_event=None) -> None:
        """启动管线并阻塞运行。on_frame(stats_dict) 每帧回调（用于 UI）。

        max_seconds: 到时自动停止（压测/自测用）。
        stop_event : threading.Event，置位后退出循环。
        """
        self._on_frame_cb = on_frame
        self.capture.start()
        self.output.open()
        self.output.start()
        self.trigger.start()
        self.stats.started_at = time.time()
        self._running = True
        log.info("管线启动：设备=%s %dHz %dch 帧长=%dms 发送=%.0fHz 扳机联动=%s",
                 self.capture.fmt.device_name, self.capture.fmt.sample_rate,
                 self.capture.fmt.channels, self.frame_ms,
                 self.output.send_rate_hz,
                 "开" if self.trigger.cfg.enabled else "关")
        t_end = (time.time() + max_seconds) if max_seconds else None
        try:
            while self._running:
                if stop_event is not None and stop_event.is_set():
                    break
                if t_end is not None and time.time() >= t_end:
                    break
                self.tick()
        except KeyboardInterrupt:
            log.info("收到中断，正在停止…")
        finally:
            self.shutdown()

    def tick(self) -> tuple[int, int]:
        """处理一帧：读音频 → 提取特征 → 映射 → 合并扳机 → 投递输出。

        注意：性能统计**刻意排除** read_frame() 的节拍等待时间，只计真实计算
        开销（分析+映射），否则 avg_process_ms 会≈帧长（20ms）而失去意义。

        扳机联动：扳机信号触发时握把以固定力度持续震动，与音频驱动**取 max**
        （不是相加，避免两者叠加超过冲击峰值）。
        """
        frame = self.capture.read_frame()
        t0 = time.perf_counter()
        feats = self.extractor.extract(frame)
        drive = self.mapper.map_frame(feats)

        # 扳机联动：用当前帧的音频能量驱动结束判定
        rms = max(feats.left.rms, feats.right.rms)
        self._trigger_drive = self.trigger.update(time.time(), rms)
        out_l = max(drive.left, self._trigger_drive)
        out_r = max(drive.right, self._trigger_drive)

        compute_ms = (time.perf_counter() - t0) * 1000.0
        self.output.set_target(out_l, out_r)
        self.stats.note(compute_ms, feats.process_ms)
        self._last_frame = feats
        self._last_drive = drive
        if self._on_frame_cb is not None:
            try:
                self._on_frame_cb(self.status())
            except Exception as e:
                # 回调异常只报一次，避免刷屏；否则会被静默吞掉导致"录到 0 帧"这类诡异现象
                if not getattr(self, "_cb_err_logged", False):
                    log.warning("on_frame 回调异常（后续相同异常不再提示）: %r", e)
                    self._cb_err_logged = True
        return out_l, out_r

    def shutdown(self) -> None:
        if not self._running and self.capture._pa is None:
            return
        self._running = False
        try:
            self.trigger.stop()
        finally:
            try:
                self.capture.stop()
            finally:
                self.output.stop()
        log.info("管线已停止：处理 %d 帧，平均耗时 %.2fms（分析 %.2fms，峰值 %.2fms）",
                 self.stats.frames, self.stats.avg_process_ms,
                 self.stats.avg_analysis_ms, self.stats.max_process_ms)

    # ---------- 状态快照（供 UI / 日志） ----------

    def status(self) -> dict:
        f = self._last_frame
        d = self._last_drive
        s = {
            "frames": self.stats.frames,
            "process_ms": self.stats.avg_process_ms,
            "max_process_ms": self.stats.max_process_ms,
            "rms_l": f.left.rms if f else 0.0,
            "rms_r": f.right.rms if f else 0.0,
            "onset_l": f.left.onset if f else 0.0,
            "onset_r": f.right.onset if f else 0.0,
            "zcr_l": f.left.zcr if f else 0.0,
            "zcr_r": f.right.zcr if f else 0.0,
            "band_low": f.left.band_low if f else 0.0,
            "band_low_r": f.right.band_low if f else 0.0,
            "drive_l": d.left if d else 0,
            "drive_r": d.right if d else 0,
            "agc_gain": d.agc_gain if d else 1.0,
            "underrun": self.capture.stats.underrun_ratio,
            "dropped": self.capture.dropped_samples,
            "read_errors": self.capture.stats.read_errors,
            "send_rate": self.output.stats.send_rate,
            "connected": self.output.stats.connected,
            "write_failures": self.output.stats.write_failures,
            "reconnects": self.output.stats.reconnects,
        }
        s.update(self.trigger.status())
        return s
