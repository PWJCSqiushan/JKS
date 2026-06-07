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
    def __init__(
        self,
        ack_lines=None,
        auto_ack=False,
        max_auto_acks=None,
        stale_on_first_write=False,
    ):
        self.ack_lines = list(ack_lines or [])
        self.auto_ack = auto_ack
        self.max_auto_acks = max_auto_acks
        self.auto_ack_count = 0
        self.stale_on_first_write = stale_on_first_write
        self.frames = []
        self.closed = False

    def write(self, data):
        payload = json.loads(data.decode("utf-8"))
        self.frames.append(payload)
        if self.stale_on_first_write:
            self.ack_lines.append(b'{"status":"error","detail":"syntax error in JSON"}\n')
            self.stale_on_first_write = False
        if self.auto_ack and (
            self.max_auto_acks is None or self.auto_ack_count < self.max_auto_acks
        ):
            detail = payload.get("name", payload.get("cmd", ""))
            self.ack_lines.append(json.dumps({"status": "ok", "detail": detail}).encode() + b"\n")
            self.auto_ack_count += 1
        return len(data)

    def flush(self):
        return None

    def readline(self):
        if not self.ack_lines:
            return b""
        return self.ack_lines.pop(0)

    def close(self):
        self.closed = True


class AppProbeCliTests(unittest.TestCase):
    def test_no_op_player_consumes_stream_without_audio_backend(self):
        from tools.jks_app_probe import NoOpPlayer

        player = NoOpPlayer()
        player.play_stream([b"one", b"", b"two"], suffix=".mp3")

        self.assertEqual(player.played, [])
        self.assertEqual(player.streamed_chunks, [b"one", b"two"])

    def test_missing_audio_argument_returns_error_without_loading_config(self):
        from tools.jks_app_probe import main

        stdout = io.StringIO()
        with clean_cwd(), patch.dict(os.environ, {}, clear=True):
            exit_code = main([], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["checks"], {})
        self.assertEqual(payload["errors"], [{"error": "audio", "message": "--audio is required"}])

    def test_runs_start_finish_orchestrator_path_with_display_ack_summary(self):
        from tools.jks_app_probe import main

        server = start_fake_services()
        stdout = io.StringIO()
        port = FakeDisplayPort(auto_ack=True)
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
                    "JKS_OLED_PORT": "/dev/cu.test",
                }

                with clean_cwd(), patch.dict(os.environ, env, clear=True):
                    with patch("tools.jks_app_probe.open_serial_output", return_value=port):
                        exit_code = main(
                            [
                                "--audio",
                                str(audio_path),
                                "--require-display-ack",
                                "--display-ack-timeout",
                                "5",
                            ],
                            stdout=stdout,
                        )
        finally:
            server.stop()

        text = stdout.getvalue()
        payload = json.loads(text)
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertNotIn("secret-token", text)
        self.assertNotIn("api_key=secret", text)
        self.assertNotIn("token=secret", text)
        self.assertNotIn("hello agent", text)
        self.assertNotIn("Fake reply to: hello agent", text)
        self.assertEqual(payload["server_events"], ["stt", "chat", "tts"])
        self.assertEqual(payload["checks"]["ui"]["clicks"], 2)
        self.assertEqual(payload["checks"]["ui"]["button_text"], "Speak")
        self.assertEqual(payload["checks"]["ui"]["button_state"], "normal")
        self.assertEqual(payload["checks"]["ui"]["status"], "Ready")
        self.assertEqual(payload["checks"]["recording"], {"started": True, "stopped": True})
        self.assertEqual(
            payload["checks"]["orchestrator"],
            {"start_calls": 1, "finish_calls": 1, "run_voice_turn_calls": 0},
        )
        self.assertEqual(payload["checks"]["stt"], {"text_length": len("hello agent")})
        self.assertEqual(payload["checks"]["agent"]["text_length"], len("Fake reply to: hello agent"))
        self.assertEqual(payload["checks"]["agent"]["display_text_length"], len("DONE"))
        self.assertEqual(payload["checks"]["agent"]["duration_ms"], 1200)
        self.assertEqual(payload["checks"]["agent"]["intensity"], "normal")
        self.assertEqual(payload["checks"]["playback"], {"played": False})
        self.assertEqual(payload["checks"]["display"]["ack_count"], 5)
        self.assertEqual(payload["checks"]["display"]["missing"], [])
        self.assertEqual(payload["checks"]["display"]["drained_count"], 0)
        self.assertEqual(
            [frame["name"] for frame in port.frames],
            ["listening", "thinking", "thinking", "speaking", "happy"],
        )
        self.assertTrue(port.closed)

    def test_display_ack_drain_ignores_stale_serial_ack_before_app_turn(self):
        from tools.jks_app_probe import main

        server = start_fake_services()
        stdout = io.StringIO()
        port = FakeDisplayPort(
            [
                b'{"status":"error","detail":"syntax error in JSON"}\n',
            ],
            auto_ack=True,
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
                    with patch("tools.jks_app_probe.open_serial_output", return_value=port):
                        exit_code = main(
                            ["--audio", str(audio_path), "--require-display-ack"],
                            stdout=stdout,
                        )
        finally:
            server.stop()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["checks"]["display"]["drained_count"], 1)
        self.assertEqual(payload["checks"]["display"]["ack_details"], ["listening", "thinking", "thinking", "speaking", "happy"])

    def test_display_ack_reader_skips_delayed_stale_ack_until_expected_detail(self):
        from tools.jks_app_probe import main

        server = start_fake_services()
        stdout = io.StringIO()
        port = FakeDisplayPort(auto_ack=True, stale_on_first_write=True)
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
                    with patch("tools.jks_app_probe.open_serial_output", return_value=port):
                        exit_code = main(
                            ["--audio", str(audio_path), "--require-display-ack"],
                            stdout=stdout,
                        )
        finally:
            server.stop()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["checks"]["display"]["skipped_count"], 1)
        self.assertEqual(payload["checks"]["display"]["ack_details"], ["listening", "thinking", "thinking", "speaking", "happy"])

    def test_display_ack_missing_fails_after_turn_without_losing_service_evidence(self):
        from tools.jks_app_probe import main

        server = start_fake_services()
        stdout = io.StringIO()
        port = FakeDisplayPort(auto_ack=True, max_auto_acks=1)
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
                    with patch("tools.jks_app_probe.open_serial_output", return_value=port):
                        exit_code = main(
                            ["--audio", str(audio_path), "--require-display-ack"],
                            stdout=stdout,
                        )
        finally:
            server.stop()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["server_events"], ["stt", "chat", "tts"])
        self.assertEqual(payload["checks"]["display"]["ack_count"], 1)
        self.assertEqual(payload["errors"][0]["error"], "display_ack")

    def test_play_flag_reports_audio_playback_failure_as_probe_failure(self):
        from tools.jks_app_probe import main

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
                    with patch("tools.jks_app_probe.open_serial_output", return_value=port):
                        class FailingPlayer:
                            def play(self, path):
                                raise OSError("no speaker")

                        with patch("tools.jks_app_probe.AudioPlayer", return_value=FailingPlayer()):
                            exit_code = main(["--audio", str(audio_path), "--play"], stdout=stdout)
        finally:
            server.stop()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["server_events"], ["stt", "chat", "tts"])
        self.assertTrue(payload["checks"]["playback"]["played"])
        self.assertIn("no speaker", payload["checks"]["playback"]["audio_error"])
        self.assertEqual(payload["errors"][0]["error"], "playback")


if __name__ == "__main__":
    unittest.main()
