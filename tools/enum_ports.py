"""枚举服务的 UDP 监听端口 + 所有端口的完整信息。

之前只查了 TCP，AdapterTriggerService 可能是 UDP。
"""

import ctypes
import ctypes.wintypes as wt

iphlpapi = ctypes.WinDLL("iphlpapi")


class ROW_TCP(ctypes.Structure):
    _fields_ = [("dwState", wt.DWORD), ("dwLocalAddr", wt.DWORD),
                ("dwLocalPort", wt.DWORD), ("dwRemoteAddr", wt.DWORD),
                ("dwRemotePort", wt.DWORD), ("dwOwningPid", wt.DWORD)]


class ROW_UDP(ctypes.Structure):
    _fields_ = [("dwLocalAddr", wt.DWORD), ("dwLocalPort", wt.DWORD),
                ("dwOwningPid", wt.DWORD)]


def tcp4():
    TCP_TABLE_OWNER_PID_ALL = 5
    size = wt.DWORD(0)
    iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, TCP_TABLE_OWNER_PID_ALL, 0)
    buf = ctypes.create_string_buffer(size.value)
    if iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, TCP_TABLE_OWNER_PID_ALL, 0) != 0:
        return []
    n = ctypes.cast(buf, ctypes.POINTER(wt.DWORD)).contents.value
    rows = ctypes.cast(ctypes.addressof(buf) + 4, ctypes.POINTER(ROW_TCP))
    out = []
    for i in range(n):
        r = rows[i]
        port = ((r.dwLocalPort & 0xFF) << 8) | ((r.dwLocalPort >> 8) & 0xFF)
        addr = ".".join(str((r.dwLocalAddr >> s) & 0xFF) for s in (0, 8, 16, 24))
        out.append(("TCP", addr, port, r.dwOwningPid, r.dwState))
    return out


def udp4():
    UDP_TABLE_OWNER_PID = 1
    size = wt.DWORD(0)
    iphlpapi.GetExtendedUdpTable(None, ctypes.byref(size), False, 2, UDP_TABLE_OWNER_PID, 0)
    buf = ctypes.create_string_buffer(size.value)
    if iphlpapi.GetExtendedUdpTable(buf, ctypes.byref(size), False, 2, UDP_TABLE_OWNER_PID, 0) != 0:
        return []
    n = ctypes.cast(buf, ctypes.POINTER(wt.DWORD)).contents.value
    rows = ctypes.cast(ctypes.addressof(buf) + 4, ctypes.POINTER(ROW_UDP))
    out = []
    for i in range(n):
        r = rows[i]
        port = ((r.dwLocalPort & 0xFF) << 8) | ((r.dwLocalPort >> 8) & 0xFF)
        addr = ".".join(str((r.dwLocalAddr >> s) & 0xFF) for s in (0, 8, 16, 24))
        out.append(("UDP", addr, port, r.dwOwningPid, 0))
    return out


allrows = tcp4() + udp4()
# 飞智服务 PID
TARGET_PIDS = {}
import subprocess
k = ctypes.WinDLL("kernel32")
TH32CS_SNAPPROCESS = 0x2


class PE(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_char * 260)]


snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
pe = PE(); pe.dwSize = ctypes.sizeof(PE)
ok = k.Process32First(snap, ctypes.byref(pe))
while ok:
    nm = pe.szExeFile.decode(errors="replace")
    if "SpaceStation" in nm or "Flydigi" in nm or "Endfield" in nm:
        TARGET_PIDS[pe.th32ProcessID] = nm
    ok = k.Process32Next(snap, ctypes.byref(pe))
k.CloseHandle(snap)

print("目标进程:", TARGET_PIDS)
print()
print("=== 目标进程占用的端口（全部状态） ===")
for proto, addr, port, pid, state in allrows:
    if pid in TARGET_PIDS:
        st = {1: "ESTAB", 2: "LISTEN", 3: "SYN_SENT", 4: "SYN_RECV", 5: "FIN_WAIT1",
              6: "FIN_WAIT2", 7: "TIME_WAIT", 8: "CLOSE", 9: "CLOSE_WAIT",
              10: "LAST_ACK", 11: "LISTEN", 12: "CLOSING"}.get(state, str(state))
        print(f"  {proto} {addr}:{port:<6} pid={pid} ({TARGET_PIDS[pid]}) {st}")
