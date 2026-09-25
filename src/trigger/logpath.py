"""飞智服务日志路径解析 —— 自动匹配当天日期。
================================================

背景
----
飞智空间站每天生成一个新日志：`service_log_YYYYMMDD.txt`。
写死日期会导致跨天后扳机联动失效。

方案
----
`log_path` 支持两种写法：
  1. 含日期占位符：`D:/Flydigi Space Station/Logs/service_log_{date}.txt`
     → `{date}` 会被替换成当天 `YYYYMMDD`
  2. 写死路径：`D:/.../service_log_20260925.txt`
     → 直接使用（保持向后兼容）

另外提供 `auto` 模式（见 `resolve_log_path(..., prefer_dated=True)`）：
  优先用当天日期的文件；若不存在，**回退到目录里最新的 service_log_*.txt**，
  并给出警告 —— 这样即使飞智某天没生成新文件也不会直接失效。

用法
----
    from src.trigger.logpath import resolve_log_path

    p = resolve_log_path("D:/Flydigi Space Station/Logs/service_log_{date}.txt")
    # → Path('D:/Flydigi Space Station/Logs/service_log_20260925.txt')
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
from pathlib import Path

log = logging.getLogger("trigger")

# 匹配 service_log_YYYYMMDD.txt（也容忍 service_log_YYYY-MM-DD.txt）
_LOG_RE = re.compile(r"service_log[_-]?(\d{4})[-_]?(\d{2})[-_]?(\d{2})\.txt$",
                     re.IGNORECASE)


def today_str() -> str:
    """返回当天日期字符串 YYYYMMDD。"""
    return _dt.date.today().strftime("%Y%m%d")


def expand_date(path_str: str, date_str: str | None = None) -> str:
    """把路径里的日期占位符替换成实际日期。

    支持的占位符（任意一个都可以）：
        {date}      → 20260925
        {date_dash} → 2026-09-25
        {date_sep}  → 2026_09_25
    """
    d = date_str or today_str()
    if len(d) == 8 and d.isdigit():
        dash = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        sep = f"{d[:4]}_{d[4:6]}_{d[6:]}"
    else:
        dash = sep = d
    return (path_str.replace("{date}", d)
            .replace("{date_dash}", dash)
            .replace("{date_sep}", sep))


def _list_dated_logs(directory: Path) -> list[tuple[str, Path]]:
    """列出目录下所有 service_log_*.txt，返回 [(日期串, 路径)]，按日期降序。"""
    out: list[tuple[str, Path]] = []
    if not directory.is_dir():
        return out
    for f in directory.iterdir():
        if not f.is_file():
            continue
        m = _LOG_RE.search(f.name)
        if m:
            out.append((m.group(1) + m.group(2) + m.group(3), f))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def resolve_log_path(path_str: str, *, prefer_dated: bool = True) -> Path:
    """解析日志路径，自动处理日期。

    参数:
        path_str:      配置里的路径，可含 {date} 等占位符
        prefer_dated:  为 True 时，若目标不存在则回退到目录里最新的日志

    返回:
        实际可用的 Path（可能不存在 —— 调用方需自行处理）
    """
    expanded = expand_date(path_str)
    p = Path(expanded)

    if p.exists():
        return p

    # 目标不存在 → 尝试回退
    if prefer_dated and p.parent.is_dir():
        candidates = _list_dated_logs(p.parent)
        if candidates:
            newest_date, newest_path = candidates[0]
            log.warning("当天日志不存在（%s），回退到最近一份：%s",
                        p.name, newest_path.name)
            if newest_date != today_str():
                log.warning("注意：回退日志的日期是 %s，可能不含今天的操作",
                            newest_date)
            return newest_path

    return p


def describe(path_str: str) -> str:
    """给 GUI/日志用的一句描述。"""
    return f"{path_str} → {resolve_log_path(path_str)}"
