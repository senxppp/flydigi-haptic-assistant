"""
Flydigi Dragonfly5 Audio-to-Haptic Middleware — CLI 入口
========================================================

子命令:
    run        实时运行中间层（默认，Ctrl+C 退出）
    devices    列出可用 Loopback 设备
    bench      离线算法基准测试（无需手柄/音频设备）
    selftest   合成音频驱动全链路自测（会真震动，需手柄在线）
    loadtest   100Hz 连发压测（文档 9.6 问题4）
    test-out   直接测试震动输出层（左/右/双脉冲）

用法示例:
    python -m src.main run
    python -m src.main run --preset racing --gain 0.8
    python -m src.main loadtest --duration 600
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

# 让 `python -m src.main` 与 `python src/main.py` 都能工作
_PKG_ROOT = Path(__file__).resolve().parents[1]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

import numpy as np  # noqa: E402

from src.analysis.features import FeatureExtractor  # noqa: E402
from src.core.config import Config  # noqa: E402
from src.mapping.mapper import HapticMapper  # noqa: E402
from src.mapping.presets import PRESETS  # noqa: E402


# ---------------------------------------------------------------- 日志

def setup_logging(level: str = "INFO", to_file: bool = True,
                  log_dir: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if to_file:
        log_dir = log_dir or (_PKG_ROOT / "logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        fp = log_dir / f"middleware_{time.strftime('%Y%m%d')}.log"
        handlers.append(logging.FileHandler(fp, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers, force=True,
    )


# ---------------------------------------------------------------- 实时显示

class LiveDisplay:
    """终端实时强度条 + 状态行（文档 6.3(2) 震动输出实时监测）。"""

    BAR_W = 24

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._last_render = 0.0

    @staticmethod
    def _bar(v: float, width: int) -> str:
        n = int(max(0.0, min(1.0, v)) * width)
        return "█" * n + "·" * (width - n)

    def render(self, s: dict, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.perf_counter()
        if not force and now - self._last_render < 0.1:
            return
        self._last_render = now
        dl = s["drive_l"] / 255.0
        dr = s["drive_r"] / 255.0
        dev = "✓" if s["connected"] else "✗"
        tg = s.get("trigger_drive", 0)
        if s.get("trigger_active"):
            tg_txt = f"动作{tg:3d}▶"
        elif s.get("trigger_events"):
            tg_txt = f"待机 {s['trigger_events']}次"
        else:
            tg_txt = "待机"
        line = (
            f"\rL {self._bar(dl, self.BAR_W)} {s['drive_l']:3d} | "
            f"R {self._bar(dr, self.BAR_W)} {s['drive_r']:3d} | "
            f"RMS {s['rms_l']:.3f}/{s['rms_r']:.3f} "
            f"AGC×{s['agc_gain']:.2f} | 计算 {s['process_ms']:.2f}ms "
            f"(峰 {s['max_process_ms']:.1f}) | 断流 {s['underrun']*100:.0f}% "
            f"丢弃 {s['dropped']} | 手柄{dev} {s['send_rate']:.0f}Hz "
            f"| 扳机 {tg_txt}"
        )
        sys.stdout.write(line[:220].ljust(180))
        sys.stdout.flush()


# ---------------------------------------------------------------- 子命令

def cmd_devices(args: argparse.Namespace) -> int:
    from src.audio.loopback import list_loopback_devices
    devs = list_loopback_devices()
    if not devs:
        print("未找到任何 Loopback 设备。请确认系统有可用的播放设备。")
        return 1
    print(f"{'idx':>4}  {'默认':^4}  {'采样率':>7}  {'声道':>4}  设备名")
    for d in devs:
        mark = "  ✔ " if d["is_default"] else "    "
        print(f"{d['index']:>4}  {mark}  {d['sample_rate']:>7}  "
              f"{d['channels']:>4}  {d['name']}")
    print("\n提示：configs/config.json 的 audio.device_hint 填设备名子串即可指定；"
          "\n      留空（null）则自动跟随系统默认播放设备。")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from src.core.pipeline import HapticPipeline

    cfg = Config.load(args.config)
    if args.preset:
        cfg.set_preset(args.preset)
    if args.gain is not None:
        cfg.data["mapping"]["master_gain"] = max(0.0, min(1.0, args.gain))
    if args.device:
        cfg.data["audio"]["device_hint"] = args.device
    if args.send_rate:
        cfg.data["output"]["send_rate_hz"] = args.send_rate
    if args.trigger is not None:
        cfg.data.setdefault("trigger", {})["enabled"] = args.trigger
    if args.trigger_drive is not None:
        cfg.data.setdefault("trigger", {})["drive"] = args.trigger_drive

    log = logging.getLogger("main")
    log.info("预设=%s  %s", cfg.preset, PRESETS[cfg.preset]["label"])

    pipe = HapticPipeline(cfg)
    disp = LiveDisplay(enabled=not args.no_ui)
    stop = threading.Event()

    def _sig(_s, _f):
        stop.set()
    try:
        signal.signal(signal.SIGINT, _sig)
    except (ValueError, OSError):
        pass

    def on_frame(s):
        disp.render(s)
    try:
        pipe.run(on_frame=on_frame, max_seconds=args.duration, stop_event=stop)
    finally:
        if not args.no_ui:
            print()
    return 0


def cmd_test_out(args: argparse.Namespace) -> int:
    from src.output.haptic_out import HapticOutput
    mode = args.mode
    with HapticOutput(send_rate_hz=100, safety_max_drive=255,
                      auto_stop_ms=5000) as out:
        # 直接同步写，便于自测
        seq = {
            "test": [("仅左", (255, 0)), ("仅右", (0, 255)), ("双", (255, 255))],
            "left": [("左全开", (255, 0))],
            "right": [("右全开", (0, 255))],
        }.get(mode, [("双全开", (255, 255))])
        for label, (l, r) in seq:
            print(f"{label} …", flush=True)
            out._raw_write(l, r)
            time.sleep(1.2)
            out._raw_write(0, 0)
            time.sleep(0.8)
    print("完成")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """离线算法基准：合成 20ms 帧跑分析+映射，统计耗时与映射曲线。

    注意：每个场景都**连续喂多帧并取稳态结果**。单帧从零状态启动时，
    滤波器会有一段瞬态振铃，直接测单帧会得到误导性的虚高数值
    （实测：2kHz 单帧 RMS 0.126，连续稳态仅 0.001）。
    """
    cfg = Config.load(args.config)
    if args.preset:
        cfg.set_preset(args.preset)
    ana = cfg.build_analysis_config()
    env = cfg.build_envelope_config()
    sr, fm = 48000, 20
    n = sr * fm // 1000
    t = np.arange(n) / sr
    rng = np.random.default_rng(7)

    def steady(sig_fn, frames: int = 25, warm: int = 8):
        """连续喂 frames 帧，返回 warm 之后的 (rms, onset, drive) 均值。"""
        ext = FeatureExtractor(sample_rate=sr, config=ana)
        mapper = HapticMapper(cfg.build_mapping_config(), frame_ms=fm)
        for k in ("L", "R"):
            e = mapper._env[k]
            e.attack_ms = env.get("attack_ms", e.attack_ms)
            e.release_ms = env.get("release_ms", e.release_ms)
        acc = []
        for i in range(frames):
            x = sig_fn(i)
            fr = np.repeat(np.asarray(x)[:, None], 2, axis=1)
            f = ext.extract(fr)
            d = mapper.map_frame(f)
            if i >= warm:
                acc.append((f.left.rms, f.left.onset, d.left, d.right))
        a = np.array(acc)
        return a[:, 0].mean(), a[:, 1].mean(), a[:, 2].mean(), a[:, 3].mean()

    print(f"预设={cfg.preset}  帧长={fm}ms ({n}点)  取稳态均值")
    print(f"{'场景':<16}{'RMS_L':>8}{'onset_L':>9}{'drive_L':>9}{'drive_R':>9}")
    print("-" * 54)

    def tone(amp, freq):
        return lambda i: amp * np.sin(2 * np.pi * freq * (i * fm / 1000 + t))

    cases = [
        ("静音", lambda i: np.zeros(n)),
        ("极弱60Hz .02", tone(0.02, 60)),
        ("弱60Hz .10", tone(0.10, 60)),
        ("中60Hz .30", tone(0.30, 60)),
        ("强60Hz .80", tone(0.80, 60)),
        ("高频2kHz .8", tone(0.80, 2000)),
        ("宽带粉噪", lambda i: 0.30 * rng.standard_normal(n)),
    ]
    for label, fn in cases:
        r, o, dl, dr = steady(fn)
        print(f"{label:<16}{r:>8.3f}{o:>9.3f}{dl:>9.0f}{dr:>9.0f}")

    # 冲击瞬态：静音若干帧后给冲击
    k = np.arange(n)
    hit = lambda i: (0.7 * np.exp(-k / (sr * 0.005)) * np.sin(2 * np.pi * 65 * k / sr)
                     if i >= 10 else np.zeros(n))
    r, o, dl, dr = steady(hit, frames=25, warm=6)
    print(f"{'静音→打击':<16}{r:>8.3f}{o:>9.3f}{dl:>9.0f}{dr:>9.0f}")

    # 性能
    ext = FeatureExtractor(sample_rate=sr, config=ana)
    mp = HapticMapper(cfg.build_mapping_config(), frame_ms=fm)
    frame = np.repeat((0.3 * rng.standard_normal(n))[:, None], 2, axis=1)
    for _ in range(5):
        mp.map_frame(ext.extract(frame))
    t0 = time.perf_counter()
    iters = 100
    for _ in range(iters):
        mp.map_frame(ext.extract(frame))
    per_ms = (time.perf_counter() - t0) / iters * 1000
    print("-" * 54)
    print(f"单帧 分析+映射耗时：{per_ms:.3f} ms（帧预算 {fm} ms，余量 {fm/per_ms:.1f}×）")
    print("\n说明：'高频2kHz' 应接近 0（80Hz 低通生效）；"
          "'静音→打击' 应有明显 onset。")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """合成音频驱动全链路（真震动）。用软件生成的震动音频走完整管线。"""
    from src.core.pipeline import HapticPipeline
    cfg = Config.load(args.config)
    if args.preset:
        cfg.set_preset(args.preset)
    pipe = HapticPipeline(cfg)
    pipe.capture.start()
    pipe.output.open()
    pipe.output.start()

    sr = pipe.capture.fmt.sample_rate
    n = sr * pipe.frame_ms // 1000
    print(f"设备={pipe.capture.fmt.device_name} {sr}Hz；手柄连接="
          f"{pipe.output.stats.connected}")
    if not pipe.output.stats.connected:
        print("⚠ 未检测到手柄，仅验证算法链路（不会震动）")
    print("按 Ctrl+C 停止。将依次播放：低频脉冲 / 左右分离 / 渐强 / 静音\n")

    rng = np.random.default_rng(3)

    def drive_frames(signal_fn, seconds: float, label: str):
        print(f"→ {label}", flush=True)
        total = int(seconds * 1000 / pipe.frame_ms)
        for i in range(total):
            tt = (i * pipe.frame_ms) / 1000.0
            block = np.asarray(signal_fn(tt), dtype=np.float64).reshape(-1)
            st = np.zeros((n, 2))
            m = min(n, block.size)
            if m:
                st[:m, 0] = block[:m]
                st[:m, 1] = block[:m]
            feats = pipe.extractor.extract(st)
            d = pipe.mapper.map_frame(feats)
            pipe.output.set_target(d.left, d.right)
            time.sleep(pipe.frame_ms / 1000.0)
        pipe.output.set_target(0, 0)
        time.sleep(0.4)

    try:
        # 各场景的 signal_fn 必须返回长度 n 的波形（tt 为该帧起始时间）
        def silent(tt):
            return np.zeros(n)

        def pulse50(tt):
            k = np.arange(n)
            return 0.7 * np.sin(2 * np.pi * 50 * (tt + k / sr))

        def alternate(tt):
            k = np.arange(n)
            out = np.zeros(n)
            if int(tt * 2) % 2 == 0:      # 每 0.5s 切换一次左右
                out[:] = 0.7 * np.sin(2 * np.pi * 55 * (tt + k / sr))
            return out

        def ramp(tt):
            k = np.arange(n)
            g = min(1.0, tt / 2.0)
            return g * 0.8 * np.sin(2 * np.pi * 60 * (tt + k / sr))

        drive_frames(silent, 0.6, "静音基线")
        drive_frames(pulse50, 1.5, "低频 50Hz 脉冲")
        drive_frames(alternate, 2.0, "左右交替（应左右握把交替）")
        drive_frames(ramp, 2.0, "渐强 0→满")
        drive_frames(silent, 0.6, "静音收尾")
    except KeyboardInterrupt:
        pass
    finally:
        pipe.output.set_target(0, 0)
        time.sleep(0.2)
        pipe.shutdown()
    print("\n自测完成")
    return 0


def cmd_loadtest(args: argparse.Namespace) -> int:
    """100Hz 连发压测（文档 9.6 问题 4）：验证与空间站并存的长期稳定性。"""
    from src.output.haptic_out import HapticOutput
    dur = args.duration
    rate = args.rate
    print(f"压测：{rate}Hz 连发 {dur}s（约 {int(rate*dur)} 帧），"
          f"观察丢帧/断连/与空间站并存…")
    out = HapticOutput(send_rate_hz=rate, safety_max_drive=200,
                       auto_stop_ms=10000)
    out.open()
    if not out.stats.connected:
        print("✗ 未检测到手柄，压测中止")
        return 1
    out.start()
    t0 = time.time()
    pattern = [(120, 60), (180, 90), (90, 150), (200, 200), (60, 120)]
    i = 0
    try:
        while time.time() - t0 < dur:
            out.set_target(*pattern[i % len(pattern)])
            i += 1
            time.sleep(1.0 / rate)
            if int(time.time() - t0) % 30 == 0 and int(time.time() - t0) > 0:
                pass
    except KeyboardInterrupt:
        print("\n手动中止")
    finally:
        elapsed = time.time() - t0
        out.set_target(0, 0)
        time.sleep(0.3)
        s = out.stats
        out.stop()
    print(f"\n压测结果：运行 {elapsed:.1f}s")
    print(f"  目标帧数 {int(rate*elapsed)}  实际发送 {s.frames_sent}")
    print(f"  写失败 {s.write_failures}  重连 {s.reconnects}  "
          f"最终连接={'在线' if s.connected else '断开'}")
    ok = s.write_failures == 0 and s.reconnects == 0
    print(f"  → {'✓ 通过（无丢帧/无断连）' if ok else '⚠ 出现异常，需排查'}")
    return 0 if ok else 2


# ---------------------------------------------------------------- 入口

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flydigi-haptic", description="八爪鱼5音频转震动中间层",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__,
    )
    p.add_argument("--config", default=None, help="配置文件路径")
    p.add_argument("--log-level", default=None)
    sub = p.add_subparsers(dest="cmd")

    def add_common(sp):
        sp.add_argument("--config", default=None)
        sp.add_argument("--preset", choices=list(PRESETS),
                        help="预设（默认取配置文件）")

    sp = sub.add_parser("run", help="实时运行中间层")
    add_common(sp)
    sp.add_argument("--gain", type=float, help="全局强度 0-1")
    sp.add_argument("--device", help="Loopback 设备名子串")
    sp.add_argument("--send-rate", type=float, help="震动帧发送频率 Hz")
    sp.add_argument("--duration", type=float, help="运行秒数（默认无限）")
    sp.add_argument("--no-ui", action="store_true", help="关闭实时强度条")
    sp.add_argument("--trigger", action=argparse.BooleanOptionalAction,
                    default=None, help="扳机联动握把震动（覆盖配置）")
    sp.add_argument("--trigger-drive", type=int, default=None,
                    help="扳机联动握把力度 0-255")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("devices", help="列出 Loopback 设备")
    sp.set_defaults(func=cmd_devices)

    sp = sub.add_parser("bench", help="离线算法基准")
    add_common(sp)
    sp.set_defaults(func=cmd_bench)

    sp = sub.add_parser("selftest", help="合成音频全链路自测（真震动）")
    add_common(sp)
    sp.set_defaults(func=cmd_selftest)

    sp = sub.add_parser("loadtest", help="100Hz 连发压测")
    sp.add_argument("--duration", type=float, default=600.0)
    sp.add_argument("--rate", type=float, default=100.0)
    sp.set_defaults(func=cmd_loadtest)

    sp = sub.add_parser("test-out", help="直接测试震动输出层")
    sp.add_argument("--mode", choices=["test", "left", "right"], default="test")
    sp.set_defaults(func=cmd_test_out)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        args = parser.parse_args((argv or []) + ["run"])
    setup_logging(args.log_level or "INFO")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
