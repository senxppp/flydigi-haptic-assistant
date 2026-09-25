"""对比分析：冲击段 vs 呼呼声段的完整频带特征。

用法: python tools/analyze_bands.py logs/frames_whoosh.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import numpy as np
    from src.analysis.features import FeatureExtractor
    from src.core.config import Config
    from src.audio.loopback import LoopbackCapture

    # 直接从 WAV 式 CSV 无法重建音频，改为现场采集 + 实时对比
    # 这里改为：重新采集短片段并分窗打印频带
    cfg = Config.load()
    ana = cfg.build_analysis_config()
    sr = cfg.data["audio"]["sample_rate"]
    frame_ms = cfg.data["audio"]["frame_ms"]
    ext = FeatureExtractor(sample_rate=sr, config=ana)
    cap = LoopbackCapture(frame_ms=frame_ms,
                          device_hint=cfg.data["audio"]["device_hint"],
                          sample_rate=sr, queue_seconds=0.5)
    cap.start()
    print("采集 8 秒，打印每帧三频带能量（RMS_L / low / mid / zcr）\n")
    print(f"{'t':>6} {'RMS':>8} {'band_low':>9} {'band_mid':>9} {'zcr':>7}")
    print("-" * 46)
    import time
    t0 = time.time()
    try:
        while time.time() - t0 < 8.0:
            fr = cap.read_frame()
            f = ext.extract(fr)
            c = f.left
            rms = c.rms
            if rms < 0.001 and c.band_mid < 0.001:
                continue
            print(f"{time.time()-t0:>5.1f}s {rms:>8.4f} {c.band_low:>9.4f} "
                  f"{c.band_mid:>9.4f} {c.zcr:>7.3f}")
    except KeyboardInterrupt:
        pass
    finally:
        cap.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
