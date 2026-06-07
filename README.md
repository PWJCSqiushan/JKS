# JKS 智能语音交互助手
      2 +
      3 +JKS 是一个本地桌面语音交互项目，用电脑端完成录音、语音识别、智能体调用和语音播放，并通过 ESP32-S3
          外接屏显示表情状态。
      4 +
      5 +当前项目已经适配临时更换后的硬件：**Waveshare ESP32-S3 Touch AMOLED 1.32**。上位机与开发板之间通
         过 USB CDC 串口通信，开发板负责在 466x466 圆形 AMOLED 屏幕上显示监听、思考、说话、完成、错误等表
         情动画。
      6 +
      7 +## 功能概览
      8 +
      9 +```text
     10 +点击语音按钮 -> 录音 -> STT 语音识别 -> Hermes / Gran Agent 智能体 -> TTS 语音合成 -> AMOLED 表情
         显示
     11 +```
     12 +
     13 +核心能力：
     14 +
     15 +- 桌面 GUI：基于 Tk 的本地语音交互界面。
     16 +- 语音输入：支持本地麦克风录音。
     17 +- 语音识别 / 合成：支持 Fish Audio，也支持自定义 HTTP STT/TTS 服务。
     18 +- 智能体调用：支持本地 Hermes / Grantly、Hermes API Server、SSH CLI 回退模式。
     19 +- 外接显示：通过串口向 ESP32-S3 发送 JSON 指令，在 AMOLED 屏幕上显示状态表情。
     20 +- 安全配置：测试和配置检查默认不打印密钥、端口、主机名、用户名等敏感信息。
     21 +
     22 +## 硬件说明
     23 +
     24 +当前默认硬件：
     25 +
     26 +- 开发板：Waveshare ESP32-S3 Touch AMOLED 1.32
     27 +- 主控：ESP32-S3-PICO-1-N8R8
     28 +- 屏幕：1.32 英寸圆形 AMOLED，466x466
     29 +- 屏幕控制器：CO5300，QSPI 接口
     30 +- 触摸控制器：CST820，I2C 接口
     31 +- 音频芯片：ES8311
     32 +- 上位机通信：USB CDC 串口
     33 +- 默认波特率：`115200`
     34 +
     35 +固件中使用的主要引脚：
     36 +
     37 +```text
     38 +AMOLED: RESET GPIO8, TE GPIO9, CS GPIO10, CLK GPIO11, D0-D3 GPIO12-GPIO15
     39 +Touch/I2C: TP_INT GPIO6, TP_RESET GPIO7, SDA GPIO47, SCL GPIO48
     40 +Audio: MCLK GPIO38, SCLK GPIO39, ASDOUT GPIO40, LRCK GPIO41, DSDIN GPIO42, PA_CTRL GPIO46
     41 +Power/Battery: BAT_ADC GPIO4, CODEC_EN GPIO16, PWR_KEY GPIO17, BAT_EN GPIO18
     42 +USB: GPIO19/GPIO20
     43 +```
     44 +
     45 +说明：当前业务流程仍主要使用电脑端麦克风和扬声器。ESP32-S3 板载 ES8311 音频与 CST820 触摸引脚已在
         固件配置中登记，但尚未作为主业务输入输出路径。
     46 +
     47 +## 项目结构
     48 +
     49 +```text
     50 +.
     51 +├── src/jks/                    # Python 主程序、配置、语音、智能体和显示控制
     52 +├── tools/                      # 烟雾测试、配置检查、硬件探测和验收脚本
     53 +├── tests/                      # 单元测试
     54 +├── firmware/oled-controller/   # ESP32-S3 AMOLED / 旧 OLED PlatformIO 固件
     55 +├── firmware/micropython/       # 历史 MicroPython OLED 固件，当前不是默认目标
     56 +├── docs/                       # 验收文档和项目计划
     57 +├── .env.example                # 环境变量模板
     58 +└── pyproject.toml              # Python 项目配置
     59 +```
     60 +
     61 +## 环境准备
     62 +
     63 +建议使用 `uv` 管理 Python 环境：
     64 +
     65 +```bash
     66 +uv sync
     67 +cp .env.example .env
     68 +```
     69 +
     70 +Windows PowerShell 中如果没有 `cp`，可以使用：
     71 +
     72 +```powershell
     73 +Copy-Item .env.example .env
     74 +```
     75 +
     76 +然后编辑 `.env`，填写本地服务、API Key 和 ESP32-S3 串口。不要把 `.env` 提交到 GitHub。
     77 +
     78 +## 关键配置
     79 +
     80 +真实服务运行至少需要配置：
     81 +
     82 +```text
     83 +JKS_AGENT_MODE
     84 +JKS_AGENT_COMMAND
     85 +JKS_AGENT_WORKDIR
     86 +JKS_STT_PROVIDER
     87 +JKS_TTS_PROVIDER
     88 +JKS_FISH_API_KEY
     89 +JKS_OLED_PORT
     90 +JKS_OLED_BAUD
     91 +```
     92 +
     93 +显示串口配置示例：
     94 +
     95 +```dotenv
     96 +JKS_OLED_PORT="replace-with-display-port"
     97 +JKS_OLED_BAUD="115200"
     98 +```
     99 +
    100 +变量名仍沿用 `JKS_OLED_PORT`，但当前对应的是 ESP32-S3 AMOLED 开发板的 USB CDC 串口。
    101 +
    102 +Fish Audio 配置示例：
    103 +
    104 +```dotenv
    105 +JKS_STT_PROVIDER="fish"
    106 +JKS_TTS_PROVIDER="fish"
    107 +JKS_FISH_API_KEY="replace-with-fish-api-key"
    108 +JKS_FISH_TTS_MODEL="s2-pro"
    109 +JKS_FISH_TTS_LATENCY="low"
    110 +JKS_TTS_VOICE="default"
    111 +```
    112 +
    113 +本地 Hermes / Grantly 示例：
    114 +
    115 +```dotenv
    116 +JKS_AGENT_MODE="local"
    117 +JKS_AGENT_HOST=""
    118 +JKS_AGENT_AUTH_METHOD=""
    119 +JKS_AGENT_COMMAND=".local/bin/jksgrantly"
    120 +JKS_AGENT_WORKDIR=".local/hermes-agent"
    121 +JKS_AGENT_MODEL="gran-agent"
    122 +```
    123 +
    124 +## 运行主程序
    125 +
    126 +```bash
    127 +uv run jks
    128 +```
    129 +
    130 +程序会打开桌面窗口。点击语音按钮后，流程会依次进入监听、转写、思考、播放等状态，并把对应表情指令
         发送给 ESP32-S3 AMOLED 屏幕。
    131 +
    132 +如果串口、智能体或语音服务暂时不可用，程序会尽量以降级方式运行，并在界面或探测结果中提示。
    133 +
    134 +## ESP32-S3 固件
    135 +
    136 +当前默认固件位于：
    137 +
    138 +```text
    139 +firmware/oled-controller/platformio.ini
    140 +firmware/oled-controller/src/main.cpp
    141 +```
    142 +
    143 +默认 PlatformIO 环境：
    144 +
    145 +```text
    146 +esp32s3_touch_amoled_1_32
    147 +```
    148 +
    149 +编译固件：
    150 +
    151 +```bash
    152 +platformio run -d firmware/oled-controller -e esp32s3_touch_amoled_1_32
    153 +```
    154 +
    155 +烧录固件：
    156 +
    157 +```bash
    158 +platformio run -d firmware/oled-controller -e esp32s3_touch_amoled_1_32 -t upload --upload-port <
         serial-port>
    159 +```
    160 +
    161 +说明：
    162 +
    163 +- 固件使用 Arduino / PlatformIO。
    164 +- AMOLED 使用 Arduino_GFX 驱动 CO5300 QSPI 屏幕。
    165 +- Arduino_GFX 固定为 `1.5.9`，用于兼容当前 PlatformIO 拉取的 Arduino-ESP32 2.x core。
    166 +- 旧 ESP32-C3 SSD1306 编译环境仍保留，用于回归测试和备用硬件。
    167 +
    168 +## 串口协议
    169 +
    170 +上位机向开发板发送一行一个 JSON 对象，格式为 newline-delimited JSON。
    171 +
    172 +常用命令：
    173 +
    174 +```text
    175 +probe
    176 +clear
    177 +{"cmd":"text","text":"JKS DISPLAY TEST"}
    178 +{"cmd":"emotion","name":"happy","text":"READY","duration_ms":1200,"intensity":"high"}
    179 +```
    180 +
    181 +支持的表情：
    182 +
    183 +```text
    184 +neutral happy thinking speaking listening surprised sleepy sad angry error
    185 +```
    186 +
    187 +开发板会返回 ACK，例如：
    188 +
    189 +```json
    190 +{"status":"ok","detail":"happy"}
    191 +```
    192 +
    193 +## 测试与验收
    194 +
    195 +运行全部单元测试：
    196 +
    197 +```bash
    198 +uv run python -m unittest discover -s tests -v
    199 +```
    200 +
    201 +配置检查：
    202 +
    203 +```bash
    204 +uv run python -m tools.jks_config_check
    205 +```
    206 +
    207 +本地假服务烟雾测试：
    208 +
    209 +```bash
    210 +uv run python -m tools.jks_smoke
    211 +```
    212 +
    213 +智能体探测：
    214 +
    215 +```bash
    216 +uv run python -m tools.jks_agent_probe
    217 +```
    218 +
    219 +真实链路合同探测：
    220 +
    221 +```bash
    222 +uv run python -m tools.jks_contract_probe
    223 +```
    224 +
    225 +麦克风探测：
    226 +
    227 +```bash
    228 +uv run python -m tools.jks_mic_probe --duration 1 --min-rms 0.0001 --timeout 10
    229 +```
    230 +
    231 +AMOLED 串口显示烟雾测试：
    232 +
    233 +```bash
    234 +uv run python -m tools.oled_smoke
    235 +```
    236 +
    237 +如果要拍摄验收视频，可以延长每个表情保持时间：
    238 +
    239 +```bash
    240 +uv run python -m tools.oled_smoke --hold-ms 2000
    241 +```
    242 +
    243 +带真实音频文件的单轮链路探测：
    244 +
    245 +```bash
    246 +uv run python -m tools.jks_turn_probe --audio /path/to/input.wav --display --require-display-ack
    253 +```
    254 +
    255 +## 当前验证状态
    256 +
    257 +当前版本已完成：
    258 +
    259 +- Python 单元测试通过。
    260 +- ESP32-S3 AMOLED PlatformIO 固件编译通过。
    261 +- 上位机串口协议保持兼容。
    262 +- README、固件文档、`.env.example` 和验收文档已同步到 ESP32-S3 AMOLED 硬件基线。
    263 +
    264 +尚未在 README 中声明完成的内容：
    265 +
    266 +- 未把 ESP32-S3 板载 ES8311 音频作为主录音 / 播放路径。
    267 +- 未把 CST820 触摸作为 GUI 控制输入。
    268 +- 物理板烧录后的显示效果仍需要人工拍摄或现场验收确认。
    269 +
    270 +## 安全注意事项
    271 +
    272 +- 不要提交 `.env`。
    273 +- 不要把 API Key、SSH 密码、真实服务地址、真实用户名写入 README 或测试日志。
    274 +- 配置检查和探测脚本默认会隐藏敏感字段；只有本地调试需要时才使用 `--verbose`。
    275 +
    276 +## 参考资料
    277 +
    278 +- Waveshare ESP32-S3 Touch AMOLED 1.32 文档：https://docs.waveshare.net/ESP32-S3-Touch-AMOLED-1.3
         2
    279 +- 手工验收清单：[docs/MANUAL_ACCEPTANCE.md](docs/MANUAL_ACCEPTANCE.md)
    280 +- 项目计划：[PROJECT_PLAN.md](PROJECT_PLAN.md)
