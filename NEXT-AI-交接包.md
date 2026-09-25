# Flydigi APEX5 音频转震动中间层 — 交接包（2026-09-25 更新）

> 本文件自包含，直接发给任何 AI 即可无缝接手。
> **更新说明**：上一版交接包（阶段一：DS 模式边界逆向 + 震动输出层）已完成；
> 本版加入**阶段二成果**：音频拦截层、分析引擎、映射层、集成管线全部实现并实测通过。

> 📌 这是开发期的**内部交接文档**，保留在此是为了记录「当时做到哪一步、踩了哪些坑」。
> 面向使用者的说明请看 [README.md](README.md) 与 [震动小助手-使用说明.md](震动小助手-使用说明.md)；
> 逆向调试脚本索引见 [tools/README.md](tools/README.md)。
> 文中涉及的本机路径已做脱敏处理。

---

## 0. 任务一句话

开发 Windows 中间层软件：拦截「音频直驱」类游戏（明日方舟：终末地等）输出的震动音频流，
实时分析音频特征，转换为八爪鱼5（Flydigi APEX5）转子马达震动指令输出到手柄。

**当前状态：核心三层全部打通并实测验证，可运行。UI 界面与真机游戏验证均已完成。**

---

## 1. 快速上手（三条命令）

```bash
cd flydigi-haptic-assistant
# 注意：需要 Python 3.12（装了 hidapi / numpy / PyAudioWPatch），不是 PATH 里的 3.13
PY="python"   # 替换为你自己的 Python 路径

"$PY" -m src.main devices     # 列出 Loopback 设备
"$PY" -m src.main bench       # 离线算法基准（无需手柄/音频）
"$PY" tests/run_all.py        # 19 项单元测试
"$PY" -m src.main run         # 实时运行中间层（Ctrl+C 退出）
```

自检环境：
```bash
"$PY" -c "import hid; print([d['path'] for d in hid.enumerate() if d['vendor_id']==0x37d7 and d['usage_page']==0xffa0])"   # 应有一条
"$PY" vib_out/flydigi_vib.py test    # 手柄应三段震动
tasklist | grep -i Horizon           # 假进程在跑 = DS 模式生效
```

---

## 2. 本次新增成果（阶段二）

### 2.1 已实现模块

| 层 | 文件 | 状态 |
|---|---|---|
| ① 震动输出 | `vib_out/flydigi_vib.py` + `src/output/haptic_out.py` | ✅ 实测（含看护/限速/自动归零） |
| ② 音频拦截 | `src/audio/loopback.py` | ✅ 实测（WASAPI Loopback + 采样环形缓冲） |
| ③ 分析引擎 | `src/analysis/features.py` | ✅ 实测（RMS/瞬态/频带/过零率） |
| ④ 映射层 | `src/mapping/mapper.py` + `presets.py` | ✅ 实测（对数曲线 + ADSR + AGC + 4 预设） |
| ⑤ 集成管线 | `src/core/pipeline.py` + `config.py` | ✅ 实测（三线程 + 配置系统） |
| ⑥ CLI | `src/main.py` | ✅ 6 个子命令 |
| ⑦ GUI | `launcher.py` | ✅ 已完成（总开关 + 滑块 + 实时力度条） |
| ⑧ 打包 | `震动小助手.spec` | ✅ 已完成（PyInstaller 单文件 exe） |

### 2.2 实测结论（本轮）

| 验证项 | 结果 |
|---|---|
| Loopback 实时捕获 | ✅ 播放 60Hz 测试音时 76/75 块稳定，无丢帧 |
| 静音零输出 | ✅ 静音段驱动 = 0/0（RMS 0.000） |
| 低频响应 | ✅ 60Hz 播放 → 驱动 158/158 |
| **左右声道分离** | ✅ **仅左声道 → L=158, R=0**（文档 3.2(4) 核心能力） |
| 高频滤除 | ✅ 2kHz 经 80Hz 低通后 RMS 0.001（-56dB） |
| 瞬态检测 | ✅ 静音→冲击帧 onset=1.0，稳态 onset=0（0 误报） |
| 单帧耗时 | ✅ **1.05ms**（帧预算 20ms，**19× 余量**） |
| 环形缓冲完整性 | ✅ 7 项测试（容量/环绕/溢出/多声道） |
| **100Hz 压测 60s** | ✅ **6002 帧，0 失败 0 重连，发送速率精确 100.0Hz** |
| 与空间站并存 | ✅ 压测全程无冲突 |

### 2.3 本轮修掉的关键问题（重要，勿重蹈）

1. **环形缓冲容量约束 bug**（最严重）
   原实现在溢出时只减 `_size` 不移动读起点，导致「有效采样数」可无限增长
   （实测写入 30+250 后 avail=280 > 容量 100）。这会让**音频帧内容错位**。
   修法：溢出时同步缩小有效窗口，起点由 `(_w - _size) % cap` 自然前移。
   → `tests/test_ringbuffer.py` 7 项测试守护此逻辑。

2. **WASAPI Loopback 无声时不产出数据且 read() 阻塞**
   实测：设备无音频播放时 1.2 秒只读到 1 块。→ 必须把读与消费**解耦**
   （后台读线程 + 采样环形缓冲 + 定节拍消费，断流补静音）。

3. **启动瞬间的驱动历史积压**
   打开流后驱动会一次性吐出约 2.5 秒的历史缓冲（多为静音），
   污染统计且让开头几帧误判为有声音。→ `_settle_stream()` 等待稳定后清空。

4. **稳态信号误触发瞬态检测**
   朴素能量通量法下，稳态正弦的帧间起伏被误判（实测 sens=1.8 时 6/30 帧 onset=1.0）。
   修法三道防线：绝对能量门限 + 相对增幅门限（2.5×均值）+ 灵敏度封顶 1.6。

5. **AGC 把底噪放大成震动**
   无信号时 AGC 把增益推到最大 3×，把 -60dB 底噪放大成驱动 180。
   修法：加 `agc_noise_floor`，低于此电平不拉升增益。

6. **单帧测滤波器会得到虚高值**
   从零状态处理单帧时，前几十个样本的瞬态振铃被 RMS 误算（2kHz 单帧 RMS 0.126，
   连续稳态仅 0.001）。→ 任何滤波器验证都要先预热 8+ 帧。

7. **性能统计口径**
   `read_frame()` 的节拍 sleep 不能算进"处理耗时"，否则统计值≈帧长（20ms）。
   只计分析+映射，实测 1.05ms。

8. **滤波器数量直接决定耗时**
   单 biquad 处理 960 点约 0.15ms；从 5 个精简到 3 个后整帧从 1.69ms 降到 1.05ms。

---

## 3. 已验证的底层结论（阶段一，勿重复逆向）

### 3.1 DS 模式边界（四通道实测）

| 通道 | 结果 |
|---|---|
| 游戏直驱震动（DualSense 0x31 输出报文） | **不通**。虚拟 DualSense 描述符无 0x31 输出报文，err=87 |
| 虚拟 DualSense 的 0x02 私有输出报文（47B） | **无效**。27 段字节扫描零反应 |
| 空间站 UI 震动测试（IPC→私有协议） | **通**。`IpcCommandEnum_CallGripVibration`(4177) |
| **自构造私有协议帧直发 0xFFA0 接口** | **通（本项目采用）** |

> 前两行正是本项目**必须配合 [DS Unlock](https://github.com/senxppp/ds-unlock) 使用**的技术依据：
> 游戏想通过 DS 管线直驱震动，路是堵死的，所以震动只能在外部补。

### 3.2 震动输出协议（逆向自 SpaceStationService.exe）

- 接口：`VID_37D7 PID_2501 / usage_page 0xFFA0`（MI_02 Col01），输出报文 32B，报文 ID 0x03。
- 帧（即发即弃，无 ack）：

```
[0]=0x03  [1]=0x5A  [2]=0xA5  [3]=0x12(震动cmdId)  [4]=0x06
[5]=左握把  [6]=右握把  [7]=左扳机  [8]=右扳机  (0-255)  [9..31]=0x00
```

- **[5][6] 握把完全可用**；[7][8] 扳机字节无效（k5 疑似 `IsSupportTriggerVibration=false`）。
- 已知 cmdId：0x01 心跳 / 0x02 昵称 / 0x03 硬件状态 / 0x04 UID / 0x10 原始数据 / 0x12 震动 / 0xA3 映射读。
- 与空间站并存无冲突（本轮 100Hz 压测 60s 证实）。

### 3.3 环境事实

- 空间站：`D:\Flydigi Space Station\`；日志 `Logs\service_log_YYYYMMDD.txt`。
- DS 模式 = 魔改 ViGEmBus 内核驱动 `driver\hidvirtualdriver.sys`，虚拟 `VID_054C PID_0CE6`。
- 触发 DS 模式：启动一个**进程名在空间站白名单里**的进程（如 `HorizonForbiddenWest.exe`
  或 `Cyberpunk2077.exe`），~5s 后日志现 `OnGameModStart`。
  日常使用建议直接用 [DS Unlock](https://github.com/senxppp/ds-unlock) 的 `DSSwitch.exe` 一键开关。
- 反编译：`ilspycmd --bundle-entry Flydigi.ControllerSdk.dll "D:\Flydigi Space Station\SpaceStationService.exe"`

### 3.4 环境依赖（Python 3.12）

```
numpy, hidapi, PyAudioWPatch
```
安装：`"$PY" -m pip install PyAudioWPatch hidapi numpy`。
**注意：不要用 PATH 里的 Python 3.13（无 hidapi/numpy）。**

---

## 4. 架构

```
游戏音频 → [① Loopback 捕获] → 20ms 帧 → [② 分析引擎] → 特征
        → [③ 映射层] → drive(0-255) → [④ 输出层@0xFFA0] → 手柄马达
```

三线程：音频读线程 → 采样环形缓冲 → 主处理线程（20ms 节拍）→ HID 写线程。

---

## 5. 文件清单

| 路径 | 内容 |
|---|---|
| `README.md` | 完整项目文档（架构/坑位/协议/配置） |
| `launcher.py` | GUI 主控（总开关 + 滑块 + 实时力度条） |
| `src/main.py` | CLI 入口（run/devices/bench/selftest/loadtest/test-out） |
| `src/audio/loopback.py` | WASAPI Loopback 捕获 + 采样环形缓冲 |
| `src/analysis/features.py` | 特征提取（RMS/瞬态/频带/过零率） |
| `src/mapping/mapper.py` | 映射曲线 + ADSR + AGC |
| `src/mapping/presets.py` | 四套预设 |
| `src/output/haptic_out.py` | 输出层工程化封装 |
| `src/trigger/source.py` | 扳机联动（双信号组奇偶判定） |
| `src/core/pipeline.py` | 三线程管线 |
| `src/core/config.py` | 配置系统 |
| `vib_out/flydigi_vib.py` | 底层震动驱动（可独立使用） |
| `tests/test_algorithm.py` | 算法测试 12 项 |
| `tests/test_ringbuffer.py` | 环形缓冲测试 7 项 |
| `configs/config.json` | 用户配置 |
| `tools/` | 逆向调试脚本与测量数据（索引见 `tools/README.md`） |

---

## 6. 下一步任务

1. **USB vs 蓝牙差异**（9.6 问题5）：USB 下 0xFFA0 行为应相同但未验证。
   配套工具 `tools/parse_rumble.py`（USB 层抓包分析）已归档，可直接用。
2. **扳机字节 [7][8] 复用**（9.6 问题1，非阻塞）
   反编译 `TestForceTriggerCommandFactory` / `K6TriggerRealtimeCommandFactory` 找独立命令族。
3. **多游戏适配**：当前滑索判据是针对《明日方舟：终末地》日志标定的，换游戏需重新标定。

---

## 7. 已知限制

- **系统音量直接决定震动强度**（文档 2.1(4)）：实测播放幅度 0.6 的信号 Loopback 读回峰值仅 494/32767。
  不是 bug，是音频直驱方案的固有特性。AGC 可补偿动态范围但不能补偿绝对音量。
- 转子马达物理带宽有限（5-80Hz），高频信息被 80Hz 低通滤除。
- **音圈马达级 HD 触觉无法复刻**：本项目是「音频 → 转子马达」的近似映射，
  不能还原 DualSense 双音圈线性马达的精细质感。这是硬件差异，不是实现缺陷。
- `music` 预设灵敏度较高，若在真实音乐游戏里觉得误触，调低 `analysis.onset_sensitivity`。
- 当前为蓝牙连接（USB 未测）。
