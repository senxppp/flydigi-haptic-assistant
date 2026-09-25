"""
环形缓冲单元测试
================

覆盖采样级环形缓冲的容量约束、丢弃语义、环绕读写与内容完整性。
这是音频拦截层的核心数据结构——一旦它的容量或时序出错，会导致音频帧
内容错位（隐蔽但严重），因此单独测试。

直接运行: python tests/test_ringbuffer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.audio.loopback import _RingBuffer  # noqa: E402

CAP = 300


def t_capacity_bound():
    """有效采样数永不超过容量；溢出丢弃计数正确。"""
    rb = _RingBuffer(CAP, 2)
    rb.write(np.zeros((CAP - 20, 2)))
    rb.write(np.zeros((50, 2)))
    assert rb.available == CAP, f"容量越界 avail={rb.available}"
    assert rb.dropped == 30, f"丢弃计数错误 dropped={rb.dropped}"
    return True


def t_wraparound_content():
    """环绕写入 + 溢出后，内容应为"保留最新、丢弃最旧"。"""
    rb = _RingBuffer(CAP, 1)
    rb.write(np.arange(200, dtype=np.float32).reshape(-1, 1))
    rb.read(50)                                     # 剩 50..199
    rb.write(np.arange(200, 400, dtype=np.float32).reshape(-1, 1))
    out, n = rb.read(CAP)
    exp = np.arange(100, 400, dtype=np.float32)     # 最旧 50 个(50..99)被丢
    assert n == CAP, f"读取数量 {n}"
    assert np.allclose(out[:, 0], exp), f"内容错位 首尾={out[0,0]},{out[-1,0]}"
    return True


def t_fragment_continuity():
    """分片写入的时序必须连续（模拟 960 采样分块）。"""
    rb = _RingBuffer(3000, 2)
    for k in range(6):
        rb.write(np.full((500, 2), k, dtype=np.float32))
    out, n = rb.read(3000)
    assert n == 3000, f"读取数量 {n}"
    assert np.allclose(out[:, 0], np.repeat(np.arange(6), 500)), "分片时序不连续"
    return True


def t_overflow_keeps_latest():
    """溢出时保留最新数据。"""
    rb = _RingBuffer(CAP, 1)
    rb.write(np.arange(CAP + 50, dtype=np.float32).reshape(-1, 1))
    out, n = rb.read(CAP)
    assert n == CAP and np.allclose(out[:, 0], np.arange(50, CAP + 50))
    return True


def t_consume_frees_space():
    """消费后应释放容量，可继续写入且不误计丢弃。"""
    rb = _RingBuffer(CAP, 1)
    rb.write(np.arange(CAP, dtype=np.float32).reshape(-1, 1))
    assert rb.available == CAP
    rb.read(100)
    assert rb.available == CAP - 100
    rb.write(np.arange(1000, 1100, dtype=np.float32).reshape(-1, 1))
    assert rb.available == CAP, f"释放后未写满 avail={rb.available}"
    assert rb.dropped == 0, f"误计丢弃 dropped={rb.dropped}"
    return True


def t_multichannel_independent():
    """多声道数据独立无串扰。"""
    rb = _RingBuffer(CAP, 2)
    d = np.zeros((10, 2), dtype=np.float32)
    d[:, 0] = 1.0
    d[:, 1] = 2.0
    rb.write(d)
    out, n = rb.read(10)
    assert np.allclose(out[:, 0], 1.0) and np.allclose(out[:, 1], 2.0), "声道串扰"
    return True


def t_empty_read():
    """空缓冲读取应返回空且不报错。"""
    rb = _RingBuffer(CAP, 2)
    out, n = rb.read(100)
    assert n == 0 and out.shape[0] == 0
    return True


TESTS = [
    ("容量约束与丢弃计数", t_capacity_bound),
    ("环绕+溢出内容正确", t_wraparound_content),
    ("分片写入时序连续", t_fragment_continuity),
    ("溢出保留最新", t_overflow_keeps_latest),
    ("消费释放容量", t_consume_frees_space),
    ("多声道独立", t_multichannel_independent),
    ("空缓冲读取", t_empty_read),
]


def main() -> int:
    print("=" * 60)
    print("  环形缓冲单元测试")
    print("=" * 60)
    failed = 0
    for name, fn in TESTS:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {name}\n      {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}\n      {type(e).__name__}: {e}")
    print("-" * 60)
    print(f"  结果: {len(TESTS)-failed}/{len(TESTS)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
