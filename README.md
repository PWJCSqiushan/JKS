# JKS 智能语音交互助手

JKS 是一个本地桌面语音交互项目：电脑端完成录音、语音识别、智能体调用和语音播放，ESP32-S3 外接屏显示表情状态。

当前适配硬件：**Waveshare ESP32-S3 Touch AMOLED 1.32**，上位机与开发板通过 USB CDC 串口通信，开发板在 466×466 圆形 AMOLED 屏上显示表情动画。

## 工作流程

```
语音按钮 → 录音 → STT 语音识别 → Agent 智能体 → TTS 语音合成 → AMOLED 表情显示
```

## 核心能力

| 能力 | 说明 |
|------|------|
| 桌面 GUI | 基于 Tk 的本地语音交互界面 |
| 语音输入 | 本地麦克风录音 |
| 语音识别/合成 | Fish Audio 或自定义 HTTP STT/TTS 服务 |
| 智能体调用 | 本地 Hermes/Grantly、Hermes API Server、SSH CLI 回退 |
| 外接显示 | 串口 JSON 指令 → ESP32-S3 AMOLED 表情 |
| 安全配置 | 测试与配置检查默认隐藏密钥、端口、主机名等敏感信息 |

## 硬件说明

**Waveshare ESP32-S3 Touch AMOLED 1.32**

| 项目 | 规格 |
|------|------|
| 主控 | ESP32-S3-PICO-1-N8R8 |
| 屏幕 | 1.32″ 圆形 AMOLED，466×466，CO5300 QSPI |
| 触摸 | CST820，I2C |
| 音频 | ES8311 |
| 通信 | USB CDC 串口，默认 115200 bps |

**主要引脚**

```
AMOLED:     RESET GPIO8, TE GPIO9, CS GPIO10, CLK GPIO11, D0-D3 GPIO12-GPIO15
Touch/I2C:  TP_INT GPIO6, TP_RESET GPIO7, SDA GPIO47, SCL GPIO48
Audio:      MCLK GPIO38, SCLK GPIO39, ASDOUT GPIO40, LRCK GPIO41, DSDIN GPIO42, PA_CTRL GPIO46
Power:      BAT_ADC GPIO4, CODEC_EN GPIO16, PWR_KEY GPIO17, BAT_EN GPIO18
USB:        GPIO19/GPIO20
```

> 当前业务流程使用电脑端麦克风和扬声器。ESP32-S3 板载音频与触摸引脚已在固件中登记，尚未作为主业务输入输出路径。

## 项目结构

```
src/jks/                    # Python 主程序、配置、语音、智能体和显示控制
tools/                      # 烟雾测试、配置检查、硬件探测和验收脚本
tests/                      # 单元测试
firmware/oled-controller/   # ESP32-S3 AMOLED / 旧 OLED PlatformIO 固件
firmware/micropython/       # 历史 MicroPython OLED 固件（非默认目标）
docs/                       # 验收文档和项目计划
.env.example                # 环境变量模板
pyproject.toml              # Python 项目配置
```

## 快速开始

```bash
uv sync
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
```

编辑 `.env` 填写本地服务、API Key 和 ESP32-S3 串口。**不要提交 `.env`。**

## 关键配置

运行至少需要以下变量：

```dotenv
JKS_AGENT_MODE=local
JKS_AGENT_COMMAND=.local/bin/jksgrantly
JKS_AGENT_WORKDIR=.local/hermes-agent
JKS_STT_PROVIDER=fish
JKS_TTS_PROVIDER=fish
JKS_FISH_API_KEY=replace-with-your-key
JKS_OLED_PORT=replace-with-display-port
JKS_OLED_BAUD=115200
```

> `JKS_OLED_PORT` 变量名沿用旧名，当前对应 ESP32-S3 AMOLED 的 USB CDC 串口。

**Fish Audio 示例**

```dotenv
JKS_FISH_TTS_MODEL=s2-pro
JKS_FISH_TTS_LATENCY=low
JKS_TTS_VOICE=default
```

**本地 Hermes / Grantly 示例**

```dotenv
JKS_AGENT_MODE=local
JKS_AGENT_HOST=
JKS_AGENT_AUTH_METHOD=
JKS_AGENT_COMMAND=.local/bin/jksgrantly
JKS_AGENT_WORKDIR=.local/hermes-agent
JKS_AGENT_MODEL=gran-agent
```

## 运行

```bash
uv run jks
```

点击语音按钮后依次进入监听→转写→思考→播放状态，并将对应表情指令发送至 AMOLED 屏幕。串口、智能体或语音服务不可用时，程序会以降级方式运行并提示。

## ESP32-S3 固件

固件位于 `firmware/oled-controller/`，PlatformIO 环境为 `esp32s3_touch_amoled_1_32`。

```bash
# 编译
platformio run -d firmware/oled-controller -e esp32s3_touch_amoled_1_32

# 烧录（替换 <serial-port> 为实际串口）
platformio run -d firmware/oled-controller -e esp32s3_touch_amoled_1_32 -t upload --upload-port <serial-port>
```

> - Arduino / PlatformIO 构建，AMOLED 使用 Arduino_GFX 驱动 CO5300 QSPI 屏幕
> - Arduino_GFX 固定 `1.5.9`，兼容 Arduino-ESP32 2.x core
> - 旧 ESP32-C3 SSD1306 编译环境保留，用于回归测试

## 串口协议

上位机发送 newline-delimited JSON，一行一个命令：

```
probe
clear
{"cmd":"text","text":"JKS DISPLAY TEST"}
{"cmd":"emotion","name":"happy","text":"READY","duration_ms":1200,"intensity":"high"}
```

**支持的表情**：`neutral` `happy` `thinking` `speaking` `listening` `surprised` `sleepy` `sad` `angry` `error`

**ACK 响应**：`{"status":"ok","detail":"happy"}`

## 测试与验收

```bash
# 单元测试
uv run python -m unittest discover -s tests -v

# 配置检查
uv run python -m tools.jks_config_check

# 烟雾测试（本地假服务）
uv run python -m tools.jks_smoke

# 智能体探测
uv run python -m tools.jks_agent_probe

# 真实链路合同探测
uv run python -m tools.jks_contract_probe

# 麦克风探测
uv run python -m tools.jks_mic_probe --duration 1 --min-rms 0.0001 --timeout 10

# AMOLED 串口显示烟雾测试
uv run python -m tools.oled_smoke

# 验收视频拍摄（延长表情保持时间）
uv run python -m tools.oled_smoke --hold-ms 2000

# 带真实音频的单轮链路探测
uv run python -m tools.jks_turn_probe --audio /path/to/input.wav --display --require-display-ack
```

## 验证状态

**已完成**：Python 单元测试通过 · ESP32-S3 AMOLED 固件编译通过 · 串口协议兼容 · 文档同步至 AMOLED 硬件基线

**未完成**：板载 ES8311 音频未作为主录音/播放路径 · CST820 触摸未作为 GUI 输入 · 物理板显示效果待现场验收

## 安全注意事项

- 不要提交 `.env`
- 不要把 API Key、SSH 密码、真实服务地址、用户名写入 README 或测试日志
- 配置检查与探测脚本默认隐藏敏感字段，调试时使用 `--verbose`

## 参考资料

- [Waveshare ESP32-S3 Touch AMOLED 1.32 文档](https://docs.waveshare.net/ESP32-S3-Touch-AMOLED-1.32)
- [手工验收清单](docs/MANUAL_ACCEPTANCE.md)
- [项目计划](PROJECT_PLAN.md)
