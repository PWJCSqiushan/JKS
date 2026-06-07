# JKS Integration Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a secret-free integration readiness layer so the project can verify real-service configuration before connecting Hermes / Gran, STT, and TTS endpoints.

**Architecture:** Keep real secrets and remote access outside the repository. A new `jks.preflight` module classifies the current environment into agent, speech, and OLED readiness modes, redacts sensitive values, and reports missing or partial configuration. A small CLI prints compact JSON for shell use, and `.env.example` documents the required variables without secret values.

**Tech Stack:** Python 3.9+, dataclasses, `unittest`, existing `jks.config.AppConfig`, standard-library JSON CLI under `tools/`.

---

## File Structure

- Create: `src/jks/preflight.py` - pure config readiness analysis and redaction helpers.
- Create: `tests/test_preflight.py` - unit tests for readiness modes, missing fields, partial speech config, and token redaction.
- Create: `tools/jks_config_check.py` - CLI that loads environment config and prints compact JSON.
- Create: `tests/test_config_check.py` - CLI tests using patched environments and stdout.
- Create: `.env.example` - secret-free runnable configuration template.
- Create: `tests/test_env_example.py` - verifies template has required keys and no obvious committed secret values.

## Task 1: Preflight Readiness Module

**Files:**
- Create: `src/jks/preflight.py`
- Create: `tests/test_preflight.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_preflight.py` with tests covering:

```python
import unittest

from jks.config import AppConfig
from jks.preflight import analyze_config, redact_secret


def config(**overrides):
    data = {
        "agent_host": "",
        "agent_user": "",
        "agent_auth_method": "",
        "agent_endpoint": "",
        "agent_token": "",
        "stt_provider": "",
        "stt_endpoint": "",
        "tts_provider": "",
        "tts_endpoint": "",
        "tts_voice": "default",
        "oled_port": "/dev/cu.usbmodem5B900048301",
        "oled_baud": 115200,
    }
    data.update(overrides)
    return AppConfig(**data)


class PreflightTests(unittest.TestCase):
    def test_missing_agent_is_not_ready_but_fake_speech_is_allowed(self):
        summary = analyze_config(config())

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["agent"]["mode"], "missing")
        self.assertEqual(summary["speech"]["mode"], "fake")
        self.assertEqual(summary["oled"]["mode"], "serial")
        self.assertIn("JKS_AGENT_ENDPOINT", summary["missing"])

    def test_http_agent_and_http_speech_are_ready(self):
        summary = analyze_config(
            config(
                agent_endpoint="http://127.0.0.1:8787/chat",
                agent_token="secret-token",
                stt_provider="http",
                stt_endpoint="http://127.0.0.1:8788/stt",
                tts_provider="http",
                tts_endpoint="http://127.0.0.1:8788/tts",
                tts_voice="warm",
            )
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["agent"]["mode"], "http")
        self.assertEqual(summary["agent"]["token"], "<redacted:12>")
        self.assertEqual(summary["speech"]["mode"], "http")
        self.assertEqual(summary["speech"]["voice"], "warm")

    def test_partial_speech_config_reports_missing_pair(self):
        summary = analyze_config(config(agent_endpoint="http://agent.local/chat", stt_endpoint="http://stt.local"))

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["speech"]["mode"], "partial")
        self.assertIn("JKS_TTS_ENDPOINT", summary["missing"])
        self.assertIn("JKS_STT_ENDPOINT and JKS_TTS_ENDPOINT must be configured together", summary["warnings"])

    def test_redact_secret_never_returns_secret_value(self):
        self.assertEqual(redact_secret(""), "")
        self.assertEqual(redact_secret("abc"), "<redacted:3>")
        self.assertEqual(redact_secret("very-secret-token"), "<redacted:17>")
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run python -m unittest tests.test_preflight -v
```

Expected: fails because `jks.preflight` does not exist.

- [ ] **Step 3: Implement preflight module**

Create `src/jks/preflight.py` with:

```python
from __future__ import annotations

from .config import AppConfig


def redact_secret(value: str) -> str:
    if not value:
        return ""
    return f"<redacted:{len(value)}>"


def analyze_config(config: AppConfig) -> dict[str, object]:
    missing: list[str] = []
    warnings: list[str] = []

    if config.agent_endpoint:
        agent_mode = "http"
    else:
        agent_mode = "missing"
        missing.append("JKS_AGENT_ENDPOINT")

    has_stt = bool(config.stt_endpoint)
    has_tts = bool(config.tts_endpoint)
    if has_stt and has_tts:
        speech_mode = "http"
    elif not has_stt and not has_tts:
        speech_mode = "fake"
    else:
        speech_mode = "partial"
        if not has_stt:
            missing.append("JKS_STT_ENDPOINT")
        if not has_tts:
            missing.append("JKS_TTS_ENDPOINT")
        warnings.append("JKS_STT_ENDPOINT and JKS_TTS_ENDPOINT must be configured together")

    oled_mode = "serial" if config.oled_port else "disabled"
    if not config.oled_port:
        missing.append("JKS_OLED_PORT")

    ok = agent_mode == "http" and speech_mode in {"http", "fake"} and oled_mode == "serial"
    return {
        "ok": ok,
        "agent": {
            "mode": agent_mode,
            "endpoint": config.agent_endpoint,
            "host": config.agent_host,
            "user": config.agent_user,
            "auth_method": config.agent_auth_method,
            "token": redact_secret(config.agent_token),
        },
        "speech": {
            "mode": speech_mode,
            "stt_provider": config.stt_provider,
            "stt_endpoint": config.stt_endpoint,
            "tts_provider": config.tts_provider,
            "tts_endpoint": config.tts_endpoint,
            "voice": config.tts_voice,
        },
        "oled": {
            "mode": oled_mode,
            "port": config.oled_port,
            "baud": config.oled_baud,
        },
        "missing": missing,
        "warnings": warnings,
    }
```

- [ ] **Step 4: Run test to verify GREEN**

Run:

```bash
uv run python -m unittest tests.test_preflight -v
```

Expected: all preflight tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/jks/preflight.py tests/test_preflight.py
git commit -m "feat: add config preflight analysis"
```

## Task 2: Config Check CLI

**Files:**
- Create: `tools/jks_config_check.py`
- Create: `tests/test_config_check.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_config_check.py`:

```python
import io
import json
import os
import unittest
from unittest.mock import patch

from tools.jks_config_check import main


class ConfigCheckCliTests(unittest.TestCase):
    def test_main_prints_compact_redacted_json(self):
        env = {
            "JKS_AGENT_ENDPOINT": "http://127.0.0.1:8787/chat",
            "JKS_AGENT_TOKEN": "secret-token",
            "JKS_STT_ENDPOINT": "http://127.0.0.1:8788/stt",
            "JKS_TTS_ENDPOINT": "http://127.0.0.1:8788/tts",
        }
        output = io.StringIO()

        with patch.dict(os.environ, env, clear=True):
            exit_code = main([], stdout=output)

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertNotIn("secret-token", text)
        self.assertNotIn(": ", text)
        payload = json.loads(text)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["agent"]["token"], "<redacted:12>")

    def test_main_returns_one_when_required_agent_endpoint_is_missing(self):
        output = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            exit_code = main([], stdout=output)

        self.assertEqual(exit_code, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("JKS_AGENT_ENDPOINT", payload["missing"])
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run python -m unittest tests.test_config_check -v
```

Expected: fails because `tools.jks_config_check` does not exist.

- [ ] **Step 3: Implement CLI**

Create `tools/jks_config_check.py`:

```python
from __future__ import annotations

import json
import sys
from typing import Optional, Sequence, TextIO

from jks.config import load_config
from jks.preflight import analyze_config


def main(argv: Optional[Sequence[str]] = None, stdout: TextIO = sys.stdout) -> int:
    summary = analyze_config(load_config())
    stdout.write(json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify GREEN**

Run:

```bash
uv run python -m unittest tests.test_config_check -v
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add tools/jks_config_check.py tests/test_config_check.py
git commit -m "feat: add config check cli"
```

## Task 3: Secret-Free Env Example

**Files:**
- Create: `.env.example`
- Create: `tests/test_env_example.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_env_example.py`:

```python
from pathlib import Path
import unittest


class EnvExampleTests(unittest.TestCase):
    def test_env_example_documents_required_keys_without_real_secrets(self):
        text = Path(".env.example").read_text()

        for key in (
            "JKS_AGENT_ENDPOINT",
            "JKS_AGENT_TOKEN",
            "JKS_STT_ENDPOINT",
            "JKS_TTS_ENDPOINT",
            "JKS_TTS_VOICE",
            "JKS_OLED_PORT",
            "JKS_OLED_BAUD",
        ):
            self.assertIn(key + "=", text)

        self.assertNotIn("Bearer ", text)
        self.assertNotIn("root", text)
        self.assertNotIn("Qq", text)
        self.assertIn("replace-with", text)
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run python -m unittest tests.test_env_example -v
```

Expected: fails because `.env.example` does not exist.

- [ ] **Step 3: Add env template**

Create `.env.example`:

```dotenv
# Copy to .env and fill values locally. Do not commit .env.
JKS_AGENT_HOST="replace-with-agent-host"
JKS_AGENT_USER="replace-with-agent-user"
JKS_AGENT_AUTH_METHOD="token"
JKS_AGENT_ENDPOINT="http://127.0.0.1:8787/chat"
JKS_AGENT_TOKEN="replace-with-agent-token"

JKS_STT_PROVIDER="http"
JKS_STT_ENDPOINT="http://127.0.0.1:8788/stt"
JKS_TTS_PROVIDER="http"
JKS_TTS_ENDPOINT="http://127.0.0.1:8788/tts"
JKS_TTS_VOICE="warm"

JKS_OLED_PORT="/dev/cu.usbmodem5B900048301"
JKS_OLED_BAUD="115200"
```

- [ ] **Step 4: Run test to verify GREEN**

Run:

```bash
uv run python -m unittest tests.test_env_example -v
```

Expected: env template test passes.

- [ ] **Step 5: Commit**

Run:

```bash
git add .env.example tests/test_env_example.py
git commit -m "docs: add secret-free env example"
```

## Task 4: Final Verification

**Files:**
- No new source files required.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run python -m unittest tests.test_preflight tests.test_config_check tests.test_env_example -v
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full tests**

Run:

```bash
uv run python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Run config check CLI**

Run:

```bash
JKS_AGENT_ENDPOINT=http://127.0.0.1:8787/chat \
JKS_AGENT_TOKEN=secret-token \
JKS_STT_ENDPOINT=http://127.0.0.1:8788/stt \
JKS_TTS_ENDPOINT=http://127.0.0.1:8788/tts \
uv run python -m tools.jks_config_check
```

Expected: output is compact JSON, `ok` is true, and the literal `secret-token` is not printed.

- [ ] **Step 4: Run existing smoke checks**

Run:

```bash
uv run python -m tools.jks_smoke
uv run python -m tools.oled_smoke --port /dev/cu.usbmodem5B900048301
```

Expected: both commands print JSON with `"ok":true`. If the OLED is not connected, record the serial failure explicitly instead of claiming hardware verification.

- [ ] **Step 5: Clean tree**

Run:

```bash
git status --short
```

Expected: no uncommitted changes after the final commit.
