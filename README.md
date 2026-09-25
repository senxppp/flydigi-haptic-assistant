# Flydigi APEX5 音频转震动中间层 · 震动小助手

> **关键词 Keywords：飞智八爪鱼5 / Flydigi APEX 5 / 八爪鱼5 / 震动小助手 / 音频转震动 Audio to Haptics / 震动中间层 Haptic Middleware / HD 震动 HD Haptics / 音圈马达 Voice Coil Haptics / DualSense 模拟 / DS 模式 DS Mode / 自适应扳机 Adaptive Triggers / 扳机震动 Trigger Vibration / 飞智空间站 Flydigi Space Station / 私有 HID 协议 usage page 0xFFA0 / FORCEADAPT / WASAPI Loopback 系统音频捕获 / 明日方舟：终末地 Arknights: Endfield / 赛博朋克2077 Cyberpunk 2077 / 滑索震动 Zipline Haptics / DS Unlock / 进程诱饵 Process Decoy / 手柄模拟器 Gamepad Emulator**

让八爪鱼5在 DS 模式下玩「音频直驱」类游戏（《明日方舟：终末地》等）也能震动。

包含两个能力：
- **音频转震动** —— 拦截系统音频，实时分析后驱动手柄马达
- **扳机震动对齐** —— 读取游戏日志，让滑索等动作的震动与实际动作精确同步

> ⚠️ 仅用于个人学习与硬件折腾，请勿用于任何违反游戏用户协议或法律法规的用途。

---

## 与 DS Unlock 配合使用（推荐组合）

本项目和 **[DS Unlock](https://github.com/senxppp/ds-unlock)** 是**互补的两块拼图**，强烈建议一起用。

### 各自负责什么

| | [DS Unlock](https://github.com/senxppp/ds-unlock) | 震动小助手（本项目） |
|---|---|---|
| **目标** | 让**任意游戏**都能用上 DS 模式的自适应扳机 | 让 DS 模式下**也有握把震动** |
| **手段** | 3.5KB 同名诱饵进程，骗开空间站的**进程名白名单** | 拦截系统音频 → 实时分析 → `0xFFA0` 私有协议**直发握把马达** |
| **产物** | 扳机产生真实阻力（FORCEADAPT 指令） | 握把双马达随音频实时震动 |
| **不碰什么** | 不注入、不读内存、不挂钩子，零反作弊风险 | 同上，只写自己手柄的 HID 接口 |

### 为什么必须两个一起用

DS Unlock 的 README 里「Known Issues」第一条写得很清楚：

> ❗ **DualSense 音圈马达（voice coil）触觉无法转译。** 游戏里专为 DualSense 双音圈线性马达
> 设计的精细 HD 震动（以音频流形式写入输出报文的 haptics）**目前不会被翻译**：飞智的管线
> 只处理扳机阻力效果（FORCEADAPT），而八爪鱼的震动马达与 DualSense 的音圈执行器硬件完全
> 不同，这部分报文被直接丢弃。

翻译成人话：**开了 DS 模式，你拿到自适应扳机，但丢掉精细震动。**

本项目走的正是另一条路——**绕开 DS 翻译管线**：自己拦截系统音频、自己算驱动值、
直接把震动帧写进手柄的 `0xFFA0` 私有接口。所以两者天然分工：

- **DS Unlock** 负责「扳机阻力」→ 走 `FORCEADAPT` 翻译管线
- **震动小助手** 负责「握把震动」→ 走自构造私有帧直发
- 两者都写同一个 `0xFFA0` 接口，实测可**与飞智空间站并存无冲突**（见下方压测结果）

### 推荐使用顺序

1. 先按 DS Unlock 的说明把 **DS 模式打开**
   （空间站里给《赛博朋克 2077》开启「自适应扳机」→ 切到 DS 模式 → 跑诱饵进程）
2. 再启动 **震动小助手**（`launcher.py` 或 `dist/震动小助手.exe`），点一下总开关
3. 最后启动游戏

> **顺序说明**：DS Unlock 要求「先进 DS 模式再进游戏」，因为模式切换伴随虚拟设备
> 销毁/重建（约 1~3 秒）；震动小助手没有这个限制，运行中随时开关都行。

> **关于诱饵进程名**：本项目早期逆向时用 `HorizonForbiddenWest.exe` 触发过 DS 模式，
> DS Unlock 用的是 `Cyberpunk2077.exe`。空间站**只按进程名匹配**（不校验路径、不校验
> 签名），所以两者都能生效；但只有《赛博朋克 2077》在空间站里有「自适应扳机」开关，
> 这正是 DS Unlock 选它当钥匙的原因。

---

## 现状总览

| 层 | 文档章节 | 状态 |
|---|---|---|
| ① 震动输出层（0xFFA0 私有协议直发） | 5.3（方案 D） | **✅ 已完成并实测**（`vib_out/flydigi_vib.py`） |
| ② 音频拦截层（WASAPI Loopback） | 第四章 | **✅ 已实现并实测**（`src/audio/loopback.py`） |
| ③ 分析引擎（RMS/瞬态/频带/过零率） | 5.1 / 3.3 | **✅ 已实现，12 项测试全通过**（`src/analysis/features.py`） |
| ④ 映射层（对数曲线 + ADSR + AGC） | 3.2 / 5.2 / 6.2 | **✅ 已实现，含四套预设**（`src/mapping/`） |
| ⑤ 集成管线（三线程 + 配置 + 看护） | 1.4 / 6.1 / 6.4 | **✅ 已实现**（`src/core/`） |
| ⑥ 压测（100Hz 连发稳定性） | 9.6 问题4 | **✅ 工具就绪**（`loadtest` 子命令） |
| ⑦ UI 界面 / 安装包 | 6.2 / 第七阶段 | **✅ 已完成**（`launcher.py`，一键打包为 exe） |
| ⑧ 真机游戏验证 | 9.6 问题7 | **✅ 已验收**（滑索震动与操作精确对齐） |

---

## 快速开始

```bash
# Python 3.12（依赖：numpy、PyAudioWPatch、hidapi）
cd flydigi-haptic-assistant
PY="python"   # 替换为你自己的 Python 路径

"$PY" -m src.main devices      # 列出可用 Loopback 设备
"$PY" -m src.main bench        # 离线算法基准（不需要手柄/音频）
"$PY" tests/run_all.py         # 19 项单元测试（算法 12 + 环形缓冲 7）
"$PY" -m src.main run          # 实时运行（Ctrl+C 退出）
```

### 图形界面（推荐）

```bash
"$PY" launcher.py
```

界面里一个大按钮即可同时启停「音频震动 + 扳机震动」，
另有音频强度、滑索力度两个滑块和实时力度条。

### 打包成独立 exe

```bash
pip install pyinstaller
pyinstaller "震动小助手.spec" --noconfirm
# 产物在 dist/震动小助手.exe
```

常用参数：

```bash
python -m src.main run --preset racing --gain 0.8     # 切预设 + 调全局强度
python -m src.main run --device "扬声器"               # 指定捕获设备名子串
python -m src.main run --duration 30 --no-ui          # 跑 30 秒，关闭强度条
python -m src.main selftest                           # 合成音频全链路自测（会震动）
python -m src.main loadtest --duration 600 --rate 100 # 100Hz 压测 10 分钟
python -m src.main test-out --mode test               # 直接测震动输出层
```

## 实测验证结果（2026-09-25）

| 验证项 | 结果 |
|---|---|
| Loopback 实时捕获 | ✅ 播放 60Hz 时 76/75 块稳定 |
| 静音零输出 | ✅ 驱动 0/0（RMS 0.000） |
| 低频响应 | ✅ 60Hz → 驱动 158/158 |
| **左右声道分离** | ✅ **仅左声道 → L=158, R=0** |
| 高频滤除 | ✅ 2kHz 经 80Hz 低通后 RMS 0.001（-56dB） |
| 瞬态检测 | ✅ 冲击帧 onset=1.0，稳态 onset=0（零误报） |
| 单帧耗时 | ✅ **1.05ms**（预算 20ms，19× 余量） |
| 100Hz 压测 60s | ✅ 6002 帧，0 失败 0 重连，速率精确 100.0Hz |
| 与空间站并存 | ✅ 压测全程无冲突 |
| 单元测试 | ✅ 19/19 通过 |

---

## 架构

```
游戏音频输出（含震动音频）
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ ① 音频拦截层  src/audio/loopback.py                          │
│    WASAPI Loopback 捕获默认播放设备 → 48kHz/16bit/立体声       │
│    [后台读线程] ──有界队列──► [定长帧消费] 断流自动补静音       │
└───────────────────────────┬──────────────────────────────────┘
                            ▼ 20ms 帧 (960, 2) float32
┌──────────────────────────────────────────────────────────────┐
│ ② 分析引擎  src/analysis/features.py                         │
│    左右声道分离 → 80Hz 低通 → RMS                             │
│    → 能量通量瞬态(onset) / 过零率(zcr) / 三频带能量            │
└───────────────────────────┬──────────────────────────────────┘
                            ▼ FrameFeatures
┌──────────────────────────────────────────────────────────────┐
│ ③ 映射层  src/mapping/mapper.py                              │
│    静音阈值 → 对数曲线 → 低频增强 → AGC → 全局增益            │
│    → 软削波 → ADSR 包络 → 单帧限速 → 0..255                   │
└───────────────────────────┬──────────────────────────────────┘
                            ▼ DriveOutput(left, right)
┌──────────────────────────────────────────────────────────────┐
│ ④ 输出层  src/output/haptic_out.py → vib_out/flydigi_vib.py   │
│    0xFFA0 私有协议帧 [3]=0x03 [5]=左握把 [6]=右握把            │
│    [HID 写线程] 按发送频率下发 + 手柄看护 + 自动归零            │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
                    八爪鱼5 握把双马达
```

**线程模型**（文档 6.1(4)）：音频读线程 / 主处理线程 / HID 写线程三者解耦，通过有界队列传递，互不阻塞。

---

## 实测坑位与关键设计决策

这些是实际踩过、必须知道的点，接手时优先看：

1. **Loopback 在无声时不产出数据，且 `read()` 会阻塞**
   实测：设备无音频播放时，1.2 秒只读到 1 块；播放 60Hz 测试音后稳定 76/75 块。
   → 因此**必须把读与消费解耦**。`LoopbackCapture` 用后台线程读 + 有界队列，消费侧按固定节拍取，取不到补静音。分析引擎时钟因此永远稳定，也不会卡死。
   *副产品*：这天然实现了文档 4.3(3) 的静音检测——静音块进去 RMS=0，输出自动归零。

2. **80Hz 低通必须看稳态，不能看单帧瞬态**
   单帧从零状态启动时，滤波器前几十个样本的振铃会被 RMS 误算成能量（实测 2kHz 单帧 RMS 0.126，连续帧稳态仅 0.001）。这是**测试方法**问题而非算法问题，但提醒：任何滤波器验证都要先跑够预热帧。
   实测稳态衰减：60Hz -1.2dB / 200Hz -16dB / 500Hz -32dB / 2kHz -56dB / 8kHz -82dB。

3. **稳态信号会误触发瞬态检测**
   朴素能量通量法下，持续正弦/噪声的帧间能量起伏被误判为瞬态（实测稳态 onset 恒为 0.2）。
   → `OnsetDetector` 加了双重抑制：**相对增幅门限**（flux 须超过近期能量均值的 `min_ratio` 倍）+ 自适应阈值。修好后稳态 onset 全部归零，冲击帧仍精准命中 1.0。

4. **系统音量直接决定震动强度**（文档 2.1(4)）
   实测播放幅度 0.6 的信号，Loopback 读回峰值仅 494/32767 ≈ 1.5%——因为系统音量较低。这是音频直驱方案的固有特性，不是 bug。**调低游戏音量的同时也减弱了震动**，用户需知悉。AGC 可部分补偿，但补偿的是动态范围而非绝对音量。

5. **必须限制单帧驱动变化量**
   马达驱动信号突变会产生机械噪音（文档 5.2(3) 的爆音问题）。映射层加了 `max_delta_per_frame`（默认 90/帧），配合 ADSR 一起压制。

6. **安全上限不可省**
   逆向协议直接写马达，任何配置错误都可能把马达打满长时间运行（有烧毁风险）。`safety_max_drive` 硬上限（默认 240）+ `auto_stop_ms` 自动归零（默认 120ms）是最后一道保险。

---

## 已验证结论（上一阶段，勿重复逆向）

### DS 模式边界（四通道实测）

| 通道 | 结果 |
|---|---|
| 游戏直驱震动（标准 DualSense 0x31 输出报文） | **不通**。虚拟 DualSense 描述符无 0x31 输出报文，写入返回 err=87 |
| 虚拟 DualSense 的 0x02 私有输出报文（47B） | **无效**。27 段字节扫描零反应，服务日志零转发 |
| 空间站 UI 震动测试（IPC→私有协议） | **通**。`IpcCommandEnum_CallGripVibration`(4177) → `VibrationControllerCommandNewXInput` |
| **自构造私有协议帧直发 0xFFA0 接口** | **通（本项目采用）**。握把双马达独立控制已验证 |

> 这张表正是「必须配合 DS Unlock 使用」的技术依据：**游戏想通过 DS 管线直驱震动，
> 路是堵死的**（前两行）。所以震动必须由本项目在外部补上。

### 震动输出协议（逆向自 SpaceStationService.exe，已实测）

- 目标接口：`VID_37D7 PID_2501 / usage_page 0xFFA0`（MI_02 Col01），输出报文 32 字节，报文 ID 0x03。
- 帧（即发即弃，无 ack）：

```
[0]=0x03  [1]=0x5A  [2]=0xA5  [3]=0x12(震动cmdId)  [4]=0x06
[5]=左握把  [6]=右握把  [7]=左扳机  [8]=右扳机  (0-255)  [9..31]=0x00
```

- **[5][6] 握把完全可用**；[7][8] 扳机字节无效（k5 设备疑似 `IsSupportTriggerVibration=false`）——不阻塞，中间层只用 [5][6]。
- 已知 cmdId：0x01 心跳 / 0x02 昵称 / 0x03 硬件状态 / 0x04 UID / 0x10 原始数据 / 0x12 震动 / 0xA3 映射读。
- 与空间站并存无冲突（服务同接口读写，心跳为周期突发）。

### 环境

- 空间站：`D:\Flydigi Space Station\`；日志 `Logs\service_log_YYYYMMDD.txt`。
- DS 模式 = 魔改 ViGEmBus 内核驱动 `driver\hidvirtualdriver.sys`，虚拟出 `VID_054C PID_0CE6`。
- 触发 DS 模式：启动一个**进程名在白名单里**的进程（如 `HorizonForbiddenWest.exe`
  或 `Cyberpunk2077.exe`），~5 秒后日志出现 `OnGameModStart`。日常使用建议直接用
  [DS Unlock](https://github.com/senxppp/ds-unlock) 的 `DSSwitch.exe` 一键开关。
- 反编译：`ilspycmd --bundle-entry Flydigi.ControllerSdk.dll "D:\Flydigi Space Station\SpaceStationService.exe"`。

---

## 配置说明

配置文件 `configs/config.json`（首次运行自动生成）：

```jsonc
{
  "preset": "action",              // action / racing / music / custom
  "audio": {
    "frame_ms": 20,                // 分析帧长（文档建议 10-20ms）
    "device_hint": null,           // null = 跟随系统默认播放设备
    "sample_rate": 48000
  },
  "mapping": {                     // 覆盖预设中的映射参数（文档 6.2）
    "master_gain": 1.0,            // 全局强度 0-1
    "silence_threshold": 0.02,     // 静音阈值
    "low_boost_gain": 1.4          // 低频增强倍数
  },
  "output": {
    "send_rate_hz": 60,            // 震动帧发送频率（文档建议 50-100Hz）
    "auto_stop_ms": 120,           // 无声后自动归零
    "safety_max_drive": 240        // 硬上限，防止打满马达
  }
}
```

**预设对照**（文档 6.2(5)）：

| 预设 | 曲线 | 强度 | 瞬态敏感度 | ADSR | 适用 |
|---|---|---|---|---|---|
| `action` | 对数 b=14 | 高 | 1.4 | 快（6/20/12ms） | 动作、射击 |
| `racing` | 对数 b=8 | 中 | 0.7 | 平滑（40/80/90ms） | 竞速、驾驶 |
| `music` | 指数 p=1.6 | 中高 | 1.8 | 极快（4/25/18ms） | 音游、节奏 |
| `custom` | 全手动 | 全手动 | 全手动 | 全手动 | 自定义 |

---

## 目录结构

```
flydigi-haptic-assistant/
├── README.md
├── LICENSE                    MIT
├── launcher.py                图形界面（总开关）
├── 震动小助手.spec             PyInstaller 打包配置
├── 震动小助手-使用说明.md      面向使用者的说明
├── TRIGGER-GRIP-说明.md        扳机联动判据完整说明
├── vib_out/flydigi_vib.py     ① 震动输出驱动（已验证，可独立使用）
├── src/
│   ├── audio/loopback.py      ② WASAPI Loopback 捕获
│   ├── analysis/features.py   ③ RMS/瞬态/频带/过零率
│   ├── mapping/
│   │   ├── mapper.py          ④ 映射曲线 + ADSR + AGC
│   │   └── presets.py         四套预设
│   ├── output/haptic_out.py   输出的工程化封装（看护/限速/自动归零）
│   ├── trigger/source.py      扳机联动（双信号组奇偶判定）
│   ├── core/
│   │   ├── pipeline.py        三线程管线
│   │   └── config.py          配置系统
│   └── main.py                CLI 入口
├── configs/config.json        用户配置
├── tests/                     单元测试（19 项）
└── tools/                     逆向调试脚本与测量数据（见 tools/README.md）
```

> `tools/` 里是开发期的探针脚本和测量 CSV，**不是运行时代码**。
> 它们记录了核心结论是怎么一步步验证出来的，索引见 [`tools/README.md`](tools/README.md)。

---

## 相关项目

- **[DS Unlock](https://github.com/senxppp/ds-unlock)** —— 飞智八爪鱼5 DS 模式解锁开关。
  用 3.5KB 诱饵进程骗开空间站的进程名白名单，让任意游戏都能用上自适应扳机。
  **与本项目配合使用**，见上方[《与 DS Unlock 配合使用》](#与-ds-unlock-配合使用推荐组合)。

---

## 已知局限

- **音圈马达级 HD 触觉无法完全复刻**：本项目是「音频 → 转子马达」的近似映射，
  不能还原 DualSense 双音圈线性马达的精细质感。这是硬件差异，不是实现缺陷。
- **系统音量直接影响震动强度**（见「坑位」第 4 条）。
- 空间站若更新检测逻辑，DS 模式的触发方式可能失效（当前为进程名匹配）。

---

## 待办

- ⬜ **USB vs 蓝牙差异**（9.6 问题5）：USB 下 0xFFA0 接口行为应相同但未验证。
- ⬜ **扳机字节 [7][8] 复用**（9.6 问题1，非阻塞）：反编译 `TestForceTriggerCommandFactory` 逆向独立命令族。
- ⬜ **多游戏适配**：目前滑索判据是针对《明日方舟：终末地》日志调出来的，换游戏需要重新标定。
