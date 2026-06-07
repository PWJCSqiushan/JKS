# JKS 项目计划书

日期：2026-06-06

## 项目目标

JKS 是一个本地语音 Agent 控制器项目。目标是让用户通过桌面端语音按钮与远端 Hermes / Gran Agent 进行类似语音通话的交互，同时把 Agent 的状态和情绪投射到外接 OLED 显示屏，形成一个可爱、灵动的 8bit 像素表情伙伴。

## MVP 范围

MVP 需要完成以下闭环：

1. 用户点击语音按钮开始录音。
2. 用户再次点击按钮停止录音。
3. 本地控制器调用 STT 服务把语音转成文字。
4. 本地控制器把文字发送给远端 Hermes / Gran Agent。
5. Agent 返回文本回复和可选表情意图。
6. 本地控制器调用 TTS 服务生成语音并播放。
7. 本地控制器把安全过滤后的表情状态发送到外接 OLED。
8. OLED 显示短文本和 8bit 表情动画，辅助表达 listening / thinking / speaking / happy / error 等状态。

## 系统架构

```text
用户语音
  -> 本地桌面控制器
  -> STT 服务
  -> Hermes / Gran Agent
  -> 本地桌面控制器
  -> TTS 播放
  -> OLED 表情显示
```

远端 Agent 只负责对话推理和返回 display intent；串口、音频播放、OLED 渲染等硬件控制全部由本地控制器负责。Agent 不能直接执行本地串口命令或 shell 命令。

## 核心模块

- `ConversationOrchestrator`：管理一次语音 turn 的状态机。
- `AudioRecorder` / `AudioPlayer`：负责麦克风录音和本地音频播放。
- `SpeechClient`：抽象 STT / TTS 服务。
- `AgentClient`：连接 Hermes / Gran Agent，并解析多种响应 envelope。
- `ExpressionEngine`：把状态或 Agent display intent 映射为安全的 OLED 表情。
- `DisplayController`：通过 USB serial 向 OLED 固件发送 JSON line 协议。
- MicroPython 固件：在 ESP32-C3 上驱动 SH1106 OLED。

## 已验证硬件基线

- 控制板：ESP32-C3
- 连接方式：USB serial
- 当前 Mac 串口：`/dev/cu.usbmodem5B900048301`
- 波特率：`115200`
- OLED：128x64 I2C OLED
- 控制器：SH1106
- I2C 地址：`0x3C`
- SDA：GPIO4
- SCL：GPIO5
- SH1106 column offset：`2`
- 固件路径：`firmware/micropython/main.py`

## 安全与配置原则

- 不提交服务器密码、API key、token、SSH 私钥或 `.env`。
- `.env.example` 只保留占位值。
- 配置检查必须区分本地 fake smoke 和真实三端集成 readiness。
- 真实集成需要配置 Agent endpoint、OLED port，以及 Fish Audio 凭据或自定义 HTTP STT/TTS endpoint。
- Fish Audio 作为当前语音 provider：`JKS_STT_PROVIDER=fish`、`JKS_TTS_PROVIDER=fish`、`JKS_FISH_API_KEY` 只放本地 `.env`。
- Agent 返回的 display intent 只允许白名单 emotion、短文本、受限 duration 和 intensity。

## OLED 表情系统

基础表情包括：

- `neutral`
- `happy`
- `thinking`
- `speaking`
- `listening`
- `surprised`
- `sleepy`
- `sad`
- `angry`
- `error`

OLED 只显示短标签，例如 `HEAR`、`WAIT`、`TALK`、`DONE`、`OOPS`。完整对话内容通过语音和桌面 transcript 承载，不在 OLED 上长文本滚动。

## 阶段计划

### 阶段 1：本地基础闭环

- 初始化 Python package 和 Tkinter 入口。
- 实现配置加载、fake speech、fake agent、fake display。
- 实现无 GUI smoke test。
- 建立单元测试和本地 contract smoke。

### 阶段 2：真实交互控制

- 实现语音按钮 toggle：第一次点击开始录音，第二次点击停止并处理。
- 实现 STT -> Agent -> TTS -> playback 的完整状态机。
- 确保同一时间只有一个 active turn。
- 错误时显示 OLED `error` 并允许立即重试。

### 阶段 3：Hermes / Gran Agent 接入

- 支持多种 Agent 响应 envelope。
- 支持 Hermes API Server 的 OpenAI-compatible `/v1/chat/completions` 请求格式。
- 支持本地 Hermes CLI transport，用同步到 `.local/` 的 `jksgrantly` wrapper 直接打通 Grantly Agent。
- 保留远端 Hermes CLI 的 SSH transport 作为回退路径。
- 支持可配置 `JKS_AGENT_MODEL`，并可从 OpenAI Chat 文本 JSON 中解析 Agent display intent。
- 增加 Agent contract probe。
- 对请求失败、HTTP 失败、空文本响应做结构化错误处理。
- 在接入真实服务前用 secret-free readiness gate 做验证。

### 阶段 4：OLED 表情能力

- 完整下发 display intent：emotion、display text、duration、intensity。
- 在固件中实现可爱的 8bit 表情帧。
- 覆盖 listening / thinking / speaking / happy / error 等实时状态。
- 增加 OLED smoke 对关键状态和 ACK 的验证。

### 阶段 5：真实服务联调

- 配置真实 Hermes / Gran Agent endpoint。
- 配置 Fish Audio STT / TTS provider 和本地 API key。
- 跑配置检查、contract probe、链式 turn probe、本地 smoke、OLED smoke。
- 记录联调问题和最终可运行命令。

## 验证策略

- 单元测试：配置、Agent parser、Speech、Display、Expression、Orchestrator、UI。
- Contract smoke：本地 fake STT / Agent / TTS 服务闭环。
- OLED smoke：串口 JSON 协议和 ACK 验证。
- 配置检查：输出 compact JSON；默认只给安全摘要，避免打印 endpoint、SSH host/user、OLED port、runtime path 或 token。
- 真实联调：只在本地 `.env` 或外部环境变量中配置敏感信息。

## 当前状态

当前项目已经完成阶段 1 到阶段 4 的主要本地能力：本地 fake 闭环、默认不输出 endpoint / host / port / path / token 的配置检查、Agent 响应 envelope 解析、Hermes API Server OpenAI-compatible 请求适配、本地 Hermes CLI transport、可配置 Hermes model/profile、OpenAI Chat 文本 JSON display intent 解析、Agent-only probe、Fish Audio STT/TTS provider、语音按钮 toggle、Agent / STT / TTS 错误降级、OLED 8bit 表情固件、display intent 安全过滤、全基础情绪 OLED ACK smoke、本机麦克风 start/stop recorder probe、默认隐藏 transcript 且支持分阶段错误定位的链式 `STT -> Agent -> TTS` turn probe、覆盖桌面 Speak/Stop 按钮 start/finish 路径的 no-GUI app probe，以及覆盖真实 Tk `mainloop` 和真实 Speak 按钮控件的 GUI probe。

阶段 5 的自动化真实联调和人眼验收已经通过：远端 Hermes/Grantly 工作树和 `jksgrantly` profile 已同步到本地 `.local/` runtime，`.env` 已切换为 `JKS_AGENT_MODE=local`、本地 `JKS_AGENT_COMMAND=.local/bin/jksgrantly` 和 `JKS_AGENT_WORKDIR=.local/hermes-agent`；本地 Grantly CLI、agent probe、配置 readiness、contract probe、链式 turn probe、no-GUI app probe 和真实 Tk GUI probe 可用于验证。当前仓库不包含真实 API key，也不提交 `.env` 或 `.local/`；真实 secret 只通过本机 shell 环境或未跟踪 runtime/profile 注入。若使用 Hermes API Server，`JKS_AGENT_ENDPOINT` 应指向 `http://127.0.0.1:8642/v1/chat/completions`，`JKS_AGENT_TOKEN` 应使用本机 Hermes `API_SERVER_KEY`，若 Hermes profile 暴露非默认 model 则设置 `JKS_AGENT_MODEL`。远端 SSH Hermes CLI 仅作为回退路径，配置 `JKS_AGENT_HOST`、`JKS_AGENT_USER`、`JKS_AGENT_SSH_PASSWORD`、`JKS_AGENT_COMMAND` 和 `JKS_AGENT_WORKDIR`。Fish Audio 侧需要设置 `JKS_STT_PROVIDER=fish`、`JKS_TTS_PROVIDER=fish`、`JKS_FISH_API_KEY` 或 `FISH_AUDIO_API_KEY`，`JKS_FISH_TTS_MODEL` 默认 `s2-pro`，`JKS_FISH_TTS_LATENCY` 默认 `low`，可选设置 `JKS_TTS_VOICE` 为 Fish voice/reference id。真实联调命令和安全摘要记录在 `docs/ACCEPTANCE_RESULTS.md`。

## 风险与对策

- 真实 Agent 响应格式不稳定：通过 fixture 和 contract probe 先验证再接入。
- STT / TTS 服务失败：统一封装 provider error，并在 UI/OLED 上显示可重试状态。
- OLED 控制器型号差异：当前以已验证的 SH1106 page-addressing 模式作为 MVP 固定基线。
- 长文本显示影响体验：OLED 只显示短标签，完整内容保留在语音和 transcript。
- 密钥泄漏风险：所有 secret 只放在本地环境变量或未跟踪配置文件。
