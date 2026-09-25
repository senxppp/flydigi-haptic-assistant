"""诊断 fcs.sock 管道的可连接性，并尝试多种连接方式。

Windows 命名管道实例占满(err=231)时，正常的 CreateFile 会失败。
但可以：
  1. 用 WaitNamedPipe 等待实例空闲
  2. 用 FILE_FLAG_OVERLAPPED 异步打开
  3. 检查是否真的占满，还是权限/路径问题
"""

import ctypes
import ctypes.wintypes as wt
import glob
import time

k = ctypes.WinDLL("kernel32", use_last_error=True)

PIPE_NAME = r"\\.\pipe\fcs.sock"   # 注意：python 原始字符串
PIPE_ACCESS = 0x80000000 | 0x40000000   # GENERIC_READ | GENERIC_WRITE
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
NMPWAIT_WAIT_FOREVER = 0xFFFFFFFF


def try_open(tag, access, flags=0, share=0, sec=None):
    h = k.CreateFileW(PIPE_NAME, access, share, sec, OPEN_EXISTING, flags, None)
    if h in (-1, 0xFFFFFFFFFFFFFFFF):
        e = ctypes.get_last_error()
        print(f"  [{tag}] 失败 err={e}")
        return None
    print(f"  [{tag}] ★ 成功 handle={h}")
    return h


def main():
    print("管道是否存在:", bool(glob.glob(r"\\\\.\\pipe\\fcs.sock")))
    print()

    # 列出同名管道（不同实例）
    print("=== 枚举该管道名 ===")
    k32 = ctypes.WinDLL("kernel32")
    buf = ctypes.create_string_buffer(65536)
    # 用 FindFirstFile 枚举
    fd = wt.WIN32_FIND_DATAW()
    hfind = k32.FindFirstFileW(r"\\\\.\\pipe\\*", ctypes.byref(fd))
    cnt = 0
    if hfind not in (-1, 0xFFFFFFFFFFFFFFFF):
        while True:
            nm = fd.cFileName
            if "fcs" in nm.lower():
                print("   实例:", nm)
                cnt += 1
            if not k32.FindNextFileW(hfind, ctypes.byref(fd)):
                break
        k32.FindClose(hfind)
    print(f"   含 'fcs' 的管道数: {cnt}")
    print()

    print("=== 尝试多种打开方式 ===")
    try_open("RW, share=0", PIPE_ACCESS)
    try_open("RW, share=3", PIPE_ACCESS, share=3)
    try_open("RW, OVERLAPPED", PIPE_ACCESS, flags=FILE_FLAG_OVERLAPPED)
    try_open("RW, 0-byte access", 0)
    try_open("READ, share=3", 0x80000000, share=3)

    print()
    print("=== 尝试 WaitNamedPipe(5s) 后连接 ===")
    r = k.WaitNamedPipeW(PIPE_NAME, 5000)
    print("  WaitNamedPipe:", "OK" if r else f"fail err={ctypes.get_last_error()}")
    if r:
        h = try_open("RW after wait", PIPE_ACCESS, share=3)
        if h:
            k.CloseHandle(h)


if __name__ == "__main__":
    main()
