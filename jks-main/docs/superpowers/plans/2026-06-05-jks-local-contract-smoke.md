# JKS Local Contract Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add repeatable local contract smoke tooling for the JKS voice-agent path without real secrets, real microphone input, real network services, or GUI interaction.

**Architecture:** A local fake HTTP service exposes `/health`, `/stt`, `/chat`, and `/tts` with the same contract consumed by `HttpSpeechClient` and `HttpAgentClient`. A one-shot smoke runner starts that service, injects fake recorder/player/display objects into `ConversationOrchestrator`, runs one complete turn, and prints a JSON summary. OLED hardware smoke uses the existing newline-delimited JSON protocol on one read-write serial fd and reads ACK lines; it avoids `mpremote exec` after firmware boot because that can interrupt `main.py`.

**Tech Stack:** Python standard library `http.server`, `threading`, `wave`, `json`, `unittest`, existing `requests` dependency, existing serial helpers in `src/jks/display.py`.

---

## File Structure

- Create: `tools/jks_fake_services.py` - loopback fake STT/chat/TTS HTTP server and reusable server factory.
- Create: `tools/jks_smoke.py` - one-shot no-GUI/no-secret/no-microphone smoke runner.
- Create: `tools/oled_smoke.py` - OLED ACK smoke over the firmware JSON protocol.
- Modify: `tools/oled_serial.py` - add a `probe` subcommand matching firmware and `DisplayController.probe()`.
- Test: `tests/test_fake_services.py`
- Test: `tests/test_smoke.py`
- Test: `tests/test_oled_smoke.py`
- Test: `tests/test_oled_serial_protocol.py`

## Task 1: Fake HTTP Contract Services

**Files:**
- Create: `tools/jks_fake_services.py`
- Create: `tests/test_fake_services.py`

- [ ] **Step 1: Write failing tests**

Create tests that start a local fake server on `127.0.0.1:0`, then verify:

```python
def test_fake_service_health_stt_chat_tts_contracts():
    server = start_fake_services()
    try:
        base_url = server.base_url
        assert requests.get(base_url + "/health", timeout=2).json()["ok"] is True
        assert requests.post(base_url + "/stt", files={"audio": ("input.wav", b"audio")}, timeout=2).json()["text"]
        chat = requests.post(base_url + "/chat", json={"message": "hello", "conversation_id": "c1"}, timeout=2).json()
        assert chat["text"]
        assert chat["emotion"] in {"happy", "thinking", "neutral"}
        tts = requests.post(base_url + "/tts", json={"text": "reply", "voice": "warm"}, timeout=2)
        assert tts.content[:4] == b"RIFF"
    finally:
        server.stop()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run python -m unittest tests.test_fake_services -v
```

Expected: fails because `tools.jks_fake_services` does not exist.

- [ ] **Step 3: Implement fake services**

Implement `FakeServiceServer` with:

- `base_url: str`
- `events: list[dict[str, object]]`
- `stop() -> None`

Implement `start_fake_services(host="127.0.0.1", port=0) -> FakeServiceServer`.

Endpoints:

- `GET /health` returns `{"ok": true}`.
- `POST /stt` returns `{"text": "hello agent"}` and records an event.
- `POST /chat` parses JSON and returns `{"text": "Fake reply to: <message>", "emotion": "happy", "display_text": "DONE", "duration_ms": 1200, "intensity": "normal"}`.
- `POST /tts` returns a short WAV generated with `wave`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run python -m unittest tests.test_fake_services -v
uv run python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/jks_fake_services.py tests/test_fake_services.py
git commit -m "test: add local fake contract services"
```

## Task 2: One-Shot No-GUI Smoke Runner

**Files:**
- Create: `tools/jks_smoke.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write failing tests**

Test `run_smoke()` starts fake services, uses injected fake recorder/no-op player/captured display, runs one turn, and returns a summary:

```python
def test_run_smoke_returns_success_summary():
    summary = run_smoke()
    assert summary["ok"] is True
    assert summary["user_text"] == "hello agent"
    assert summary["agent_text"].startswith("Fake reply")
    assert "listening" in summary["display_emotions"]
    assert "speaking" in summary["display_emotions"]
    assert summary["played_count"] == 1
    assert {"stt", "chat", "tts"}.issubset(set(summary["server_events"]))
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run python -m unittest tests.test_smoke -v
```

Expected: fails because `tools.jks_smoke` does not exist.

- [ ] **Step 3: Implement smoke runner**

Implement:

- `run_smoke() -> dict[str, object]`
- `main(argv=None, stdout=sys.stdout) -> int`

`run_smoke()` should:

1. Start `start_fake_services()`.
2. Create temporary fake WAV path.
3. Build `HttpSpeechClient` and `HttpAgentClient` pointed at fake server.
4. Inject fake recorder, no-op player, and captured display into `ConversationOrchestrator`.
5. Return summary JSON-safe dict.

`main()` prints compact JSON and exits 0 when `ok` is true.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run python -m unittest tests.test_smoke -v
uv run python -m tools.jks_smoke
uv run python -m unittest discover -s tests -v
```

Expected: tests pass; CLI prints JSON with `"ok": true`.

- [ ] **Step 5: Commit**

```bash
git add tools/jks_smoke.py tests/test_smoke.py
git commit -m "test: add local end-to-end smoke runner"
```

## Task 3: OLED ACK Smoke

**Files:**
- Create: `tools/oled_smoke.py`
- Create: `tests/test_oled_smoke.py`

- [ ] **Step 1: Write failing tests**

Test the smoke function against a fake read/write stream:

```python
def test_oled_smoke_sends_commands_and_collects_acks():
    port = FakePort([
        b'{"status":"ok","detail":"probe"}\n',
        b'{"status":"ok","detail":"happy"}\n',
        b'{"status":"ok","detail":"text"}\n',
        b'{"status":"ok","detail":"clear"}\n',
    ])
    result = run_oled_smoke(port=port)
    assert result["ok"] is True
    assert [ack["detail"] for ack in result["acks"]] == ["probe", "happy", "text", "clear"]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run python -m unittest tests.test_oled_smoke -v
```

Expected: fails because `tools.oled_smoke` does not exist.

- [ ] **Step 3: Implement OLED smoke**

Implement:

- `run_oled_smoke(port=None, port_path="/dev/cu.usbmodem5B900048301", baud=115200, timeout=1.0) -> dict[str, object]`
- `main(argv=None, stdout=sys.stdout) -> int`

The smoke sends JSON frames for:

1. `{"cmd":"probe"}`
2. `{"cmd":"emotion","name":"happy","text":"SMOKE OK"}`
3. `{"cmd":"text","text":"JKS SMOKE"}`
4. `{"cmd":"clear"}`

It reads ACKs from the same fd, returns parsed ACKs, and does not call `mpremote exec`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run python -m unittest tests.test_oled_smoke -v
uv run python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/oled_smoke.py tests/test_oled_smoke.py
git commit -m "test: add oled ack smoke runner"
```

## Task 4: OLED Serial Probe Subcommand

**Files:**
- Modify: `tools/oled_serial.py`
- Modify: `tests/test_oled_serial_protocol.py`

- [ ] **Step 1: Write failing tests**

Add tests:

```python
def test_probe_helper_encodes_command():
    assert json.loads(encode_probe().decode()) == {"cmd": "probe"}

def test_cli_writes_probe_command_to_binary_output():
    output = FakeOutput()
    main(["probe"], output=output)
    assert json.loads(output.getvalue().decode()) == {"cmd": "probe"}
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run python -m unittest tests.test_oled_serial_protocol -v
```

Expected: fails because `encode_probe` and `probe` parser are missing.

- [ ] **Step 3: Implement probe command**

Add:

- `probe_command() -> dict[str, str]`
- `encode_probe() -> bytes`
- `probe` subparser in `build_parser()`
- branch in `frame_from_args()`

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run python -m unittest tests.test_oled_serial_protocol -v
uv run python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/oled_serial.py tests/test_oled_serial_protocol.py
git commit -m "feat: add oled probe serial command"
```

## Task 5: Final Verification

**Files:**
- No required source changes.

- [ ] **Step 1: Full tests**

Run:

```bash
uv run python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Local no-secret smoke**

Run:

```bash
uv run python -m tools.jks_smoke
```

Expected: JSON output includes `"ok":true`.

- [ ] **Step 3: OLED hardware smoke**

If OLED is connected and `main.py` is running, run:

```bash
uv run python -m tools.oled_smoke --port /dev/cu.usbmodem5B900048301
```

Expected: JSON output includes ACKs for `probe`, `happy`, `text`, and `clear`.

- [ ] **Step 4: Clean tree**

Run:

```bash
git status --short
```

Expected: no uncommitted changes.
