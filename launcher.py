"""震动小助手 — 图形界面
========================

一个总开关控制全部功能：
  - 音频震动（游戏音效 → 握把震动）
  - 滑索扳机联动（检测到滑索动作 → 握把持续震动）

架构：
    tkinter 主线程（界面）
      └─ 后台线程跑 HapticPipeline.run()
           └─ on_frame 回调 → 投递到界面队列 → 定时刷新

用法:
    python launcher.py            # 开发期直接跑
    震动小助手.exe                # 打包后双击
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

# ---------- 路径处理（兼容 PyInstaller 打包）----------

def _base_dir() -> Path:
    """返回资源根目录。打包后是 exe 所在目录，开发时是项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _resource_dir() -> Path:
    """返回打包内嵌资源目录（PyInstaller 解压到 _MEIPASS）。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _ensure_user_config() -> Path:
    """确保 exe 同级目录下有可编辑的 configs/config.json。

    打包后：若不存在，从内嵌资源复制一份出来（用户可自由修改）。
    开发时：直接用项目里的 configs/。
    """
    user_cfg = _base_dir() / "configs" / "config.json"
    if user_cfg.exists():
        return user_cfg

    bundled = _resource_dir() / "configs" / "config.json"
    if bundled.exists():
        # 尝试写到 exe 旁边（保持可编辑）；若无写权限则退回用内嵌那份
        try:
            user_cfg.parent.mkdir(parents=True, exist_ok=True)
            user_cfg.write_bytes(bundled.read_bytes())
            return user_cfg
        except Exception:
            return bundled
    return user_cfg


BASE = _base_dir()
RES = _resource_dir()
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
if str(RES) not in sys.path:
    sys.path.insert(0, str(RES))

from src.core.config import Config                       # noqa: E402
from src.core.pipeline import HapticPipeline             # noqa: E402

# ---------- 配色 ----------
BG = "#1f2430"
CARD = "#2a3140"
FG = "#e8ecf3"
MUTED = "#8b93a7"
ACCENT = "#3fb950"        # 开启（绿）
DANGER = "#f85149"        # 关闭/错误（红）
WARN = "#d29922"
BAR_BG = "#161b22"


class QueueLogHandler(logging.Handler):
    """把日志转发到界面队列。"""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put(("log", self.format(record)))
        except Exception:
            pass


class VibrationAssistant:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("震动小助手")
        self.root.geometry("620x560")
        self.root.minsize(560, 500)
        self.root.configure(bg=BG)

        self.cfg_path = _ensure_user_config()
        self.config = Config.load(self.cfg_path)
        self.pipeline: HapticPipeline | None = None
        self.pipe_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.running = False

        self.ui_q: queue.Queue = queue.Queue()
        self._setup_logging()

        # 可变参数
        self.var_master = tk.DoubleVar(value=1.0)
        self.var_trigger_drive = tk.IntVar(
            value=int(self.config.data.get("trigger", {}).get("drive", 75)))
        self.var_trigger_on = tk.BooleanVar(
            value=bool(self.config.data.get("trigger", {}).get("enabled", True)))

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._pump)

        self._log("震动小助手已就绪。点击开关启动。")

    # ---------- 日志 ----------

    def _setup_logging(self) -> None:
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        # 清掉已有 handler，避免重复输出
        for h in list(root.handlers):
            root.removeHandler(h)
        h = QueueLogHandler(self.ui_q)
        h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        root.addHandler(h)

    def _log(self, msg: str) -> None:
        self.ui_q.put(("log", msg))

    # ---------- 界面 ----------

    def _build_ui(self) -> None:
        pad = {"padx": 16, "pady": (0, 8)}

        # 标题
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=16, pady=(16, 4))
        tk.Label(head, text="震动小助手", font=("Microsoft YaHei UI", 17, "bold"),
                 bg=BG, fg=FG).pack(side="left")
        self.lbl_state = tk.Label(head, text="● 已停止", font=("Microsoft YaHei UI", 10),
                                  bg=BG, fg=MUTED)
        self.lbl_state.pack(side="right")

        # 总开关
        sw = tk.Frame(self.root, bg=CARD, highlightthickness=0)
        sw.pack(fill="x", padx=16, pady=(8, 10), ipady=6)
        self.btn_power = tk.Button(
            sw, text="启 动", font=("Microsoft YaHei UI", 15, "bold"),
            bg="#2d7d46", fg="white", activebackground="#3fb950",
            activeforeground="white", relief="flat", bd=0, cursor="hand2",
            command=self.toggle)
        self.btn_power.pack(fill="x", padx=12, pady=12, ipady=10)

        tk.Label(sw, text="点击后同时开启：音频震动 + 滑索扳机震动",
                 font=("Microsoft YaHei UI", 9), bg=CARD, fg=MUTED
                 ).pack(pady=(0, 10))

        # 实时状态
        st = tk.Frame(self.root, bg=CARD)
        st.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(st, text="实时状态", font=("Microsoft YaHei UI", 10, "bold"),
                 bg=CARD, fg=FG).grid(row=0, column=0, columnspan=2,
                                      sticky="w", padx=12, pady=(10, 6))

        self.bars = {}
        for i, (key, name) in enumerate((("left", "左握把"), ("right", "右握把"))):
            tk.Label(st, text=name, font=("Microsoft YaHei UI", 9),
                     bg=CARD, fg=MUTED, width=7, anchor="w"
                     ).grid(row=i + 1, column=0, padx=(12, 4), sticky="w")
            c = tk.Canvas(st, height=16, bg=BAR_BG, highlightthickness=0)
            c.grid(row=i + 1, column=1, sticky="ew", padx=(0, 12), pady=3)
            fill = c.create_rectangle(0, 0, 0, 16, fill=ACCENT, width=0)
            txt = c.create_text(8, 8, text="0", anchor="w",
                                fill=MUTED, font=("Consolas", 9))
            self.bars[key] = (c, fill, txt)
        st.columnconfigure(1, weight=1)

        self.lbl_info = tk.Label(st, text="—", font=("Consolas", 9),
                                 bg=CARD, fg=MUTED, justify="left", anchor="w")
        self.lbl_info.grid(row=3, column=0, columnspan=2, sticky="w",
                           padx=12, pady=(6, 10))

        # 参数
        pr = tk.Frame(self.root, bg=CARD)
        pr.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(pr, text="参数调节", font=("Microsoft YaHei UI", 10, "bold"),
                 bg=CARD, fg=FG).grid(row=0, column=0, columnspan=3,
                                      sticky="w", padx=12, pady=(10, 6))

        tk.Label(pr, text="音频强度", font=("Microsoft YaHei UI", 9),
                 bg=CARD, fg=MUTED, width=9, anchor="w"
                 ).grid(row=1, column=0, padx=(12, 4), sticky="w")
        self.scl_master = ttk.Scale(pr, from_=0.2, to=2.5, orient="horizontal",
                                    variable=self.var_master,
                                    command=self._on_master)
        self.scl_master.grid(row=1, column=1, sticky="ew", pady=3)
        self.lbl_master = tk.Label(pr, text="1.00", font=("Consolas", 9),
                                   bg=CARD, fg=MUTED, width=5)
        self.lbl_master.grid(row=1, column=2, padx=(4, 12))

        tk.Label(pr, text="滑索力度", font=("Microsoft YaHei UI", 9),
                 bg=CARD, fg=MUTED, width=9, anchor="w"
                 ).grid(row=2, column=0, padx=(12, 4), sticky="w")
        self.scl_trig = ttk.Scale(pr, from_=0, to=255, orient="horizontal",
                                  variable=self.var_trigger_drive,
                                  command=self._on_trig)
        self.scl_trig.grid(row=2, column=1, sticky="ew", pady=3)
        self.lbl_trig = tk.Label(pr, text="75", font=("Consolas", 9),
                                 bg=CARD, fg=MUTED, width=5)
        self.lbl_trig.grid(row=2, column=2, padx=(4, 12))
        pr.columnconfigure(1, weight=1)

        # 日志
        lg = tk.Frame(self.root, bg=CARD)
        lg.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        tk.Label(lg, text="运行日志", font=("Microsoft YaHei UI", 10, "bold"),
                 bg=CARD, fg=FG).pack(anchor="w", padx=12, pady=(10, 4))
        self.txt = tk.Text(lg, height=8, bg="#12161e", fg="#a8b3c7",
                           font=("Consolas", 9), relief="flat", bd=0,
                           insertbackground=FG, wrap="word")
        self.txt.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.txt.configure(state="disabled")

    # ---------- 参数回调 ----------

    def _on_master(self, _=None) -> None:
        v = self.var_master.get()
        self.lbl_master.config(text=f"{v:.2f}")
        if self.pipeline is not None:
            self.pipeline.mapper.cfg.master_gain = v

    def _on_trig(self, _=None) -> None:
        v = int(self.var_trigger_drive.get())
        self.lbl_trig.config(text=str(v))
        if self.pipeline is not None:
            self.pipeline.trigger.cfg.drive = v

    # ---------- 启停 ----------

    def toggle(self) -> None:
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self.running:
            return
        self.btn_power.config(text="启 动 中 …", state="disabled")
        self.root.update_idletasks()

        try:
            # 应用界面参数到配置
            d = self.config.data
            d.setdefault("mapping", {})["master_gain"] = float(self.var_master.get())
            d.setdefault("trigger", {})["enabled"] = bool(self.var_trigger_on.get())
            d["trigger"]["drive"] = int(self.var_trigger_drive.get())

            self.pipeline = HapticPipeline(self.config)
        except Exception as e:
            self._fail(f"初始化失败：{e}\n\n"
                       "常见原因：\n"
                       "  · 手柄未连接或飞智空间站未运行\n"
                       "  · 系统没有可用的音频输出设备")
            return

        self.stop_event.clear()
        self.running = True

        def _worker():
            try:
                self.pipeline.run(stop_event=self.stop_event,
                                  on_frame=self._on_frame)
            except Exception as e:
                self.ui_q.put(("error", str(e)))
            finally:
                self.ui_q.put(("stopped", None))

        self.pipe_thread = threading.Thread(target=_worker, daemon=True,
                                            name="pipeline")
        self.pipe_thread.start()

        self.btn_power.config(text="停 止", bg="#8b2f2b",
                              activebackground=DANGER, state="normal")
        self.lbl_state.config(text="● 运行中", fg=ACCENT)

    def stop(self) -> None:
        if not self.running:
            return
        self.btn_power.config(text="停 止 中 …", state="disabled")
        self._log("正在停止…")
        self.stop_event.set()

    def _fail(self, msg: str) -> None:
        self.btn_power.config(text="启 动", bg="#2d7d46",
                              activebackground=ACCENT, state="normal")
        self.lbl_state.config(text="● 已停止", fg=MUTED)
        self.running = False
        self._log("✗ " + msg)
        messagebox.showerror("震动小助手", msg)

    def _on_frame(self, s: dict) -> None:
        if not self.ui_q.full():
            self.ui_q.put(("frame", s))

    # ---------- 事件泵 ----------

    def _pump(self) -> None:
        try:
            for _ in range(60):
                kind, payload = self.ui_q.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "frame":
                    self._update_bars(payload)
                elif kind == "error":
                    self._log("✗ 管线异常：" + payload)
                elif kind == "stopped":
                    self._after_stop()
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _after_stop(self) -> None:
        self.running = False
        self.pipeline = None
        self.pipe_thread = None
        self.btn_power.config(text="启 动", bg="#2d7d46",
                              activebackground=ACCENT, state="normal")
        self.lbl_state.config(text="● 已停止", fg=MUTED)
        for key in self.bars:
            c, fill, txt = self.bars[key]
            c.coords(fill, 0, 0, 0, 16)
            c.itemconfig(txt, text="0")
        self.lbl_info.config(text="—")
        self._log("已停止。")

    def _append_log(self, line: str) -> None:
        self.txt.configure(state="normal")
        self.txt.insert("end", line + "\n")
        # 限制行数，避免长时间运行吃内存
        if int(self.txt.index("end-1c").split(".")[0]) > 400:
            self.txt.delete("1.0", "100.0")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _update_bars(self, s: dict) -> None:
        for key, field in (("left", "drive_l"), ("right", "drive_r")):
            val = int(s.get(field, 0))
            c, fill, txt = self.bars[key]
            w = max(1, c.winfo_width())
            x = int(w * min(val, 255) / 255)
            c.coords(fill, 0, 0, x, 16)
            c.itemconfig(txt, text=str(val))

        tg = int(s.get("trigger_drive", 0))
        if s.get("trigger_active"):
            trig = f"滑索联动中 ({tg})"
        elif s.get("trigger_groups"):
            trig = f"待机（已识别 {s['trigger_groups']} 组信号）"
        else:
            trig = "待机"

        rate = float(s.get("send_rate", 0.0))
        ms = float(s.get("process_ms", 0.0))
        conn = "已连接" if s.get("connected") else "未连接"
        self.lbl_info.config(
            text=f"发送 {rate:5.1f} Hz | 单帧 {ms:4.2f} ms | 手柄 {conn} | 滑索：{trig}")

    # ---------- 关闭 ----------

    def _on_close(self) -> None:
        if self.running:
            self.stop_event.set()
            if self.pipe_thread is not None:
                self.pipe_thread.join(timeout=2.0)
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    try:
        # 高 DPI 适配（Windows）
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    # 全局异常兜底：GUI 程序没有控制台，崩溃必须弹窗告知用户
    def _excepthook(exc_type, exc, tb):
        import traceback
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            messagebox.showerror(
                "震动小助手 — 发生错误",
                f"{exc_type.__name__}: {exc}\n\n详细信息：\n{detail[-1200:]}")
        except Exception:
            pass

    sys.excepthook = _excepthook

    try:
        VibrationAssistant(root)
    except Exception as e:
        _excepthook(type(e), e, e.__traceback__)
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
