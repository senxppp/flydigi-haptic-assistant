"""
运行全部测试
============

用法: python tests/run_all.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def main() -> int:
    suites = ["test_algorithm.py", "test_ringbuffer.py"]
    rc = 0
    for s in suites:
        p = _HERE / s
        print(f"\n{'#' * 66}\n#  {s}\n{'#' * 66}")
        r = subprocess.run([sys.executable, str(p)])
        rc = rc or r.returncode
    print(f"\n{'=' * 66}")
    print("全部测试完成" + ("" if rc == 0 else "  —— 存在失败"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
