import io
import json
import os
import tempfile
import unittest
import wave
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tools.jks_fake_services import start_fake_services
from tools.jks_turn_probe import main


@contextmanager
def clean_cwd():
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            yield
        finally:
            os.chdir(old_cwd)


def write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 400)


class FakeDisplayPort:
    def __init__(self, ack_lines=None):
        self.ack_lines = list(ack_lines or [])
        self.frames = []
        self.flushed = False
        self.closed = False

    def write(self, data):
        self.frames.append(json.loads(data.decode("utf-8")))
        return len(data)

    def flush(self):
        self.flushed = True

    def readline(self):
        if not self.ack_lines:
            return b""
        return self.ack_lines.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True
        return False


class TurnProbeCliTests(unittest.TestCase):
    def test_missing_audio_argument_returns_error_without_config_or_network_probe(self):
        stdout = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, {}, clear=True):
            exit_code = main([], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["checks"], {})
        self.assertEqual(payload["errors"], [{"error": "audio", "message": "--audio is required"}])

    def test_missing_config_returns_preflight_without_network_probe(self):
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "input.wav"
            write_silent_wav(audio_path)

            with clean_cwd(), patch.dict(os.environ, {}, clear=True):
                with patch("jks.speech.requests.post") as speech_post:
                    with patch("jks.agent.requests.post") as agent_post:
                        exit_code = main(["--audio", str(audio_path)], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["checks"], {})
        self.assertEqual(payload["server_events"], [])
        self.assertIn("JKS_AGENT_ENDPOINT", payload["preflight"]["missing"])
        speech_post.assert_not_called()
        agent_post.assert_not_called()

    def test_probe_runs_stt_agent_tts_in_turn_order_and_redacts_secrets(self):
        server = start_fake_services()
        stdout = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path = Path(temp_dir) / "input.wav"
                write_silent_wav(audio_path)
                env = {
                    "JKS_AGENT_ENDPOINT": server.base_url + "/v1/chat/completions?token=secret",
                    "JKS_AGENT_TOKEN": "secret-token",
                    "JKS_AGENT_MODEL": "gran-agent",
                    "JKS_STT_ENDPOINT": server.base_url + "/stt?api_key=secret",
                    "JKS_TTS_ENDPOINT": server.base_url + "/tts?api_key=secret",
                    "JKS_TTS_VOICE": "warm",
                }

                with clean_cwd(), patch.dict(os.environ, env, clear=True):
                    exit_code = main(["--audio", str(audio_path)], stdout=stdout)
        finally:
            server.stop()

        text = stdout.getvalue()
        payload = json.loads(text)
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertNotIn("secret-token", text)
        self.assertNotIn("api_key=secret", text)
        self.assertNotIn("token=secret", text)
        self.assertNotIn(": ", text)
        self.assertNotIn("hello agent", text)
        self.assertNotIn("Fake reply to: hello agent", text)
        self.assertEqual(payload["checks"]["stt"], {"text_length": len("hello agent")})
        self.assertEqual(payload["checks"]["agent"]["text_length"], len("Fake reply to: hello agent"))
        self.assertEqual(payload["checks"]["agent"]["emotion"], "happy")
        self.assertTrue(payload["checks"]["agent"]["display_present"])
        self.assertEqual(payload["checks"]["agent"]["display_text_length"], len("DONE"))
        self.assertEqual(payload["checks"]["agent"]["duration_ms"], 1200)
        self.assertEqual(payload["checks"]["agent"]["intensity"], "normal")
        self.assertGreater(payload["checks"]["tts"]["bytes"], 0)
        self.assertEqual(payload["checks"]["tts"]["voice"], "warm")
        self.assertEqual(payload["server_events"], ["stt", "chat", "tts"])
        self.assertEqual([event["kind"] for event in server.events], ["stt", "chat", "tts"])
        self.assertEqual(server.events[1]["format"], "openai")
        self.assertEqual(server.events[1]["model"], "gran-agent")

    def test_verbose_probe_includes_transcripts_for_local_debugging(self):
        server = start_fake_services()
        stdout = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path = Path(temp_dir) / "input.wav"
                write_silent_wav(audio_path)
                env = {
                    "JKS_AGENT_ENDPOINT": server.base_url + "/chat",
                    "JKS_STT_ENDPOINT": server.base_url + "/stt",
                    "JKS_TTS_ENDPOINT": server.base_url + "/tts",
                }

                with clean_cwd(), patch.dict(os.environ, env, clear=True):
                    exit_code = main(["--audio", str(audio_path), "--verbose"], stdout=stdout)
        finally:
            server.stop()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["checks"]["stt"]["text"], "hello agent")
        self.assertEqual(payload["checks"]["agent"]["text"], "Fake reply to: hello agent")

    def test_stt_failure_reports_stt_stage(self):
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "input.wav"
            write_silent_wav(audio_path)
            env = {
                "JKS_AGENT_ENDPOINT": "http://agent.local/chat",
                "JKS_STT_ENDPOINT": "http://speech.local/stt",
                "JKS_TTS_ENDPOINT": "http://speech.local/tts",
            }

            with clean_cwd(), patch.dict(os.environ, env, clear=True):
                with patch("jks.speech.requests.post", side_effect=OSError("offline")):
                    exit_code = main(["--audio", str(audio_path)], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["server_events"], [])
        self.assertEqual(payload["errors"][0]["error"], "stt")

    def test_play_flag_plays_generated_tts_audio(self):
        server = start_fake_services()
        stdout = io.StringIO()
        played = []
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path = Path(temp_dir) / "input.wav"
                write_silent_wav(audio_path)
                env = {
                    "JKS_AGENT_ENDPOINT": server.base_url + "/chat",
                    "JKS_STT_ENDPOINT": server.base_url + "/stt",
                    "JKS_TTS_ENDPOINT": server.base_url + "/tts",
                }

                with clean_cwd(), patch.dict(os.environ, env, clear=True):
                    with patch("jks.audio.AudioPlayer.play", side_effect=lambda path: played.append(Path(path))):
                        exit_code = main(["--audio", str(audio_path), "--play"], stdout=stdout)
        finally:
            server.stop()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["checks"]["playback"], {"played": True})
        self.assertEqual(len(played), 1)
        self.assertTrue(played[0].exists())

    def test_display_flag_writes_turn_states_and_final_intent_with_required_acks(self):
        server = start_fake_services()
        stdout = io.StringIO()
        port = FakeDisplayPort(
            [
                b'{"status":"ok","detail":"listening"}\n',
                b'{"status":"ok","detail":"thinking"}\n',
                b'{"status":"ok","detail":"thinking"}\n',
                b'{"status":"ok","detail":"speaking"}\n',
                b'{"status":"ok","detail":"happy"}\n',
            ]
        )
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path = Path(temp_dir) / "input.wav"
                write_silent_wav(audio_path)
                env = {
                    "JKS_AGENT_ENDPOINT": server.base_url + "/chat",
                    "JKS_STT_ENDPOINT": server.base_url + "/stt",
                    "JKS_TTS_ENDPOINT": server.base_url + "/tts",
                    "JKS_OLED_PORT": "/dev/cu.test",
                }

                with clean_cwd(), patch.dict(os.environ, env, clear=True):
                    with patch("tools.jks_turn_probe.open_serial_output", return_value=port, create=True):
                        exit_code = main(
                            ["--audio", str(audio_path), "--display", "--require-display-ack"],
                            stdout=stdout,
                        )
        finally:
            server.stop()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["server_events"], ["stt", "chat", "tts"])
        self.assertEqual(
            [frame["name"] for frame in port.frames],
            ["listening", "thinking", "thinking", "speaking", "happy"],
        )
        self.assertEqual([frame["text"] for frame in port.frames], ["HEAR", "TEXT", "WAIT", "TALK", "DONE"])
        self.assertEqual(
            [event["stage"] for event in payload["display_events"]],
            ["listening", "transcribing", "thinking", "speaking", "agent"],
        )
        self.assertEqual(payload["checks"]["display"]["ack_count"], 5)
        self.assertEqual(payload["checks"]["display"]["missing"], [])

    def test_required_display_ack_failure_stops_before_network_turn(self):
        server = start_fake_services()
        stdout = io.StringIO()
        port = FakeDisplayPort()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path = Path(temp_dir) / "input.wav"
                write_silent_wav(audio_path)
                env = {
                    "JKS_AGENT_ENDPOINT": server.base_url + "/chat",
                    "JKS_STT_ENDPOINT": server.base_url + "/stt",
                    "JKS_TTS_ENDPOINT": server.base_url + "/tts",
                    "JKS_OLED_PORT": "/dev/cu.test",
                }

                with clean_cwd(), patch.dict(os.environ, env, clear=True):
                    with patch("tools.jks_turn_probe.open_serial_output", return_value=port, create=True):
                        exit_code = main(
                            ["--audio", str(audio_path), "--display", "--require-display-ack"],
                            stdout=stdout,
                        )
        finally:
            server.stop()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["server_events"], [])
        self.assertEqual([event["stage"] for event in payload["display_events"]], ["listening"])
        self.assertEqual(payload["errors"][0]["error"], "display_ack")
        self.assertEqual([event["kind"] for event in server.events], [])

    def test_display_ack_timeout_argument_is_used_for_required_acks(self):
        server = start_fake_services()
        stdout = io.StringIO()
        timeouts = []

        class RecordingDisplay:
            def __init__(self, output, ack_input=None):
                self.output = output

            def show(self, intent):
                self.output.frames.append({"name": intent.emotion, "text": intent.text})

            def read_ack(self, timeout=0.0):
                timeouts.append(timeout)
                return {"status": "ok", "detail": "ok"}

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path = Path(temp_dir) / "input.wav"
                write_silent_wav(audio_path)
                env = {
                    "JKS_AGENT_ENDPOINT": server.base_url + "/chat",
                    "JKS_STT_ENDPOINT": server.base_url + "/stt",
                    "JKS_TTS_ENDPOINT": server.base_url + "/tts",
                    "JKS_OLED_PORT": "/dev/cu.test",
                }

                with clean_cwd(), patch.dict(os.environ, env, clear=True):
                    with patch("tools.jks_turn_probe.open_serial_output", return_value=FakeDisplayPort(), create=True):
                        with patch("tools.jks_turn_probe.DisplayController", RecordingDisplay):
                            exit_code = main(
                                [
                                    "--audio",
                                    str(audio_path),
                                    "--require-display-ack",
                                    "--display-ack-timeout",
                                    "6.5",
                                ],
                                stdout=stdout,
                            )
        finally:
            server.stop()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(timeouts, [6.5, 6.5, 6.5, 6.5, 6.5])


if __name__ == "__main__":
    unittest.main()
