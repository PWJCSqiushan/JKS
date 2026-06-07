import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


@contextmanager
def clean_cwd():
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            yield
        finally:
            os.chdir(old_cwd)


class FakeRoot:
    def __init__(self):
        self.destroyed = False
        self.withdrawn = False
        self.updated = 0
        self.title_value = "JKS Voice Agent"
        self.after_calls = []
        self.mainloop_called = False
        self.quit_called = False

    def withdraw(self):
        self.withdrawn = True

    def update(self):
        self.updated += 1

    def update_idletasks(self):
        self.updated += 1

    def destroy(self):
        self.destroyed = True

    def title(self):
        return self.title_value

    def after(self, delay_ms, callback):
        self.after_calls.append((delay_ms, callback))
        self.after_calls.sort(key=lambda item: item[0])

    def mainloop(self):
        self.mainloop_called = True
        while self.after_calls and not self.quit_called:
            _, callback = self.after_calls.pop(0)
            callback()

    def quit(self):
        self.quit_called = True


class FakeButton:
    def __init__(self, app):
        self.app = app
        self.text = "Speak"
        self.state = "normal"

    def invoke(self):
        self.app.clicks += 1
        if self.app.clicks == 1:
            self.state = "normal"
            self.text = "Stop"
            self.app.status.set("Listening")
            self.app.orchestrator.start_recording()
            return None
        self.state = "disabled"
        self.text = "Stop"
        self.app.status.set("Transcribing")
        result = self.app.orchestrator.finish_voice_turn()
        self.app.status.set("Ready")
        self.text = "Speak"
        self.state = "normal"
        self.app.transcript.set(f"You: {result.user_text}\nAgent: {result.agent_text}")
        return None

    def cget(self, key):
        if key == "text":
            return self.text
        if key == "state":
            return self.state
        raise KeyError(key)


class FakeStringVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeJksApp:
    def __init__(self, root, orchestrator):
        self.root = root
        self.orchestrator = orchestrator
        self.clicks = 0
        self.status = FakeStringVar("Ready")
        self.transcript = FakeStringVar("")
        self.button = FakeButton(self)
        self.device_status = FakeStringVar("OLED ready")


class FakeResult:
    user_text = "hello agent"
    agent_text = "Fake reply to: hello agent"
    emotion = "happy"
    audio_error = ""


class FakeDisplay:
    def __init__(self):
        self.acks = []

    def add_ack(self, detail):
        self.acks.append({"status": "ok", "detail": detail})

    def read_ack(self, timeout=0.0):
        if not self.acks:
            return None
        return self.acks.pop(0)


class FakeInner:
    def __init__(self):
        self.display = FakeDisplay()

    def start_recording(self):
        self.display.add_ack("listening")
        return None

    def finish_voice_turn(self):
        self.display.add_ack("thinking")
        self.display.add_ack("thinking")
        self.display.add_ack("speaking")
        self.display.add_ack("happy")
        return FakeResult()


class GuiProbeCliTests(unittest.TestCase):
    def test_missing_audio_argument_returns_error_without_creating_tk(self):
        from tools.jks_gui_probe import main

        stdout = io.StringIO()
        with clean_cwd(), mock.patch("tools.jks_gui_probe.tk.Tk") as tk_mock:
            exit_code = main([], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["checks"], {})
        self.assertEqual(payload["errors"], [{"error": "audio", "message": "--audio is required"}])
        tk_mock.assert_not_called()

    def test_hidden_gui_probe_invokes_real_button_path_without_transcript_leak(self):
        from tools.jks_gui_probe import main
        from jks.config import AppConfig

        stdout = io.StringIO()
        root = FakeRoot()
        config = AppConfig(
            agent_host="",
            agent_user="",
            agent_auth_method="",
            agent_ssh_password="",
            agent_command="/usr/local/lib/hermes-agent/venv/bin/hermes",
            agent_workdir="/usr/local/lib/hermes-agent",
            agent_endpoint="http://agent.local/chat",
            agent_token="secret-token",
            agent_model="gran-agent",
            stt_provider="http",
            stt_endpoint="http://speech.local/stt",
            stt_token="",
            tts_provider="http",
            tts_endpoint="http://speech.local/tts",
            tts_token="",
            fish_api_key="",
            fish_tts_model="s2-pro",
            fish_tts_latency="low",
            tts_voice="warm",
            oled_port="/dev/cu.fake",
            oled_baud=115200,
        )

        with tempfile.TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "input.wav"
            audio_path.write_bytes(b"fake-audio")

            with clean_cwd(), mock.patch("tools.jks_gui_probe.tk.Tk", return_value=root), mock.patch(
                "tools.jks_gui_probe.JksApp", FakeJksApp
            ), mock.patch("tools.jks_gui_probe.load_config", return_value=config), mock.patch(
                "tools.jks_gui_probe.analyze_config",
                return_value={"ok": True, "agent": {"mode": "http"}, "speech": {"mode": "http"}},
            ), mock.patch("tools.jks_gui_probe.build_orchestrator", return_value=FakeInner()):
                exit_code = main(
                    ["--audio", str(audio_path), "--require-display-ack", "--display-ack-timeout", "5"],
                    stdout=stdout,
                )

        text = stdout.getvalue()
        payload = json.loads(text)
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertNotIn("secret-token", text)
        self.assertNotIn("agent.local", text)
        self.assertNotIn("speech.local", text)
        self.assertNotIn("hello agent", text)
        self.assertTrue(root.withdrawn)
        self.assertTrue(root.mainloop_called)
        self.assertTrue(root.quit_called)
        self.assertTrue(root.destroyed)
        self.assertEqual(payload["checks"]["gui"]["button_text"], "Speak")
        self.assertEqual(payload["checks"]["gui"]["button_state"], "normal")
        self.assertEqual(payload["checks"]["orchestrator"]["start_calls"], 1)
        self.assertEqual(payload["checks"]["orchestrator"]["finish_calls"], 1)
        self.assertEqual(payload["checks"]["display"]["ack_count"], 5)
        self.assertEqual(payload["server_events"], ["stt", "chat", "tts"])


if __name__ == "__main__":
    unittest.main()
