# tools —— 逆向调试脚本与测量数据

> ⚠️ 这些是**开发期的一次性探针脚本**，不是产品运行时代码。
> 它们被用来摸清飞智手柄私有 HID 协议、验证滑索震动判据。
> 保留在这里是为了可复现 —— 核心结论的每一步都能重新跑一遍。

## 重要说明

- 脚本里的路径是**写死的本机路径**（如 `D:/Flydigi Space Station/...`），
  换机器跑需要自己改。
- 部分脚本需要**独占打开 HID 设备**，跑之前请先关掉主程序。
- `.csv` 是测量数据，`verify_*` / `measure_*` / `reanalyze_*` 系列直接读它们。

## 脚本索引

### HID 协议逆向（摸清飞智私有接口）

| 脚本 | 说明 |
| --- | --- |
| `probe_iface.py` | APEX5 接口探测：列出两个厂商接口的能力，并尝试在 0xFFEF 上发命令。 |
| `scan_cmd.py` | APEX5 命令字扫描器：找"扳机震动"对应的命令。 |
| `scan_write.py` | 带播报的握把/扳机命令扫描器（第二轮，针对写命令族）。 |
| `raw_pulse.py` | 裸脉冲诊断：绕过中间层，直接持续重发震动帧。 |
| `dig_port.py` | 找 AdapterTriggerService 监听的端口号，以及相关网络配置。 |
| `dig_port2.py` | 精确定位 AdapterTriggerService 的端口号。 |
| `dig_service.py` | 挖掘 SpaceStationService.exe 里与扳机/震动相关的字符串与帧格式。 |
| `dig_vib.py` | 在服务 exe 里找 VibParams / VibType 的处理逻辑与相关 HID 命令字。 |
| `dig_hidcmd.py` | 在服务 exe 里找 HID 命令帧的字节结构。 |
| `dig_frames.py` | 从空间站日志里挖出所有真实的 HID 命令帧，并归类。 |
| `enum_ports.py` | 枚举服务的 UDP 监听端口 + 所有端口的完整信息。 |
| `unix_connect.py` | 用 Winsock2 (AF_UNIX = 1) 连接 fcs.sock。 |
| `udp_sniff.py` | 监听/探测飞智服务的 UDP 端口 7878（AdapterTriggerService）。 |
| `pipe_probe.py` | 诊断 fcs.sock 管道的可连接性，并尝试多种连接方式。 |
| `_dig_proto.py` | protobufjs 生成的类通常长这样: (function(){ ... }) 里带 fields: {cmdId:{type:"string",id:1},...} |
| `_dig_force.py` | 过滤纯枚举列表 |
| `_dig_send.py` | 找前端发送 IPC 的具体实现（怎么把 JSON 送到服务）。 |
| `_dig_uid.py` |  |

### 音频 / 日志特征提取

| 脚本 | 说明 |
| --- | --- |
| `analyze_bands.py` | 对比分析：冲击段 vs 呼呼声段的完整频带特征。 |
| `analyze_frames.py` | 分析录制的帧序列，定位「冲击 → 绵长呼啸」这类事件。 |
| `record_frames.py` | 全帧录制：把每一帧的完整特征写 CSV，供事后分析声学包络。 |
| `live_probe.py` | 实时探针：跑完整管线，但把每帧强度打到一行，方便与听感对照。 |
| `corr_hid_log.py` | 对照实验：同时记录 HID 字节快照 + 日志扳机事件，找相关性。 |
| `probe_log_latency.py` | 评估用服务日志作为扳机震动信号源的可行性（延迟/吞吐）。 |
| `verify_trigger_corr.py` | 验证「呼呼声 = 扳机震动」假设。 |
| `verify_airflow.py` | 离线验证气流通道：对比开关前后的映射结果 + 扫描 gain。 |
| `tail_log.py` | 实时跟踪空间站服务日志，抓取新出现的命令帧。 |
| `watch_all.py` | 监视飞智服务的 UDP 端口流量变化 + 日志变化。 |

### 滑索判定验证（核心结论：双信号组奇偶）

| 脚本 | 说明 |
| --- | --- |
| `zipline_print.py` | 滑索音频指纹抓取：日志信号 + 多频段能量 + RMS，同时对齐。 |
| `analyze_zipline.py` | 分析滑索音频指纹：把日志信号与多频段能量精确对齐。 |
| `measure_zip_dur.py` | 正确测量：单次滑索的音频持续时长。 |
| `verify_two_groups.py` | 验证「双信号组」判据：信号组1=进入滑索，信号组2=脱离滑索。 |
| `verify_hid_rule.py` | 离线验证 HID 判据：用真实对照数据重放，看动作时长是否与 HID 活跃段一致。 |
| `verify_lowfreq.py` | 用低频段能量做滑索判据的可行性验证。 |
| `diag_zipslide.py` | 滑索诊断 —— 同时记录扳机信号与音频能量，输出时间线。 |

### 扳机联动实验

| 脚本 | 说明 |
| --- | --- |
| `trigger_grip.py` | 扳机联动握把震动 —— 实时演示。 |
| `trigger_grip2.py` | 扳机联动握把震动 —— 完整实现（动作间有明显分割）。 |
| `trigger_grip3.py` | 扳机联动握把震动 v3 —— 相对包络下降检测。 |
| `trigger_grip4.py` | 扳机联动握把震动 v4 —— 修复峰值串扰 + 大幅降低结束延迟。 |
| `trigger_grip5.py` | 扳机联动握把震动 v5 —— 极速响应版（<50ms）。 |
| `trigger_grip6.py` | 扳机联动握把震动 v6 —— 双通道极速结束判定。 |
| `trigger_grip7.py` | 扳机联动握把震动 v7 —— 修正 v6 的"起势误杀"。 |
| `sniff_trigger_state.py` | 直读飞智私有接口 0xFFA0，找扳机震动状态。 |
| `timeline_trigger_state.py` | 时间线抓取 0xFFA0 —— 把字节变化和「扳机震动开/关」对齐。 |
| `sweep_trigger.py` | 参数扫描：在真实抓取数据上找出一组能正确匹配滑索时长的判定参数。 |
| `watch_trigger_timeline.py` | 观察扳机信号在一次完整动作中的时间分布。 |
| `measure_action.py` | 滑索时长实测 —— 按空格标记开始/结束，统计真实时长分布。 |
| `watch_action.py` | 动作事件监测：打印完整特征，用于定位某个游戏动作的声学指纹。 |
| `replay_trigger.py` | 离线重放：用真实抓取数据验证扳机联动的结束判定。 |
| `reanalyze_ab.py` | 重新分析对照实验：以「用户真实操作」为分界，而不是蜂鸣分段。 |
| `ab_probe.py` | 对照实验：静止 vs 滑索 —— 判定 0xFFA0 字节能否识别滑索状态。 |
| `dual_probe.py` | 双通道对齐抓取：一次性确定滑索的**结束信号**到底来自哪一路。 |
| `test_shared_read.py` | 验证：能否在输出层持有句柄的同时，以共享模式读取 0xFFA0。 |
| `probe_dualsense.py` | 探测虚拟 DualSense 的 HID 端点，找可读的扳机数据通道。 |
| `sniff_ds_bytes.py` | 监听虚拟 DualSense 的输入报告，找出随动作变化的字节。 |

### USB 层抓包分析（早期路线，后被 HID 层取代）

| 脚本 | 说明 |
| --- | --- |
| `parse_rumble.py` | 解析 **USBPcap** 抓包文件（linktype 249），提取主机→设备（OUT）方向的震动/输出指令，可按 Xbox360 输出报告解码（`payload[0]==0x00 and payload[1]==0x08` → 左/右马达字节）。支持 `--device N` 过滤、`--all` 显示上行包、`--follow` 实时跟踪文件增长。 |

> 这是**早期从 USB 协议层**摸手柄输出的路线，后来产品改用更直接的
> **HID 层**方案（上方各组脚本）。保留它是因为对「USB vs 蓝牙差异」这类
> 未完成的问题仍然有用。
>
> ⚠️ 配套的抓包文件 `*.pcap` **不在本仓库里**：整机 USB 抓包会包含
> **所有** USB 设备（键盘、存储等）的流量，不适合公开。需要时自行用
> USBPcap 重新抓一份。

## 数据文件

| 文件 | 说明 |
| --- | --- |
| `_ab.csv` | A/B 双相位逐帧 HID 原始帧（静止 / 滑索 / 静止） |
| `_dual.csv` | HID + 音频双通道时间线 |
| `_dual_rms.csv` | 纯音频 RMS 逐帧（replay_trigger / sweep_trigger 的输入） |
| `_zp.csv` | 滑索逐帧特征（rms + 四频段 + 信号位） |
| `zipslide.csv` | 滑索早期采集：左右声道 RMS / onset / zcr / 频段 / drive |
| `frames_airflow.csv` | 逐帧全特征录制（2252 帧）：左右声道 rms / onset / zcr / 低频带 / drive / agc。用于对比「气流声」通道开关前后的映射结果 |
| `frames_whoosh.csv` | 逐帧全特征录制（3002 帧）：同上格式，针对「呼呼声」段（`analyze_bands.py` / `verify_airflow.py` 的输入） |

## 跑法

```bash
python tools/verify_two_groups.py    # 验证双信号组奇偶判定
python tools/verify_hid_rule.py      # 验证 HID byte4~11 反映输入活动
python tools/measure_zip_dur.py      # 测量滑索动作时长

# USB 层抓包分析（需要先用 USBPcap 抓一份 .pcap）
python tools/parse_rumble.py capture.pcap            # 只看下行指令
python tools/parse_rumble.py capture.pcap --follow   # 实时跟踪新指令
```
