# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 震动小助手

打包命令:
    python -m PyInstaller 震动小助手.spec --noconfirm

产物:
    dist/震动小助手.exe   单文件，双击即用

关键处理:
  1. `configs/config.json` 作为**数据文件**打进包，
     launcher 首次运行时会释放到 exe 同目录的 configs/ 下，供用户修改。
  2. `hid` / `pyaudiowpatch` 用 hiddenimports 显式声明，
     因为它们是运行时动态导入的（pyd 静态链接，无需额外 DLL）。
  3. 排除 matplotlib / PIL 等未使用的大型库以减小体积。
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 数据文件：把配置打进包（运行时释放到 exe 同级 configs/）
datas = [
    ("configs/config.json", "configs"),
    ("TRIGGER-GRIP-说明.md", "."),
]

hiddenimports = [
    "hid",
    "pyaudiowpatch",
    "numpy",
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    # ⚠ haptic_out.py 通过 sys.path 动态插入 vib_out/ 后 import flydigi_vib，
    #   PyInstaller 静态分析看不到这个依赖，必须显式声明，
    #   否则 exe 运行时报 ModuleNotFoundError: No module named 'flydigi_vib'
    "flydigi_vib",
]
# 收集子模块，确保 pyaudiowpatch 内部引用完整
hiddenimports += collect_submodules("pyaudiowpatch")

excludes = [
    "matplotlib", "PIL", "scipy", "pandas",
    "pytest", "IPython", "notebook",
    "PyQt5", "PySide2", "PySide6", "wx",
]

a = Analysis(
    ["launcher.py"],
    pathex=[".", "vib_out"],       # vib_out 也要加入搜索路径
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="震动小助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # 不用 UPX，避免杀软误报
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # GUI 程序，不显示黑窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
