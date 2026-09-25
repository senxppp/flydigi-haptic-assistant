#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 GitHub REST API 上传整个仓库（绕过被拦截的 git push 协议）。

用法:
    python upload_via_api.py

会读取当前目录下所有文件（排除 .git / .gh_token / .device_code 等），
逐个通过 contents API 创建/更新。
"""

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = "senxppp/flydigi-haptic-assistant"
BRANCH = "main"
API = f"https://api.github.com/repos/{REPO}/contents"

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "build", "dist"}
SKIP_FILES = {".gh_token", ".device_code", ".repo_url", ".gitignore.bak"}

COMMIT_MSG = (
    "feat: Flydigi APEX5 音频转震动中间层 · 震动小助手\n\n"
    "让八爪鱼5在 DS 模式下玩「音频直驱」类游戏也能震动。\n\n"
    "1. 音频转震动：WASAPI Loopback 捕获 + 20ms 帧分析（RMS/瞬态/频带）\n"
    "   + 对数映射曲线 + ADSR 包络 + AGC\n"
    "2. 扳机震动对齐：读取游戏日志，按双信号组奇偶判据判定动作起止\n"
    "   （奇数组=开始，偶数组=停止）\n\n"
    "实测 4 次动作时长 6.43/6.49/6.43/6.44s，与操作精确对齐。\n"
    "19 项单元测试全部通过（算法 12 + 环形缓冲 7）。"
)


def api(method: str, url: str, tok: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, method=method, data=data,
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def collect(root: Path):
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        parts = set(rel.parts)
        if parts & SKIP_DIRS:
            continue
        if rel.name in SKIP_FILES or rel.name.startswith("."):
            continue
        out.append(rel)
    return out


def get_sha(tok: str, rel: str) -> str | None:
    code, d = api("GET", f"{API}/{rel.as_posix()}?ref={BRANCH}", tok)
    if code == 200:
        return d.get("sha")
    return None


def main() -> int:
    root = Path.cwd()
    tok = (root / ".gh_token").read_text(encoding="utf-8").strip()
    files = collect(root)
    print(f"待上传 {len(files)} 个文件\n")

    ok = fail = 0
    for i, rel in enumerate(files, 1):
        content = (root / rel).read_bytes()
        b64 = base64.b64encode(content).decode()
        body = {"message": COMMIT_MSG, "content": b64, "branch": BRANCH}

        sha = get_sha(tok, rel)
        if sha:
            body["sha"] = sha

        code, d = api("PUT", f"{API}/{rel.as_posix()}", tok, body)
        if code in (200, 201):
            ok += 1
            print(f"  [{i:2d}/{len(files)}] OK   {rel}")
        else:
            fail += 1
            msg = d.get("message", d)
            print(f"  [{i:2d}/{len(files)}] FAIL {rel}  -> {code} {msg}")
        time.sleep(0.4)   # 温和限速，避免触发 abuse 检测

    print(f"\n完成: 成功 {ok} / 失败 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
