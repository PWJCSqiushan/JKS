# JKS Voice Agent OLED Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python desktop controller that records voice, sends transcribed text to the remote Hermes / Gran agent, plays synthesized speech, and drives the verified SH1106 OLED expression device over serial.

**Architecture:** The app is a local controller with clear adapters for audio input, STT/TTS, remote agent transport, OLED display, and conversation orchestration. Hardware control remains local; the remote agent returns text and optional display intent that is validated before becoming OLED commands.

**Tech Stack:** Python 3.9+, Tkinter, unittest, `requests` for HTTP adapters, `sounddevice` + `soundfile` for microphone recording and playback, existing MicroPython OLED firmware, newline-delimited JSON serial protocol.

---

## File Structure

Create a Python package under `src/jks/` and keep existing hardware utilities.

- Create: `.gitignore` - excludes local secrets, virtual environments, build outputs, binary flash backups, and macOS metadata.
- Create: `pyproject.toml` - package metadata, dependencies, test command documentation.
- Create: `src/jks/__init__.py` - package marker.
- Create: `src/jks/__main__.py` - command entrypoint.
- Create: `src/jks/config.py` - environment configuration and validation.
- Create: `src/jks/display.py` - OLED serial controller and display intent validation.
- Create: `src/jks/expression.py` - cute/lively expression mapping and animation frame selection.
- Create: `src/jks/agent.py` - remote agent HTTP client and response parsing.
- Create: `src/jks/speech.py` - STT/TTS interfaces, fake clients, and generic HTTP adapters.
- Create: `src/jks/audio.py` - microphone recorder and audio playback wrapper.
- Create: `src/jks/orchestrator.py` - voice turn state machine.
- Create: `src/jks/app.py` - Tkinter desktop UI with one voice button and transcript area.
- Keep: `tools/oled_serial.py` - manual serial test CLI.
- Keep: `firmware/micropython/main.py` and `firmware/micropython/ssd1306_min.py` - verified ESP32-C3 SH1106 firmware.
- Test: `tests/test_config.py`
- Test: `tests/test_display_controller.py`
- Test: `tests/test_expression.py`
- Test: `tests/test_agent_client.py`
- Test: `tests/test_speech.py`
- Test: `tests/test_orchestrator.py`
- Keep existing: `tests/test_oled_serial_protocol.py`

## Task 1: Repository And Package Scaffold

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `src/jks/__init__.py`
- Create: `src/jks/__main__.py`
- Test: existing `tests/test_oled_serial_protocol.py`

- [ ] **Step 1: Initialize git repository**

Run:

```bash
git init
git status --short
```

Expected: `git status --short` lists the current untracked project files.

- [ ] **Step 2: Add project ignore rules**

Create `.gitignore`:

```gitignore
.DS_Store
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.superpowers/
*.log
.env
.env.*
!.env.example
hardware/*.bin
firmware/micropython/*.bin
firmware/oled-controller/.pio/
```

- [ ] **Step 3: Add Python package metadata**

Create `pyproject.toml`:

```toml
[project]
name = "jks"
version = "0.1.0"
description = "Local voice agent controller with OLED expressions"
requires-python = ">=3.9"
dependencies = [
  "requests>=2.32.0",
  "sounddevice>=0.5.0",
  "soundfile>=0.12.1"
]

[project.scripts]
jks = "jks.__main__:main"

[tool.uv]
package = true
```

- [ ] **Step 4: Add package entrypoint**

Create `src/jks/__init__.py`:

```python
"""JKS voice agent OLED controller."""
```

Create `src/jks/__main__.py`:

```python
from .app import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run existing tests**

Run:

```bash
uv run python -m unittest discover -s tests -v
```

Expected: existing OLED serial protocol tests pass.

- [ ] **Step 6: Commit scaffold**

Run:

```bash
git add .gitignore pyproject.toml src/jks/__init__.py src/jks/__main__.py
git commit -m "chore: initialize jks python package"
```

## Task 2: Configuration Loader

**Files:**
- Create: `src/jks/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_config.py`:

```python
import os
import unittest
from unittest.mock import patch

from jks.config import AppConfig, load_config


class ConfigTests(unittest.TestCase):
    def test_loads_defaults_for_oled(self):
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()

        self.assertEqual(config.oled_port, "/dev/cu.usbmodem5B900048301")
        self.assertEqual(config.oled_baud, 115200)

    def test_loads_remote_and_speech_settings(self):
        env = {
            "JKS_AGENT_ENDPOINT": "http://127.0.0.1:8787/chat",
            "JKS_AGENT_TOKEN": "secret-token",
            "JKS_STT_ENDPOINT": "http://127.0.0.1:8788/stt",
            "JKS_TTS_ENDPOINT": "http://127.0.0.1:8788/tts",
            "JKS_TTS_VOICE": "warm",
            "JKS_OLED_PORT": "/dev/cu.test",
            "JKS_OLED_BAUD": "57600",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertEqual(config.agent_endpoint, env["JKS_AGENT_ENDPOINT"])
        self.assertEqual(config.agent_token, "secret-token")
        self.assertEqual(config.stt_endpoint, env["JKS_STT_ENDPOINT"])
        self.assertEqual(config.tts_endpoint, env["JKS_TTS_ENDPOINT"])
        self.assertEqual(config.tts_voice, "warm")
        self.assertEqual(config.oled_port, "/dev/cu.test")
        self.assertEqual(config.oled_baud, 57600)

    def test_invalid_baud_fails_cleanly(self):
        with patch.dict(os.environ, {"JKS_OLED_BAUD": "fast"}, clear=True):
            with self.assertRaises(ValueError):
                load_config()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m unittest tests.test_config -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'jks.config'`.

- [ ] **Step 3: Implement config loader**

Create `src/jks/config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class AppConfig:
    agent_endpoint: str
    agent_token: str
    stt_endpoint: str
    tts_endpoint: str
    tts_voice: str
    oled_port: str
    oled_baud: int


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def load_config() -> AppConfig:
    return AppConfig(
        agent_endpoint=os.environ.get("JKS_AGENT_ENDPOINT", ""),
        agent_token=os.environ.get("JKS_AGENT_TOKEN", ""),
        stt_endpoint=os.environ.get("JKS_STT_ENDPOINT", ""),
        tts_endpoint=os.environ.get("JKS_TTS_ENDPOINT", ""),
        tts_voice=os.environ.get("JKS_TTS_VOICE", "default"),
        oled_port=os.environ.get("JKS_OLED_PORT", "/dev/cu.usbmodem5B900048301"),
        oled_baud=_int_env("JKS_OLED_BAUD", 115200),
    )
```

- [ ] **Step 4: Run config tests**

Run:

```bash
uv run python -m unittest tests.test_config -v
```

Expected: PASS.

- [ ] **Step 5: Commit config**

Run:

```bash
git add src/jks/config.py tests/test_config.py
git commit -m "feat: add environment configuration loader"
```

## Task 3: OLED Display Controller

**Files:**
- Create: `src/jks/display.py`
- Create: `tests/test_display_controller.py`

- [ ] **Step 1: Write failing display tests**

Create `tests/test_display_controller.py`:

```python
import io
import json
import unittest

from jks.display import DisplayController, DisplayIntent


class FakePort(io.BytesIO):
    def flush(self):
        self.flushed = True


class DisplayControllerTests(unittest.TestCase):
    def test_sends_whitelisted_emotion_with_short_text(self):
        port = FakePort()
        display = DisplayController(port)

        display.show(DisplayIntent(emotion="thinking", text="WAIT"))

        payload = json.loads(port.getvalue().decode("utf-8"))
        self.assertEqual(payload, {"cmd": "emotion", "name": "thinking", "text": "WAIT"})

    def test_invalid_emotion_falls_back_to_neutral(self):
        port = FakePort()
        display = DisplayController(port)

        display.show(DisplayIntent(emotion="run_shell", text="BAD"))

        payload = json.loads(port.getvalue().decode("utf-8"))
        self.assertEqual(payload["name"], "neutral")

    def test_text_is_clamped_for_oled(self):
        port = FakePort()
        display = DisplayController(port)

        display.show(DisplayIntent(emotion="happy", text="THIS IS TOO LONG FOR OLED"))

        payload = json.loads(port.getvalue().decode("utf-8"))
        self.assertEqual(payload["text"], "THIS IS TOO LO")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m unittest tests.test_display_controller -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'jks.display'`.

- [ ] **Step 3: Implement display controller**

Create `src/jks/display.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import termios
from typing import BinaryIO


ALLOWED_EMOTIONS = {
    "neutral", "happy", "thinking", "speaking", "listening",
    "surprised", "sleepy", "sad", "angry", "error",
}


@dataclass(frozen=True)
class DisplayIntent:
    emotion: str
    text: str = ""
    duration_ms: int = 1200
    intensity: str = "normal"


def clamp_oled_text(text: str, limit: int = 14) -> str:
    clean = "".join(ch for ch in str(text) if " " <= ch <= "~")
    return clean[:limit]


class DisplayController:
    def __init__(self, output: BinaryIO):
        self.output = output

    def show(self, intent: DisplayIntent) -> None:
        emotion = intent.emotion if intent.emotion in ALLOWED_EMOTIONS else "neutral"
        payload = {
            "cmd": "emotion",
            "name": emotion,
            "text": clamp_oled_text(intent.text or emotion.upper()),
        }
        self._write(payload)

    def clear(self) -> None:
        self._write({"cmd": "clear"})

    def probe(self) -> None:
        self._write({"cmd": "probe"})

    def _write(self, payload: dict[str, str]) -> None:
        frame = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        self.output.write(frame)
        self.output.flush()


def open_serial_output(path: str, baud: int) -> BinaryIO:
    fd = os.open(path, os.O_WRONLY | os.O_NOCTTY)
    attrs = termios.tcgetattr(fd)
    baud_const = getattr(termios, f"B{baud}", termios.B115200)
    attrs[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY | termios.ICRNL)
    attrs[1] &= ~termios.OPOST
    attrs[2] |= termios.CLOCAL | termios.CREAD | termios.CS8
    attrs[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG)
    attrs[4] = baud_const
    attrs[5] = baud_const
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return os.fdopen(fd, "wb", buffering=0)
```

- [ ] **Step 4: Run display tests**

Run:

```bash
uv run python -m unittest tests.test_display_controller -v
```

Expected: PASS.

- [ ] **Step 5: Run all tests**

Run:

```bash
uv run python -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] **Step 6: Commit display controller**

Run:

```bash
git add src/jks/display.py tests/test_display_controller.py
git commit -m "feat: add oled display controller"
```

## Task 4: Cute Expression System

**Files:**
- Create: `src/jks/expression.py`
- Create: `tests/test_expression.py`

- [ ] **Step 1: Write failing expression tests**

Create `tests/test_expression.py`:

```python
import unittest

from jks.expression import ExpressionEngine, TurnState


class ExpressionTests(unittest.TestCase):
    def test_state_maps_to_cute_expression(self):
        engine = ExpressionEngine()

        self.assertEqual(engine.intent_for_state(TurnState.LISTENING).emotion, "listening")
        self.assertEqual(engine.intent_for_state(TurnState.THINKING).text, "WAIT")
        self.assertEqual(engine.intent_for_state(TurnState.SPEAKING).text, "TALK")

    def test_agent_emotion_is_clamped(self):
        engine = ExpressionEngine()

        intent = engine.intent_from_agent({"emotion": "run_shell", "display_text": "BAD"})

        self.assertEqual(intent.emotion, "neutral")

    def test_speaking_animation_has_multiple_frames(self):
        engine = ExpressionEngine()

        frames = engine.frames_for("speaking")

        self.assertGreaterEqual(len(frames), 2)
        self.assertTrue(all(frame.emotion == "speaking" for frame in frames))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m unittest tests.test_expression -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'jks.expression'`.

- [ ] **Step 3: Implement expression engine**

Create `src/jks/expression.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .display import ALLOWED_EMOTIONS, DisplayIntent, clamp_oled_text


class TurnState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


STATE_INTENTS = {
    TurnState.IDLE: DisplayIntent("neutral", "READY"),
    TurnState.LISTENING: DisplayIntent("listening", "HEAR"),
    TurnState.TRANSCRIBING: DisplayIntent("thinking", "TEXT"),
    TurnState.THINKING: DisplayIntent("thinking", "WAIT"),
    TurnState.SPEAKING: DisplayIntent("speaking", "TALK"),
    TurnState.ERROR: DisplayIntent("error", "OOPS"),
}


@dataclass(frozen=True)
class ExpressionFrame:
    emotion: str
    text: str
    duration_ms: int


class ExpressionEngine:
    def intent_for_state(self, state: TurnState) -> DisplayIntent:
        return STATE_INTENTS[state]

    def intent_from_agent(self, payload: dict[str, object]) -> DisplayIntent:
        raw_emotion = str(payload.get("emotion", "neutral"))
        emotion = raw_emotion if raw_emotion in ALLOWED_EMOTIONS else "neutral"
        text = clamp_oled_text(str(payload.get("display_text", emotion.upper())))
        duration = self._clamp_duration(payload.get("duration_ms", 1200))
        intensity = str(payload.get("intensity", "normal"))
        if intensity not in {"soft", "normal", "high"}:
            intensity = "normal"
        return DisplayIntent(emotion=emotion, text=text, duration_ms=duration, intensity=intensity)

    def frames_for(self, emotion: str) -> list[ExpressionFrame]:
        if emotion == "speaking":
            return [
                ExpressionFrame("speaking", "TALK", 180),
                ExpressionFrame("speaking", "TALK", 180),
                ExpressionFrame("speaking", "TALK", 220),
            ]
        if emotion == "thinking":
            return [
                ExpressionFrame("thinking", "WAIT", 250),
                ExpressionFrame("thinking", "?", 250),
            ]
        if emotion == "happy":
            return [
                ExpressionFrame("happy", "DONE", 220),
                ExpressionFrame("happy", "^_^", 220),
            ]
        if emotion == "listening":
            return [
                ExpressionFrame("listening", "HEAR", 220),
                ExpressionFrame("listening", "...", 220),
            ]
        return [ExpressionFrame(emotion if emotion in ALLOWED_EMOTIONS else "neutral", "", 500)]

    def _clamp_duration(self, raw: object) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 1200
        return max(200, min(value, 5000))
```

- [ ] **Step 4: Run expression tests**

Run:

```bash
uv run python -m unittest tests.test_expression -v
```

Expected: PASS.

- [ ] **Step 5: Commit expression engine**

Run:

```bash
git add src/jks/expression.py tests/test_expression.py
git commit -m "feat: add cute oled expression engine"
```

## Task 5: Remote Agent Client

**Files:**
- Create: `src/jks/agent.py`
- Create: `tests/test_agent_client.py`

- [ ] **Step 1: Write failing agent tests**

Create `tests/test_agent_client.py`:

```python
import json
import unittest
from unittest.mock import patch

from jks.agent import AgentReply, parse_agent_reply, HttpAgentClient


class AgentClientTests(unittest.TestCase):
    def test_parse_structured_reply(self):
        reply = parse_agent_reply({"text": "你好", "emotion": "happy"})

        self.assertEqual(reply, AgentReply(text="你好", emotion="happy"))

    def test_parse_plain_text_reply(self):
        reply = parse_agent_reply("plain answer")

        self.assertEqual(reply.text, "plain answer")
        self.assertEqual(reply.emotion, "")

    def test_http_client_posts_message(self):
        class FakeResponse:
            status_code = 200
            content = json.dumps({"text": "ok", "emotion": "thinking"}).encode("utf-8")
            def raise_for_status(self):
                pass
            def json(self):
                return json.loads(self.content)

        with patch("jks.agent.requests.post", return_value=FakeResponse()) as post:
            client = HttpAgentClient("http://127.0.0.1:8787/chat", "token")
            reply = client.send_message("hello", "conv-1")

        self.assertEqual(reply.text, "ok")
        self.assertEqual(reply.emotion, "thinking")
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer token")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m unittest tests.test_agent_client -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'jks.agent'`.

- [ ] **Step 3: Implement agent client**

Create `src/jks/agent.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class AgentReply:
    text: str
    emotion: str = ""


def parse_agent_reply(payload: Any) -> AgentReply:
    if isinstance(payload, str):
        return AgentReply(text=payload)
    if isinstance(payload, dict):
        text = payload.get("text", payload.get("reply", ""))
        emotion = payload.get("emotion", "")
        return AgentReply(text=str(text), emotion=str(emotion))
    return AgentReply(text=str(payload))


class HttpAgentClient:
    def __init__(self, endpoint: str, token: str = "", timeout: float = 30.0):
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout

    def send_message(self, text: str, conversation_id: str) -> AgentReply:
        if not self.endpoint:
            raise RuntimeError("JKS_AGENT_ENDPOINT is not configured")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = requests.post(
            self.endpoint,
            json={"message": text, "conversation_id": conversation_id},
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return parse_agent_reply(payload)
```

- [ ] **Step 4: Run agent tests**

Run:

```bash
uv run python -m unittest tests.test_agent_client -v
```

Expected: PASS.

- [ ] **Step 5: Commit agent client**

Run:

```bash
git add src/jks/agent.py tests/test_agent_client.py
git commit -m "feat: add remote agent client"
```

## Task 6: Speech Client Abstractions

**Files:**
- Create: `src/jks/speech.py`
- Create: `tests/test_speech.py`

- [ ] **Step 1: Write failing speech tests**

Create `tests/test_speech.py`:

```python
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jks.speech import FakeSpeechClient, HttpSpeechClient


class SpeechTests(unittest.TestCase):
    def test_fake_speech_client_is_deterministic(self):
        client = FakeSpeechClient(text="hello agent")

        self.assertEqual(client.transcribe(Path("input.wav")), "hello agent")
        output = client.synthesize("reply", "warm")

        self.assertTrue(output.exists())
        self.assertGreater(output.stat().st_size, 0)

    def test_http_tts_writes_audio_file(self):
        class FakeResponse:
            content = b"audio-bytes"
            def raise_for_status(self):
                pass
            def json(self):
                return {"text": "ignored"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("jks.speech.requests.post", return_value=FakeResponse()):
                client = HttpSpeechClient(
                    stt_endpoint="https://speech.test/stt",
                    tts_endpoint="https://speech.test/tts",
                    output_dir=Path(temp_dir),
                )
                output = client.synthesize("hello", "warm")

        self.assertEqual(output.name, "tts-output.wav")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m unittest tests.test_speech -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'jks.speech'`.

- [ ] **Step 3: Implement speech clients**

Create `src/jks/speech.py`:

```python
from __future__ import annotations

from pathlib import Path
import tempfile

import requests


class FakeSpeechClient:
    def __init__(self, text: str = "hello"):
        self.text = text
        self.output_dir = Path(tempfile.gettempdir())

    def transcribe(self, audio_path: Path) -> str:
        return self.text

    def synthesize(self, text: str, voice: str) -> Path:
        output = self.output_dir / "jks-fake-tts.wav"
        output.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
        return output


class HttpSpeechClient:
    def __init__(self, stt_endpoint: str, tts_endpoint: str, output_dir: Path):
        self.stt_endpoint = stt_endpoint
        self.tts_endpoint = tts_endpoint
        self.output_dir = output_dir

    def transcribe(self, audio_path: Path) -> str:
        if not self.stt_endpoint:
            raise RuntimeError("JKS_STT_ENDPOINT is not configured")
        with audio_path.open("rb") as audio:
            response = requests.post(self.stt_endpoint, files={"audio": audio}, timeout=60)
        response.raise_for_status()
        payload = response.json()
        return str(payload["text"])

    def synthesize(self, text: str, voice: str) -> Path:
        if not self.tts_endpoint:
            raise RuntimeError("JKS_TTS_ENDPOINT is not configured")
        response = requests.post(
            self.tts_endpoint,
            json={"text": text, "voice": voice},
            timeout=60,
        )
        response.raise_for_status()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / "tts-output.wav"
        output.write_bytes(response.content)
        return output
```

- [ ] **Step 4: Run speech tests**

Run:

```bash
uv run python -m unittest tests.test_speech -v
```

Expected: PASS.

- [ ] **Step 5: Commit speech clients**

Run:

```bash
git add src/jks/speech.py tests/test_speech.py
git commit -m "feat: add speech client abstractions"
```

## Task 7: Audio Recorder And Playback

**Files:**
- Create: `src/jks/audio.py`

- [ ] **Step 1: Add audio wrapper**

Create `src/jks/audio.py`:

```python
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import time


class AudioRecorder:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def record_fixed_seconds(self, seconds: float = 4.0) -> Path:
        import sounddevice as sd
        import soundfile as sf

        frames = int(self.sample_rate * seconds)
        data = sd.rec(frames, samplerate=self.sample_rate, channels=1, dtype="float32")
        sd.wait()
        output = Path(tempfile.gettempdir()) / f"jks-recording-{int(time.time() * 1000)}.wav"
        sf.write(output, data, self.sample_rate)
        return output


class AudioPlayer:
    def play(self, audio_path: Path) -> None:
        subprocess.run(["afplay", str(audio_path)], check=True)
```

- [ ] **Step 2: Run import smoke test**

Run:

```bash
uv run python - <<'PY'
from jks.audio import AudioRecorder, AudioPlayer
print(AudioRecorder().sample_rate)
print(AudioPlayer.__name__)
PY
```

Expected:

```text
16000
AudioPlayer
```

- [ ] **Step 3: Commit audio wrapper**

Run:

```bash
git add src/jks/audio.py
git commit -m "feat: add local audio recorder and player"
```

## Task 8: Conversation Orchestrator

**Files:**
- Create: `src/jks/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing orchestrator tests**

Create `tests/test_orchestrator.py`:

```python
import tempfile
import unittest
from pathlib import Path

from jks.agent import AgentReply
from jks.orchestrator import ConversationOrchestrator


class FakeRecorder:
    def record_fixed_seconds(self, seconds=4.0):
        path = Path(tempfile.gettempdir()) / "jks-test.wav"
        path.write_bytes(b"audio")
        return path


class FakeSpeech:
    def transcribe(self, audio_path):
        return "hello"
    def synthesize(self, text, voice):
        path = Path(tempfile.gettempdir()) / "reply.wav"
        path.write_bytes(b"audio")
        return path


class FakeAgent:
    def send_message(self, text, conversation_id):
        return AgentReply(text="reply", emotion="happy")


class FakeDisplay:
    def __init__(self):
        self.emotions = []
    def show(self, intent):
        self.emotions.append(intent.emotion)


class FakePlayer:
    def __init__(self):
        self.played = []
    def play(self, audio_path):
        self.played.append(audio_path)


class OrchestratorTests(unittest.TestCase):
    def test_voice_turn_updates_display_and_returns_reply(self):
        display = FakeDisplay()
        player = FakePlayer()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(),
            agent=FakeAgent(),
            display=display,
            player=player,
            voice="warm",
        )

        result = orchestrator.run_voice_turn()

        self.assertEqual(result.user_text, "hello")
        self.assertEqual(result.agent_text, "reply")
        self.assertIn("listening", display.emotions)
        self.assertIn("thinking", display.emotions)
        self.assertIn("speaking", display.emotions)
        self.assertEqual(display.emotions[-1], "happy")
        self.assertEqual(len(player.played), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m unittest tests.test_orchestrator -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'jks.orchestrator'`.

- [ ] **Step 3: Implement orchestrator**

Create `src/jks/orchestrator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .agent import AgentReply
from .expression import ExpressionEngine, TurnState


@dataclass(frozen=True)
class TurnResult:
    user_text: str
    agent_text: str
    emotion: str


class ConversationOrchestrator:
    def __init__(self, recorder, speech, agent, display, player, voice: str):
        self.recorder = recorder
        self.speech = speech
        self.agent = agent
        self.display = display
        self.player = player
        self.voice = voice
        self.expression = ExpressionEngine()
        self.conversation_id = str(uuid4())

    def _show_state(self, state: TurnState) -> None:
        self.display.show(self.expression.intent_for_state(state))

    def run_voice_turn(self) -> TurnResult:
        try:
            self._show_state(TurnState.LISTENING)
            audio_path = self.recorder.record_fixed_seconds()
            self._show_state(TurnState.TRANSCRIBING)
            user_text = self.speech.transcribe(audio_path)
            self._show_state(TurnState.THINKING)
            reply: AgentReply = self.agent.send_message(user_text, self.conversation_id)
            self._show_state(TurnState.SPEAKING)
            audio_reply = self.speech.synthesize(reply.text, self.voice)
            self.player.play(audio_reply)
            final_emotion = reply.emotion or "happy"
            self.display.show(self.expression.intent_from_agent({"emotion": final_emotion, "display_text": "DONE"}))
            return TurnResult(user_text=user_text, agent_text=reply.text, emotion=final_emotion)
        except Exception:
            self._show_state(TurnState.ERROR)
            raise
```

- [ ] **Step 4: Run orchestrator tests**

Run:

```bash
uv run python -m unittest tests.test_orchestrator -v
```

Expected: PASS.

- [ ] **Step 5: Run all tests**

Run:

```bash
uv run python -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] **Step 6: Commit orchestrator**

Run:

```bash
git add src/jks/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add voice conversation orchestrator"
```

## Task 9: Tkinter Desktop Controller

**Files:**
- Create: `src/jks/app.py`
- Modify: `src/jks/__main__.py`

- [ ] **Step 1: Add desktop app wiring**

Create `src/jks/app.py`:

```python
from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import tkinter as tk
from tkinter import ttk

from .agent import HttpAgentClient
from .audio import AudioPlayer, AudioRecorder
from .config import load_config
from .display import DisplayController, open_serial_output
from .orchestrator import ConversationOrchestrator
from .speech import FakeSpeechClient, HttpSpeechClient


class JksApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("JKS Voice Agent")
        self.status = tk.StringVar(value="Ready")
        self.transcript = tk.StringVar(value="")
        self.button = ttk.Button(root, text="Speak", command=self.start_turn)
        self.button.pack(padx=16, pady=12)
        ttk.Label(root, textvariable=self.status).pack(padx=16, pady=4)
        ttk.Label(root, textvariable=self.transcript, wraplength=420).pack(padx=16, pady=12)
        self.orchestrator = self._build_orchestrator()

    def _build_orchestrator(self) -> ConversationOrchestrator:
        config = load_config()
        try:
            serial_output = open_serial_output(config.oled_port, config.oled_baud)
            display = DisplayController(serial_output)
        except Exception:
            display = DisplayController(open(Path(tempfile.gettempdir()) / "jks-oled.log", "ab", buffering=0))

        if config.stt_endpoint and config.tts_endpoint:
            speech = HttpSpeechClient(config.stt_endpoint, config.tts_endpoint, Path(tempfile.gettempdir()))
        else:
            speech = FakeSpeechClient("hello agent")

        return ConversationOrchestrator(
            recorder=AudioRecorder(),
            speech=speech,
            agent=HttpAgentClient(config.agent_endpoint, config.agent_token),
            display=display,
            player=AudioPlayer(),
            voice=config.tts_voice,
        )

    def start_turn(self) -> None:
        self.button.configure(state="disabled")
        self.status.set("Listening")
        thread = threading.Thread(target=self._run_turn, daemon=True)
        thread.start()

    def _run_turn(self) -> None:
        try:
            result = self.orchestrator.run_voice_turn()
            self.root.after(0, lambda: self._finish_success(result.user_text, result.agent_text))
        except Exception as exc:
            self.root.after(0, lambda: self._finish_error(exc))

    def _finish_success(self, user_text: str, agent_text: str) -> None:
        self.status.set("Ready")
        self.transcript.set(f"You: {user_text}\nAgent: {agent_text}")
        self.button.configure(state="normal")

    def _finish_error(self, exc: Exception) -> None:
        self.status.set(f"Error: {exc}")
        self.button.configure(state="normal")


def main() -> int:
    root = tk.Tk()
    JksApp(root)
    root.mainloop()
    return 0
```

Ensure `src/jks/__main__.py` remains:

```python
from .app import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run GUI import smoke**

Run:

```bash
uv run python - <<'PY'
from jks.app import JksApp, main
print(JksApp.__name__)
print(callable(main))
PY
```

Expected:

```text
JksApp
True
```

- [ ] **Step 3: Commit desktop app**

Run:

```bash
git add src/jks/app.py src/jks/__main__.py
git commit -m "feat: add tkinter voice controller"
```

## Task 10: Local Demo And Hardware Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-06-05-jks-voice-agent-oled-design.md` only if command names changed during implementation.

- [ ] **Step 1: Verify tests**

Run:

```bash
uv run python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Verify OLED manual commands**

Run:

```bash
python3 -m tools.oled_serial --port /dev/cu.usbmodem5B900048301 emotion thinking
python3 -m tools.oled_serial --port /dev/cu.usbmodem5B900048301 text "JKS READY"
python3 -m tools.oled_serial --port /dev/cu.usbmodem5B900048301 clear
```

Expected: OLED changes expression/text and clears without random pixel noise.

- [ ] **Step 3: Verify MicroPython firmware still runs**

Run:

```bash
/tmp/jks-pio/bin/mpremote connect /dev/cu.usbmodem5B900048301 exec "import sys; print(sys.implementation)"
```

Expected: output includes `ESP32_GENERIC_C3`.

- [ ] **Step 4: Run app with fake speech**

Run:

```bash
JKS_AGENT_ENDPOINT="" uv run python -m jks
```

Expected: app window opens. Because no agent endpoint is configured, clicking Speak reaches an error state after fake transcription and displays OLED error. This verifies UI threading and local display fallback without calling external services.

- [ ] **Step 5: Run app with real services**

Start local adapters or tunnels outside this repository so the following loopback URLs serve the contracts defined by `HttpAgentClient` and `HttpSpeechClient`. Then set environment variables in the current shell:

```bash
export JKS_AGENT_ENDPOINT="http://127.0.0.1:8787/chat"
export JKS_AGENT_TOKEN=""
export JKS_STT_ENDPOINT="http://127.0.0.1:8788/stt"
export JKS_TTS_ENDPOINT="http://127.0.0.1:8788/tts"
export JKS_TTS_VOICE="warm"
export JKS_OLED_PORT="/dev/cu.usbmodem5B900048301"
export JKS_OLED_BAUD="115200"
uv run python -m jks
```

Expected:

- A click records local microphone audio.
- STT returns user text.
- Agent returns reply text.
- TTS returns playable audio.
- Audio plays locally.
- OLED transitions through listening, thinking, speaking, and happy/error.

- [ ] **Step 6: Commit verification doc updates**

If the implementation changed commands or environment variable names, update the spec and commit:

```bash
git add docs/superpowers/specs/2026-06-05-jks-voice-agent-oled-design.md
git commit -m "docs: align design spec with implementation"
```

If no doc changes are needed, run:

```bash
git status --short
```

Expected: no uncommitted source changes from implementation tasks.

## Notes For Implementers

- Keep server credentials out of committed files.
- Keep `hardware/*.bin` ignored; the existing flash backup is for local recovery.
- The working OLED is SH1106, not SSD1306.
- The verified OLED pins are `SDA=GPIO4`, `SCL=GPIO5`, address `0x3C`.
- If the serial port changes after reconnect, update `JKS_OLED_PORT` rather than editing source code.
- Do not let remote agent output bypass `ExpressionEngine` or `DisplayController`.
- The first real remote-agent integration should adapt to the existing Hermes / Gran endpoint shape by editing only `src/jks/agent.py` and its tests.
