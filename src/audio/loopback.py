"""
音频拦截层 — WASAPI Loopback 捕获
==================================

对应开发文档第四章（4.2 音频流拦截实现 / 4.3 音频流预处理）。

设计要点（均为实测驱动，详见 README「实测坑位」）：

1. **绝不能在消费侧直接 read()**
   WASAPI Loopback 在目标设备无音频播放时**不产出数据**，`read()` 会永久阻塞；
   有声时又可能一次吐出积压的多块数据。两种行为都会打乱分析节拍。
   → 本模块把「读」与「消费」彻底解耦：后台读线程持续 read 并写入**采样环形缓冲**，
     消费侧按固定时间节拍从环形缓冲精确取 N 个采样。取不到就补静音。
   *副产品*：静音块进分析引擎后 RMS=0，输出自动归零，天然实现文档 4.3(3) 的静音检测。

2. **用采样级环形缓冲，而非块队列**
   若按「块」排队，读写两侧的块边界会漂移，导致帧内容错位。
   环形缓冲按采样计数，`read_frame()` 永远拿到时间连续的恰好 N 点。

3. **启动预热**
   首次打开流时驱动内部可能有历史积压；启动后丢弃前 warmup_ms 毫秒数据，
   避免把启动瞬态当成真实音频（实测：不预热时首帧输出可达 220/255）。

4. **突发保护**
   环形缓冲满时丢最旧采样（低延迟优先），计入 drop_events。只要占比 <1% 即健康。

用法:
    cap = LoopbackCapture(frame_ms=20)
    cap.start()                       # 启动后台读线程
    while running:
        frame = cap.read_frame()      # 定长 (N, 2) float32，按节拍阻塞
    cap.stop()
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import pyaudiowpatch as pa
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要 PyAudioWPatch：pip install PyAudioWPatch") from exc

DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2


@dataclass
class AudioFormat:
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    device_index: Optional[int] = None
    device_name: str = ""


@dataclass
class CaptureStats:
    """捕获层运行统计（文档 6.4 音频流断流/断流检测）。

    drop_events: 环形缓冲满而丢最旧的采样数。音频突发（游戏启动、场景切换）时
    属预期保护行为，占比 <1% 即健康，不是错误。
    """
    frames_emitted: int = 0        # 已产出帧数
    real_frames: int = 0           # 含真实音频的帧数
    silence_filled: int = 0        # 断流补静音的帧数
    dropped_samples: int = 0       # 突发保护丢弃的采样数
    read_errors: int = 0           # 驱动读取异常
    warmup_frames: int = 0         # 预热期丢弃的帧数
    last_peak: float = 0.0
    started_at: float = 0.0

    @property
    def underrun_ratio(self) -> float:
        return self.silence_filled / max(1, self.frames_emitted)

    @property
    def drop_ratio(self) -> float:
        produced = self.real_frames + self.silence_filled
        return self.dropped_samples / max(1, self.dropped_samples + produced * 960)

    def reset(self) -> None:
        for f in self.__dataclass_fields__:
            if f.endswith("_at"):
                continue
            setattr(self, f, 0 if isinstance(getattr(self, f), int) else 0.0)


def list_loopback_devices() -> list[dict]:
    """列出所有可用的 Loopback 设备（供 CLI `devices` 与 UI 使用）。"""
    p = pa.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
        default_out = wasapi.get("defaultOutputDevice", -1)
        return [
            {"index": d["index"], "name": d["name"],
             "is_default": d["index"] == default_out,
             "sample_rate": int(d["defaultSampleRate"]),
             "channels": d["maxInputChannels"]}
            for d in p.get_loopback_device_info_generator()
        ]
    finally:
        p.terminate()


def find_default_loopback() -> dict:
    """找与「默认播放设备」配对的 loopback 设备。"""
    p = pa.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
        default_out = wasapi.get("defaultOutputDevice", -1)
        target = p.get_device_info_by_index(default_out)["name"] + " [Loopback]"
        for d in p.get_loopback_device_info_generator():
            if d["name"] == target:
                return d
        for d in p.get_loopback_device_info_generator():  # 兜底
            return d
        raise RuntimeError("系统中没有可用的 Loopback 设备")
    finally:
        p.terminate()


def resolve_loopback(device_hint: Optional[str] = None) -> dict:
    """按名字子串匹配 loopback；hint 为 None 时使用默认播放设备。"""
    if not device_hint:
        return find_default_loopback()
    p = pa.PyAudio()
    try:
        for d in p.get_loopback_device_info_generator():
            if device_hint.lower() in d["name"].lower():
                return d
        raise RuntimeError(f"未找到匹配 '{device_hint}' 的 Loopback 设备")
    finally:
        p.terminate()


class _RingBuffer:
    """线程安全的采样级环形缓冲（float32，多声道）。写满丢弃最旧采样。

    实现要点：永远维护「最旧采样位置」= (_w - _size) mod cap。
    溢出丢弃时同时前移 _w 与减少 _size，容量严格受 cap 约束。
    """

    def __init__(self, capacity_samples: int, channels: int):
        self.cap = max(256, int(capacity_samples))
        self.ch = channels
        self._buf = np.zeros((self.cap, channels), dtype=np.float32)
        self._w = 0          # 下一个写入位置
        self._size = 0       # 当前有效采样数（0 <= size <= cap）
        self._lock = threading.Lock()
        self.dropped = 0

    def write(self, data: np.ndarray) -> None:
        n = data.shape[0]
        if n == 0:
            return
        with self._lock:
            if n >= self.cap:
                # 单次写入超过整个缓冲：只保留最后 cap 个采样
                self.dropped += n - self.cap
                self._buf[:] = data[-self.cap:]
                self._w = 0
                self._size = self.cap
                return
            # 需要腾出的空间
            overflow = self._size + n - self.cap
            if overflow > 0:
                self.dropped += overflow
                self._size -= overflow        # 丢最旧：直接缩小有效窗口
                # _w 不动；最旧位置由 (_w - _size) 自然前移
            end = self._w + n
            if end <= self.cap:
                self._buf[self._w:end] = data
            else:
                first = self.cap - self._w
                self._buf[self._w:] = data[:first]
                self._buf[: n - first] = data[first:]
            self._w = end % self.cap
            self._size += n

    def read(self, n: int) -> tuple[np.ndarray, int]:
        """取最多 n 个采样（从最旧开始），返回 (数据, 实际数量)。"""
        with self._lock:
            take = min(n, self._size)
            if take <= 0:
                return np.zeros((0, self.ch), dtype=np.float32), 0
            start = (self._w - self._size) % self.cap
            end = start + take
            if end <= self.cap:
                out = self._buf[start:end].copy()
            else:
                first = self.cap - start
                out = np.empty((take, self.ch), dtype=np.float32)
                out[:first] = self._buf[start:]
                out[first:] = self._buf[: take - first]
            self._size -= take
            return out, take

    @property
    def available(self) -> int:
        with self._lock:
            return self._size


class LoopbackCapture:
    """WASAPI Loopback 捕获器：后台线程 → 环形缓冲 → 定长帧消费。

    read_frame() 保证每 frame_ms 返回恰好 (frame_samples, 2) float32；
    音频断流时返回全零帧，绝不无限阻塞。
    """

    def __init__(
        self,
        frame_ms: int = 20,
        device_hint: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        queue_seconds: float = 0.3,
        target_channels: int = 2,
        warmup_ms: float = 200.0,
    ):
        self.frame_ms = frame_ms
        self.device_hint = device_hint
        self.target_sr = sample_rate
        self.target_ch = target_channels
        self.queue_seconds = queue_seconds
        self.warmup_ms = warmup_ms
        self._ring: Optional[_RingBuffer] = None
        self._stop = threading.Event()
        self._reader: Optional[threading.Thread] = None
        self._pa = None
        self._stream = None
        self.fmt = AudioFormat()
        self.stats = CaptureStats()
        self._next_deadline = 0.0
        self._pending = np.zeros((0, target_channels), dtype=np.float32)
        self._warmup_frames_left = 0
        self._backlogged = False
        self.catchup_frames = 0   # 追赶模式触发帧数（用于诊断节拍健康度）

    # ---------- 生命周期 ----------

    def start(self) -> "LoopbackCapture":
        dev = resolve_loopback(self.device_hint)
        self.fmt = AudioFormat(
            sample_rate=int(dev["defaultSampleRate"]),
            channels=int(dev["maxInputChannels"]),
            device_index=dev["index"],
            device_name=dev["name"],
        )
        # 环形缓冲只需容纳很小的突发余量；过大反而累积陈旧数据。
        self._ring = _RingBuffer(
            capacity_samples=int(min(self.queue_seconds,
                                     max(0.08, self.frame_ms / 1000.0 * 4))
                                 * self.fmt.sample_rate),
            channels=self.fmt.channels,
        )
        self._pa = pa.PyAudio()
        self._stream = self._pa.open(
            format=pa.paInt16,
            channels=self.fmt.channels,
            rate=self.fmt.sample_rate,
            input=True,
            input_device_index=self.fmt.device_index,
            frames_per_buffer=self._block_frames(),
        )
        self._warmup_frames_left = max(1, int(self.warmup_ms / self.frame_ms))
        self.stats.started_at = time.time()
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop,
                                        name="audio-reader", daemon=True)
        self._reader.start()

        # 启动稳定：等驱动把初始积压吐完，再把缓冲清零。
        # 实测：不这样做，启动瞬间会一次性拿到 ~2.5s 的历史静音数据，
        # 既污染统计又让开头几帧误判为"有声音"。
        self._settle_stream()
        self._next_deadline = time.perf_counter()
        return self

    def _settle_stream(self) -> None:
        """等待驱动初始积压排出并清空缓冲（阻塞，最多 ~1.2s）。"""
        deadline = time.perf_counter() + 1.2
        last = -1
        stable = 0
        while time.perf_counter() < deadline and not self._stop.is_set():
            time.sleep(0.05)
            if self._ring is None:
                return
            self._ring.read(self._ring.available)   # 边等边清
            cur = self._ring.available
            if cur == last:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
            last = cur
        if self._ring is not None:
            self._ring.read(self._ring.available)
        # 读线程与清空存在竞争：等一小段让稳态建立，再清空并归零统计，
        # 使 dropped 只反映运行期真实突发（启动积压不计入，避免误报）。
        self._warmup_frames_left = 2
        time.sleep(self.frame_ms * 3 / 1000.0)
        if self._ring is not None:
            self._ring.read(self._ring.available)
            self._ring.dropped = 0

    def stop(self) -> None:
        self._stop.set()
        if self._reader is not None:
            self._reader.join(timeout=1.5)
            self._reader = None
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
        finally:
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ---------- 内部 ----------

    def _block_frames(self) -> int:
        """驱动每次 read 的块大小（与帧长一致，减少搬运次数）。"""
        return max(256, int(self.fmt.sample_rate * self.frame_ms / 1000))

    def _read_loop(self) -> None:
        block = self._block_frames()
        while not self._stop.is_set():
            try:
                raw = self._stream.read(block, exception_on_overflow=False)
            except Exception:
                self.stats.read_errors += 1
                time.sleep(0.01)
                continue
            a = np.frombuffer(raw, dtype=np.int16)
            if self.fmt.channels and a.size % self.fmt.channels == 0:
                a = a.reshape(-1, self.fmt.channels)
            if self._ring is not None and a.size:
                self._ring.write(a.astype(np.float32) / 32768.0)

    # ---------- 消费侧 ----------

    def read_frame(self) -> np.ndarray:
        """阻塞到下一拍，返回恰好 (frame_samples, target_ch) float32。

        节拍策略（针对 WASAPI 的实际行为做了适配）：
          - 以单调时钟推进 20ms 节拍，保证分析帧的时间戳均匀；
          - 但若环形缓冲积压明显（> 2 帧），说明读线程产出快于消费，
            此时**不再 sleep**，立刻消费以追赶，避免持续积压导致丢数据。
            积压是启动瞬间的一次性现象，追平后自动恢复常规节拍。
        """
        block_frames = max(1, int(self.fmt.sample_rate * self.frame_ms / 1000))

        # 预热期：丢弃缓冲里的历史数据，输出静音
        if self._warmup_frames_left > 0:
            self._warmup_frames_left -= 1
            if self._ring is not None:
                self._ring.read(self._ring.available)
                self._ring.dropped = 0   # 预热期的丢弃不计入统计
            self.stats.warmup_frames += 1
            # 预热帧不计入 frames_emitted / silence_filled，避免污染断流率
            if self._warmup_frames_left == 0:
                self._next_deadline = time.perf_counter()
                self.stats.frames_emitted = 0
                self.stats.silence_filled = 0
                self.stats.real_frames = 0
            time.sleep(self.frame_ms / 1000.0)
            return np.zeros((block_frames, self.target_ch), dtype=np.float32)

        pending = self._ring.available if self._ring is not None else 0
        backlog = pending > block_frames * 2

        if not backlog:
            self._next_deadline += self.frame_ms / 1000.0
            sleep_for = self._next_deadline - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                self._next_deadline = time.perf_counter()
        else:
            # 追赶模式：不睡，立即消费；并把节拍基准拉回当前时刻
            self._next_deadline = time.perf_counter()
            self.catchup_frames += 1

        got = 0
        data = np.zeros((0, self.fmt.channels), dtype=np.float32)
        if self._ring is not None:
            data, got = self._ring.read(block_frames)

        frame = np.zeros((block_frames, self.target_ch), dtype=np.float32)
        n = min(block_frames, data.shape[0])
        if n:
            frame[:n] = self._to_target_channels(data[:n])

        if got == 0:
            self.stats.silence_filled += 1
        else:
            self.stats.real_frames += 1
            self.stats.last_peak = float(np.abs(frame).max())
        self.stats.frames_emitted += 1
        self._backlogged = backlog
        return frame

    def _to_target_channels(self, data: np.ndarray) -> np.ndarray:
        ch = data.shape[1] if data.ndim > 1 else 1
        if ch == self.target_ch:
            return data
        if ch == 1:
            return np.repeat(data, self.target_ch, axis=1)
        if ch > self.target_ch:
            return data[:, : self.target_ch]
        reps = -(-self.target_ch // ch)
        return np.tile(data, (1, reps))[:, : self.target_ch]

    # ---------- 统计同步 ----------

    @property
    def dropped_samples(self) -> int:
        return self._ring.dropped if self._ring else 0
