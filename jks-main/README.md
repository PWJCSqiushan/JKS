# JKS

Local voice-agent controller with an external OLED expression companion.

JKS lets a desktop app run a voice-call-like loop:

```text
voice button -> recording -> STT -> Hermes / Gran Agent -> TTS playback -> OLED expression
```

The remote agent handles conversation reasoning. The local controller owns microphone recording, audio playback, serial I/O, and OLED safety filtering.

## Hardware Baseline

- Board: ESP32-C3
- Firmware route: MicroPython
- Display: 128x64 I2C OLED
- Controller: SH1106
- I2C address: `0x3C`
- SDA: GPIO4
- SCL: GPIO5
- Baud: `115200`
- Observed serial port on this Mac: `/dev/cu.usbmodem5B900048301`

## Setup

```bash
uv sync
cp .env.example .env
```

Fill `.env` locally. Do not commit secrets.
The app and CLI tools load `.env` from the current working directory by default;
shell environment variables override file values. Placeholder values such as
`replace-with-*` intentionally fail readiness checks.
Fish streaming MP3 playback uses `mpg123 -q -`; install it locally if `--play`
or the desktop app should play Fish TTS as bytes arrive.

Required real-service values for the local Hermes/Grantly + Fish Audio path:

```text
JKS_AGENT_MODE
JKS_AGENT_COMMAND
JKS_AGENT_WORKDIR
JKS_STT_PROVIDER
JKS_TTS_PROVIDER
JKS_FISH_API_KEY
JKS_OLED_PORT
JKS_OLED_BAUD
```

`JKS_AGENT_TOKEN` is optional when the endpoint does not require bearer auth.
`JKS_AGENT_MODEL` defaults to `gran-agent`, `JKS_FISH_TTS_MODEL` defaults to
`s2-pro`, `JKS_FISH_TTS_LATENCY` defaults to `low`, and `JKS_TTS_VOICE`
defaults to `default`. Set `JKS_TTS_VOICE` only when using a specific Fish
voice/reference id.

### Local Hermes / Grantly

The primary Grantly path runs Hermes locally from the synced runtime under
`.local/`:

```dotenv
JKS_AGENT_MODE="local"
JKS_AGENT_HOST=""
JKS_AGENT_AUTH_METHOD=""
JKS_AGENT_COMMAND=".local/bin/jksgrantly"
JKS_AGENT_WORKDIR=".local/hermes-agent"
JKS_AGENT_MODEL="gran-agent"
```

`JKS_AGENT_ENDPOINT` is not required in local mode. The local wrapper uses the
synced profile at `.local/hermes-home/.hermes/profiles/jksgrantly` and invokes
Hermes as `hermes -p jksgrantly ...`. JKS resolves relative command/workdir
paths from the current project directory before launching the subprocess.

### Hermes API Server

If you intentionally run a local Hermes Agent API server, use its OpenAI-compatible Chat
Completions endpoint:

```dotenv
JKS_AGENT_ENDPOINT="http://127.0.0.1:8642/v1/chat/completions"
JKS_AGENT_TOKEN="replace-with-hermes-api-server-key"
JKS_AGENT_MODEL="gran-agent"
```

`JKS_AGENT_TOKEN` must match the Hermes `API_SERVER_KEY` value. JKS sends
`JKS_AGENT_MODEL`, a single user message, `stream:false`, and a
`X-Hermes-Session-Id` header for conversation continuity.

If a Hermes profile advertises another model name, set `JKS_AGENT_MODEL` to that
name. For OLED control through OpenAI Chat Completions, the agent may return a
JSON object as message content:

```json
{"text":"Sure, I am listening.","emotion":"happy","display_text":"YAY","duration_ms":1200,"intensity":"high"}
```

JKS treats `text` as the spoken reply and clamps the display fields through the
local expression safety layer.

### Hermes SSH / CLI Fallback

If a remote machine has Hermes running but no OpenAI-compatible HTTP API port,
JKS can still call the remote Hermes CLI over SSH:

```dotenv
JKS_AGENT_HOST="replace-with-agent-host"
JKS_AGENT_USER="replace-with-agent-user"
JKS_AGENT_AUTH_METHOD="ssh-password"
JKS_AGENT_SSH_PASSWORD="replace-with-ssh-password"
JKS_AGENT_COMMAND="/usr/local/lib/hermes-agent/venv/bin/hermes"
JKS_AGENT_WORKDIR="/usr/local/lib/hermes-agent"
```

SSH key auth also works by omitting `JKS_AGENT_SSH_PASSWORD`. Passwords must
stay in local `.env` or shell environment only. JKS invokes
`hermes --continue <jks-session> -z <prompt>` and asks Hermes to return compact
JSON with `text`, `emotion`, `display_text`, `duration_ms`, and `intensity`.

### Fish Audio Speech

For Fish Audio STT/TTS, set both speech providers to `fish` and keep the API
key only in local `.env`:

```dotenv
JKS_STT_PROVIDER="fish"
JKS_TTS_PROVIDER="fish"
JKS_FISH_API_KEY="replace-with-fish-api-key"
JKS_FISH_TTS_MODEL="s2-pro"
JKS_FISH_TTS_LATENCY="low"
JKS_TTS_VOICE="default"
```

`FISH_AUDIO_API_KEY` and `FISH_API_KEY` are also accepted as aliases when an
existing Fish config already uses those names. `JKS_TTS_VOICE` may be a Fish
Audio `reference_id` / voice model id. When it is `default`, JKS omits
`reference_id`. Fish ASR uses `POST
https://api.fish.audio/v1/asr` with bearer auth and an `audio` form field. Fish
TTS uses `POST https://api.fish.audio/v1/tts`, `model:s2-pro`,
`latency:low`, and `stream=True` response reads so mp3 bytes are written as
Fish emits them for playback.

For non-Fish HTTP speech adapters, configure `JKS_STT_ENDPOINT` and
`JKS_TTS_ENDPOINT`. `JKS_STT_TOKEN` and `JKS_TTS_TOKEN` are optional bearer
tokens for those custom endpoints.

Run the desktop controller:

```bash
uv run jks
```

## Verification

Run all tests:

```bash
uv run python -m unittest discover -s tests -v
```

Run the local fake STT / Agent / TTS smoke:

```bash
uv run python -m tools.jks_smoke
```

Check configuration readiness without printing secrets:

```bash
uv run python -m tools.jks_config_check
```

The default JSON is a safe summary: it reports modes, configured booleans,
missing keys, and warnings without printing endpoints, SSH hosts, usernames,
runtime paths, OLED ports, or tokens. For local-only debugging, add
`--verbose` to print the fuller redacted preflight structure.

Probe configured real contracts:

```bash
uv run python -m tools.jks_contract_probe
```

Probe only Hermes / Gran Agent without requiring Fish Audio:

```bash
uv run python -m tools.jks_agent_probe
```

Probe local microphone permission and signal without sending audio to any
service:

```bash
uv run python -m tools.jks_mic_probe --duration 1 --min-rms 0.0001 --timeout 10
```

Run a chained no-GUI/no-mic turn probe with a real audio file:

```bash
uv run python -m tools.jks_turn_probe --audio /path/to/input.wav
```

Add OLED output to the same probe when the board is connected:

```bash
uv run python -m tools.jks_turn_probe --audio /path/to/input.wav --display --require-display-ack
```

For long OLED animations, increase the ACK window:

```bash
uv run python -m tools.jks_turn_probe --audio /path/to/input.wav --display --require-display-ack --display-ack-timeout 6
```

Probe the same start/stop path used by the desktop Speak button without opening
a GUI:

```bash
uv run python -m tools.jks_app_probe --audio /path/to/input.wav --require-display-ack --display-ack-timeout 6 --play
```

Probe the real Tk event loop and real Speak button widget with the same audio
file:

```bash
uv run python -m tools.jks_gui_probe --audio /path/to/input.wav --require-display-ack --display-ack-timeout 6 --play
```

By default, the turn probe prints text lengths instead of full transcripts so
real user speech is not copied into logs. Probe preflight output is also a safe
summary by default. Add `--verbose` only for local debugging when transcript
output is safe:

```bash
uv run python -m tools.jks_turn_probe --audio /path/to/input.wav --verbose
```

Run OLED hardware smoke:

```bash
uv run python -m tools.oled_smoke
```

The command reads `JKS_OLED_PORT` and `JKS_OLED_BAUD` from `.env` unless
`--port` or `--baud` are provided. For photo or video capture, hold each emotion
longer:

```bash
uv run python -m tools.oled_smoke --hold-ms 2000
```

The OLED smoke covers all base emotions: `neutral`, `listening`, `thinking`,
`speaking`, `happy`, `surprised`, `sleepy`, `sad`, `angry`, and `error`.

Capture visual acceptance evidence outside the repository. First list camera
device indexes, then aim the selected camera at the physical OLED and record
while the OLED smoke cycles moods:

```bash
uv run python -m tools.jks_visual_evidence --list-devices
uv run python -m tools.jks_visual_evidence --camera-device 1 --seconds 20 --hold-ms 1000
```

The helper writes to `/tmp/jks-acceptance-evidence` by default and still
requires visual review: the OLED must actually be readable in the recorded
camera video.

## Firmware

The working firmware files are:

- `firmware/micropython/main.py`
- `firmware/micropython/ssd1306_min.py`

Upload updated firmware with:

```bash
mpremote connect /dev/cu.usbmodem5B900048301 fs cp firmware/micropython/main.py :main.py
mpremote connect /dev/cu.usbmodem5B900048301 reset
```

If `mpremote` is not on `PATH` on this Mac, use the verified local binary:

```bash
/tmp/jks-pio/bin/mpremote connect /dev/cu.usbmodem5B900048301 fs cp firmware/micropython/main.py :main.py
/tmp/jks-pio/bin/mpremote connect /dev/cu.usbmodem5B900048301 reset
```

The OLED protocol is newline-delimited JSON. Example:

```json
{"cmd":"emotion","name":"happy","text":"DONE","duration_ms":1200,"intensity":"normal"}
```

Allowed emotions:

```text
neutral happy thinking speaking listening surprised sleepy sad angry error
```

## Documentation

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the Chinese project plan and phased roadmap.
Use [docs/MANUAL_ACCEPTANCE.md](docs/MANUAL_ACCEPTANCE.md) for the real-service and GUI/OLED acceptance checklist.
