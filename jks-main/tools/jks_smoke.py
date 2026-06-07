"""Run a no-GUI local contract smoke for the JKS voice-agent path."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from typing import Optional, Sequence, TextIO

from jks.agent import HttpAgentClient
from jks.audio import AudioPlayer
from jks.display import DisplayIntent
from jks.orchestrator import ConversationOrchestrator
from jks.speech import HttpSpeechClient
from tools.jks_fake_services import start_fake_services


class FakeRecorder:
    def __init__(self, audio_path: Path):
        self.audio_path = audio_path
        self.recordings = 0

    def record_fixed_seconds(self, seconds: float = 4.0) -> Path:
        self.recordings += 1
        self.audio_path.write_bytes(b"fake-audio")
        return self.audio_path


class NoOpPlayer(AudioPlayer):
    def __init__(self):
        self.played = []

    def play(self, audio_path: Path) -> None:
        self.played.append(Path(audio_path))


class CapturedDisplay:
    def __init__(self):
        self.intents = []

    def show(self, intent: DisplayIntent) -> None:
        self.intents.append(intent)


def run_smoke() -> dict[str, object]:
    server = start_fake_services()
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            recorder = FakeRecorder(output_dir / "input.wav")
            player = NoOpPlayer()
            display = CapturedDisplay()
            speech = HttpSpeechClient(
                stt_endpoint=server.base_url + "/stt",
                tts_endpoint=server.base_url + "/tts",
                output_dir=output_dir,
            )
            agent = HttpAgentClient(
                server.base_url + "/v1/chat/completions",
                timeout=5.0,
                model="gran-agent",
            )
            orchestrator = ConversationOrchestrator(
                recorder=recorder,
                speech=speech,
                agent=agent,
                display=display,
                player=player,
                voice="warm",
            )

            result = orchestrator.run_voice_turn()
            return {
                "ok": True,
                "user_text": result.user_text,
                "agent_text": result.agent_text,
                "emotion": result.emotion,
                "display_emotions": [intent.emotion for intent in display.intents],
                "display_texts": [intent.text for intent in display.intents],
                "played_count": len(player.played),
                "server_events": [event["kind"] for event in server.events],
                "server_chat_formats": [
                    str(event.get("format", ""))
                    for event in server.events
                    if event.get("kind") == "chat"
                ],
                "recordings": recorder.recordings,
            }
    finally:
        server.stop()


def main(argv: Optional[Sequence[str]] = None, stdout: TextIO = sys.stdout) -> int:
    try:
        summary = run_smoke()
    except Exception as exc:
        summary = {"ok": False, "errors": [{"error": "smoke", "message": str(exc)}]}
    stdout.write(json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
