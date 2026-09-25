"""用 Winsock2 (AF_UNIX = 1) 连接 fcs.sock。

Windows 10 1803+ 支持 AF_UNIX，Python 官方 win 版没编译进去，
所以直接用 ctypes 调 ws2_32.dll。
"""

import ctypes
import ctypes.wintypes as wt

AF_UNIX = 1
SOCK_STREAM = 1

ws2 = ctypes.WinDLL("ws2_32")

# 初始化 Winsock
class WSAData(ctypes.Structure):
    _fields_ = [("wVersion", wt.WORD), ("wHighVersion", wt.WORD),
                ("szDescription", ctypes.c_char * 257),
                ("szSystemStatus", ctypes.c_char * 129),
                ("iMaxSockets", ctypes.c_ushort), ("iMaxUdpDg", ctypes.c_ushort),
                ("lpVendorInfo", ctypes.c_char_p)]

wsa = WSAData()
ret = ws2.WSAStartup(0x0202, ctypes.byref(wsa))
print("WSAStartup:", ret)
print("版本:", wsa.wVersion, "描述:", wsa.szDescription.decode(errors="replace"))


class SOCKADDR_UN(ctypes.Structure):
    _fields_ = [("sun_family", ctypes.c_ushort),
                ("sun_path", ctypes.c_char * 108)]


def try_connect(path: str):
    s = ws2.socket(AF_UNIX, SOCK_STREAM, 0)
    if s == -1:
        return f"socket() 失败 err={ws2.WSAGetLastError()}"
    try:
        addr = SOCKADDR_UN()
        addr.sun_family = AF_UNIX
        b = path.encode()
        if len(b) >= 108:
            return f"路径太长 {len(b)}"
        ctypes.memmove(addr.sun_path, b, len(b))
        r = ws2.connect(s, ctypes.byref(addr), ctypes.sizeof(addr))
        if r == 0:
            return "OK"
        return f"connect 失败 err={ws2.WSAGetLastError()}"
    finally:
        ws2.closesocket(s)


paths = [r"\\.\pipe\fcs.sock", r"\\.\pipe\fcs.sock\0",
         "\\\\.\\pipe\\fcs.sock", r"\\.\pipe\fcs.sock"]
for p in paths:
    print(f"  {p!r} -> {try_connect(p)}")

ws2.WSACleanup()
