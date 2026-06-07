"""Probe configured JKS Agent, STT, and TTS contracts without printing secrets."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from typing import Optional, Sequence, TextIO
import wave

from jks.agent import build_agent_client
from jks.config import load_config
from jks.preflight import analyze_config
from jks.speech import build_speech_client
from tools.jks_probe_summary import summarize_agent_reply, summarize_preflight


def _write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 800)


def run_probe() -> dict[str, object]:
    config = load_config()
    preflight = analyze_config(config)
    summary: dict[str, object] = {
        "ok": False,
        "preflight": summarize_preflight(preflight),
        "checks": {},
        "errors": [],
    }
    if not preflight.get("ok"):
        return summary

    checks: dict[str, object] = {}
    errors: list[dict[str, str]] = []

    try:
        agent_reply = build_agent_client(config, timeout=60.0).probe_contract()
        checks["agent"] = summarize_agent_reply(
            agent_reply,
            mode=str(preflight.get("agent", {}).get("mode", "http")),
        )
    except Exception as exc:
        errors.append({"error": "agent", "message": str(exc)})

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_audio = temp_path / "contract-probe.wav"
            _write_silent_wav(input_audio)
            speech = build_speech_client(config, temp_path)
            stt_text = speech.transcribe(input_audio)
            tts_audio = speech.synthesize("JKS contract probe", config.tts_voice)
            checks["speech"] = {
                "mode": str(preflight.get("speech", {}).get("mode", "http")),
                "stt_text_length": len(stt_text),
                "tts_bytes": tts_audio.stat().st_size,
            }
    except Exception as exc:
        errors.append({"error": "speech", "message": str(exc)})

    summary["checks"] = checks
    summary["errors"] = errors
    summary["ok"] = not errors and "agent" in checks and "speech" in checks
    return summary


def main(argv: Optional[Sequence[str]] = None, stdout: TextIO = sys.stdout) -> int:
    try:
        summary = run_probe()
    except Exception as exc:
        summary = {
            "ok": False,
            "preflight": {},
            "checks": {},
            "errors": [{"error": "config", "message": str(exc)}],
        }
    stdout.write(json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
