# JKS Voice Agent OLED Design

Date: 2026-06-05

## Objective

Build a local desktop controller that makes the project feel like a voice call with the remote Hermes / Gran agent while driving an external OLED expression device in real time.

The MVP must support:

- Press or click a voice button to record speech.
- Convert speech to text.
- Send text to the remote Hermes / Gran agent service.
- Receive agent text and an optional display intent.
- Generate and play TTS audio from the agent reply.
- Show cute, lively 8bit-style expressions on the OLED during the conversation.

## Verified Hardware Baseline

The display route is already validated and should be treated as fixed for MVP implementation.

- Control board: ESP32-C3
- Connection: USB serial from the local computer
- Serial port observed on this Mac: `/dev/cu.usbmodem5B900048301`
- Serial baud: `115200`
- Firmware route: MicroPython on ESP32-C3
- OLED module: external 128x64 I2C OLED
- OLED controller: SH1106
- OLED address: `0x3C`
- OLED pins: `SDA=GPIO4`, `SCL=GPIO5`
- SH1106 column offset: `2`
- Current working firmware files:
  - `firmware/micropython/main.py`
  - `firmware/micropython/ssd1306_min.py`
- Original board flash backup:
  - `hardware/esp32c3-current-flash-4mb.bin`

Important hardware lesson: SSD1306 mode can light the panel but causes random pixel noise on this OLED module. The working display mode is SH1106 page-addressing mode.

## MVP Architecture

The MVP is a local desktop controller. Local software owns all low-latency and hardware-facing work. The remote agent owns conversation reasoning.

```text
User voice
  -> Local Controller
  -> STT
  -> Remote Hermes / Gran Agent
  -> Local Controller
  -> TTS playback
  -> OLED expression updates
```

The remote agent must not directly access local serial devices. It may return text plus a display intent. The local controller validates and maps that intent into OLED commands.

## Components

### ConversationOrchestrator

Owns the conversation state machine and coordinates all other modules.

States:

- `idle`
- `listening`
- `transcribing`
- `thinking`
- `speaking`
- `error`

Only one voice turn is processed at a time in MVP. A new click while a turn is active either stops recording or is ignored based on the current state.

### AudioInput

Records local microphone audio when the user clicks or presses the voice control.

Responsibilities:

- Start recording on user action.
- Stop recording on second user action for MVP.
- Save audio in a format accepted by the STT provider.
- Return a local audio path or byte buffer to `ConversationOrchestrator`.

### SpeechClient

Abstracts STT and TTS providers.

Responsibilities:

- `transcribe(audio) -> text`
- `synthesize(text, voice) -> playable audio`
- Surface provider failures with structured errors.

The design allows OpenAI or another speech API later, but the orchestration layer should not depend on a provider-specific SDK shape.

### AgentClient

Connects to the remote Hermes / Gran agent.

Responsibilities:

- Send user text and conversation metadata.
- Receive agent reply text.
- Receive optional display intent when available.
- Hide transport details such as SSH tunnel, HTTP endpoint, or local proxy.

Credentials and server details must be configured outside committed source files.

### DisplayController

Controls the OLED expression device.

Responsibilities:

- Maintain a whitelist of allowed expression states.
- Send newline-delimited JSON commands over serial.
- Read optional ACK lines from the device.
- Degrade cleanly when the serial device is unavailable.

Current verified OLED protocol:

```json
{"cmd":"emotion","name":"happy","text":"READY"}
{"cmd":"emotion","name":"thinking","text":"WAIT"}
{"cmd":"text","text":"JKS READY"}
{"cmd":"clear"}
{"cmd":"probe"}
```

Current ACK example:

```json
{"status":"ok","detail":"happy"}
```

### Config

Configuration is loaded from environment variables or a local untracked config file.

Required MVP configuration:

```text
JKS_AGENT_HOST
JKS_AGENT_USER
JKS_AGENT_AUTH_METHOD
JKS_AGENT_ENDPOINT
JKS_STT_PROVIDER
JKS_TTS_PROVIDER
JKS_TTS_VOICE
JKS_OLED_PORT=/dev/cu.usbmodem5B900048301
JKS_OLED_BAUD=115200
```

Secrets such as passwords, API keys, SSH private keys, and tokens are never committed to the repository.

## Agent Response Contract

Preferred structured response:

```json
{
  "text": "当然可以，我来帮你看一下。",
  "emotion": "thinking"
}
```

MVP fallback when the agent only returns plain text:

- While recording: `listening`
- While transcribing: `thinking`
- While waiting for the agent: `thinking`
- While playing TTS: `speaking`
- After successful playback: `happy`
- On recoverable failure: `error`

The local controller may infer a simple expression from text, but inference must remain conservative. The agent cannot request arbitrary serial payloads or shell commands.

## Expression System

The expression system must feel cute, lively, and like a small pixel companion rather than a static status screen.

Base expression names:

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

Animation rules:

- `idle`: subtle blink and breathing rhythm.
- `listening`: attentive eyes and small rhythmic movement.
- `thinking`: eye movement or flashing question mark.
- `speaking`: mouth alternates between 2 to 3 frames.
- `happy`: short bounce or blink after a successful response.
- `error`: brief gentle shake, then return to neutral.

OLED text rules:

- Do not display long agent replies on the OLED.
- Use short labels such as `WAIT`, `TALK`, `DONE`, `READY`.
- The voice output carries the full response; the OLED carries personality and state.

Agent display intent may include:

```json
{
  "emotion": "happy",
  "display_text": "DONE",
  "duration_ms": 1200,
  "intensity": "normal"
}
```

The local controller clamps duration and intensity to safe values.

## Data Flow

One complete voice turn:

1. User clicks the voice button.
2. `ConversationOrchestrator` sets OLED to `listening`.
3. `AudioInput` records microphone input.
4. Recording ends by second click.
5. `ConversationOrchestrator` sets OLED to `thinking`.
6. `SpeechClient.transcribe()` returns user text.
7. `AgentClient.send_message()` sends the text to the remote agent.
8. Agent returns text and optionally an emotion.
9. `ConversationOrchestrator` sets OLED to `speaking`.
10. `SpeechClient.synthesize()` creates audio.
11. Local controller plays audio.
12. OLED transitions to the agent-requested emotion or `happy`.
13. State returns to `idle`.

## Error Handling

Serial unavailable:

- Log the serial failure.
- Continue voice conversation without OLED.
- Show a reconnect prompt in the local UI.

STT failure:

- OLED shows `error`.
- Preserve the recorded audio path for debugging.
- Allow immediate retry.

Agent timeout:

- OLED transitions from `thinking` to `error`.
- Preserve transcribed user text.
- Show the preserved text in the local UI so the user can retry without losing context.

TTS failure:

- Preserve the agent text response.
- Display `error` or `neutral`.
- Use text output or silent fallback in MVP.

Malformed agent display intent:

- Ignore invalid fields.
- Fall back to state-based expressions.
- Never pass arbitrary payloads to serial.

## Security Boundaries

- Do not commit root passwords, API keys, tokens, or private keys.
- Prefer SSH key or local proxy authentication over embedding passwords.
- Remote agent output is data, not executable code.
- OLED commands are limited to a whitelist of JSON command types.
- The remote server cannot directly open local serial ports.
- Local logs should redact credentials and access tokens.

## Testing And Verification

Existing tests:

```bash
uv run python -m unittest discover -s tests -v
```

Current expected result:

```text
OK
```

Manual OLED verification:

```bash
uv run python -m tools.oled_serial --port /dev/cu.usbmodem5B900048301 emotion happy
uv run python -m tools.oled_serial --port /dev/cu.usbmodem5B900048301 text "JKS READY"
uv run python -m tools.oled_serial --port /dev/cu.usbmodem5B900048301 clear
```

Firmware verification:

```bash
/tmp/jks-pio/bin/mpremote connect /dev/cu.usbmodem5B900048301 exec "import sys; print(sys.implementation)"
```

MVP implementation should add focused tests for:

- Conversation state transitions.
- Agent response parsing.
- Display intent validation.
- Serial command encoding.
- Speech provider error handling through fakes.

## Acceptance Criteria

The MVP is accepted when all criteria are met:

- The user can click a voice control to record speech.
- The recorded speech is transcribed to text.
- The text is sent to the remote Hermes / Gran agent.
- The agent reply is received and preserved as text.
- The reply is synthesized to audio and played locally.
- OLED displays `listening`, `thinking`, `speaking`, and a completion expression.
- OLED expressions are cute and lively, with at least four short animation states.
- Serial, STT, agent, and TTS failures each have a clear degraded state.
- Secrets are not committed.
- Host-side tests pass.
- Hardware display can be manually verified through the serial command tool.

## Non-Goals For MVP

- Independent hardware voice terminal.
- Browser/PWA permission model.
- Full expression editor.
- Remote server direct control of local serial devices.
- Streaming duplex voice conversation.
- Long text rendering on OLED.
- Production enclosure or PCB redesign.

## Future Phases

Phase 2:

- Streaming partial STT and earlier `thinking` transitions.
- More expressive pixel animations.
- Better speech interruption and barge-in behavior.
- Local session transcript viewer.

Phase 3:

- Dedicated desktop app UI.
- Agent tool display protocol for richer OLED behavior.
- Hardware enclosure and cable routing.
- Optional independent device client.

Phase 4:

- Wake word.
- Always-on low-power idle animation.
- Multi-agent or persona-specific expression packs.
- Deployment automation for remote Hermes / Gran agent integration.
