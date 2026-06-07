from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jks.config import AppConfig


class FakeRoot:
    def __init__(self):
        self.after_calls = []
        self.title_text = ""
        self.geometry_value = None
        self.minsize_value = None
        self.mainloop_called = False

    def title(self, text):
        self.title_text = text

    def geometry(self, value):
        self.geometry_value = value

    def minsize(self, width, height):
        self.minsize_value = (width, height)

    def after(self, delay_ms, callback):
        self.after_calls.append(delay_ms)
        callback()

    def mainloop(self):
        self.mainloop_called = True


class DelayedRoot(FakeRoot):
    def after(self, delay_ms, callback):
        self.after_calls.append((delay_ms, callback))


class FakeStringVar:
    def __init__(self, value=""):
        self.value = value
        self.history = [value]

    def set(self, value):
        self.value = value
        self.history.append(value)

    def get(self):
        return self.value


class FakeButton:
    def __init__(self, root, text, command):
        self.root = root
        self.text = text
        self.command = command
        self.options = {}
        self.packed = False

    def pack(self, **kwargs):
        self.packed = True

    def configure(self, **kwargs):
        self.options.update(kwargs)
        if "text" in kwargs:
            self.text = kwargs["text"]


class FakeLabel:
    def __init__(self, root, **kwargs):
        self.root = root
        self.kwargs = kwargs

    def pack(self, **kwargs):
        self.pack_kwargs = kwargs


class FakeCanvas:
    created = []

    def __init__(self, root, **kwargs):
        self.root = root
        self.kwargs = kwargs
        self.operations = []
        self.packed = False
        FakeCanvas.created.append(self)

    def pack(self, **kwargs):
        self.packed = True
        self.pack_kwargs = kwargs

    def delete(self, *args):
        self.operations.append(("delete", args))

    def create_rectangle(self, *args, **kwargs):
        self.operations.append(("rectangle", args, kwargs))

    def create_oval(self, *args, **kwargs):
        self.operations.append(("oval", args, kwargs))

    def create_arc(self, *args, **kwargs):
        self.operations.append(("arc", args, kwargs))

    def create_line(self, *args, **kwargs):
        self.operations.append(("line", args, kwargs))

    def create_text(self, *args, **kwargs):
        self.operations.append(("text", args, kwargs))


class ImmediateThread:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


class DeferredThread:
    created = []

    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon
        DeferredThread.created.append(self)

    def start(self):
        pass


class FakeOrchestrator:
    def __init__(self, result=None, exc=None, start_exc=None):
        self.result = result
        self.exc = exc
        self.start_exc = start_exc
        self.turns = 0
        self.starts = 0

    def run_voice_turn(self):
        self.turns += 1
        if self.exc:
            raise self.exc
        return self.result

    def start_recording(self):
        self.starts += 1
        if self.start_exc:
            raise self.start_exc

    def finish_voice_turn(self):
        self.turns += 1
        if self.exc:
            raise self.exc
        return self.result


class ProgressOrchestrator(FakeOrchestrator):
    def __init__(self, status_callback, result):
        super().__init__(result=result)
        self.status_callback = status_callback

    def finish_voice_turn(self):
        from jks.expression import TurnState

        self.turns += 1
        self.status_callback(TurnState.TRANSCRIBING)
        self.status_callback(TurnState.THINKING)
        self.status_callback(TurnState.SPEAKING)
        return self.result


def sample_config(**overrides):
    data = {
        "agent_host": "",
        "agent_user": "",
        "agent_auth_method": "",
        "agent_ssh_password": "",
        "agent_command": "/usr/local/lib/hermes-agent/venv/bin/hermes",
        "agent_workdir": "/usr/local/lib/hermes-agent",
        "agent_endpoint": "",
        "agent_token": "",
        "agent_model": "gran-agent",
        "stt_provider": "",
        "stt_endpoint": "",
        "stt_token": "",
        "tts_provider": "",
        "tts_endpoint": "",
        "tts_token": "",
        "tts_voice": "warm",
        "fish_api_key": "",
        "fish_tts_model": "s2-pro",
        "fish_tts_latency": "low",
        "oled_port": "/dev/cu.missing",
        "oled_baud": 115200,
    }
    data.update(overrides)
    return AppConfig(**data)


class AppTests(unittest.TestCase):
    def test_importing_app_does_not_create_gui(self):
        import jks.app as app

        self.assertTrue(callable(app.main))

    def test_main_help_prints_usage_without_creating_gui(self):
        from jks import app

        created_roots = []
        with patch.object(app.tk, "Tk", side_effect=lambda: created_roots.append(FakeRoot())):
            output = io.StringIO()
            exit_code = app.main(["--help"], stdout=output)

        self.assertEqual(exit_code, 0)
        self.assertIn("JKS Voice Agent", output.getvalue())
        self.assertEqual(created_roots, [])

    def test_orchestrator_builder_uses_null_display_when_serial_unavailable(self):
        from jks import app
        from jks.display import NullDisplayController
        from jks.speech import FakeSpeechClient

        with tempfile.TemporaryDirectory() as tmp:
            config = sample_config()

            orchestrator = app.build_orchestrator(
                config,
                open_serial=lambda path, baud: (_ for _ in ()).throw(OSError("missing oled")),
                output_dir=Path(tmp),
            )

        self.assertIsInstance(orchestrator.display, NullDisplayController)
        self.assertIsInstance(orchestrator.speech, FakeSpeechClient)

    def test_orchestrator_builder_reports_serial_degraded_status(self):
        from jks import app
        from jks.display import NullDisplayController

        degraded_messages = []
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = app.build_orchestrator(
                sample_config(oled_port="/dev/cu.missing"),
                open_serial=lambda path, baud: (_ for _ in ()).throw(OSError("missing oled")),
                output_dir=Path(tmp),
                display_status_callback=degraded_messages.append,
            )

        self.assertIsInstance(orchestrator.display, NullDisplayController)
        self.assertEqual(
            degraded_messages,
            ["OLED unavailable on /dev/cu.missing; reconnect display and restart if needed."],
        )

    def test_orchestrator_builder_rejects_partial_speech_config(self):
        from jks import app

        with self.assertRaises(ValueError):
            app.build_orchestrator(
                sample_config(stt_endpoint="http://stt.local"),
                open_serial=lambda path, baud: io.BytesIO(),
            )

    def test_orchestrator_builder_uses_fish_audio_provider(self):
        from jks import app
        from jks.speech import FishAudioSpeechClient

        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = app.build_orchestrator(
                sample_config(
                    stt_provider="fish",
                    tts_provider="fish",
                    fish_api_key="fish-secret",
                ),
                open_serial=lambda path, baud: io.BytesIO(),
                output_dir=Path(tmp),
            )

        self.assertIsInstance(orchestrator.speech, FishAudioSpeechClient)

    def test_ui_sets_visible_default_window_size(self):
        from jks import app
        from jks.orchestrator import TurnResult

        root = FakeRoot()
        orchestrator = FakeOrchestrator(
            result=TurnResult(user_text="hello", agent_text="reply", emotion="happy")
        )

        with patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            app.JksApp(root, orchestrator=orchestrator)

        self.assertEqual(root.geometry_value, "560x420")
        self.assertEqual(root.minsize_value, (420, 320))

    def test_orchestrator_builder_uses_ssh_hermes_agent_when_host_is_configured(self):
        from jks import app
        from jks.agent import SshHermesAgentClient

        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = app.build_orchestrator(
                sample_config(
                    agent_host="gran.example.com",
                    agent_user="jks",
                    agent_auth_method="ssh-password",
                    agent_ssh_password="ssh-secret",
                ),
                open_serial=lambda path, baud: io.BytesIO(),
                output_dir=Path(tmp),
            )

        self.assertIsInstance(orchestrator.agent, SshHermesAgentClient)
        self.assertEqual(orchestrator.agent.host, "gran.example.com")
        self.assertEqual(orchestrator.agent.user, "jks")

    def test_ui_success_turn_updates_transcript_and_restores_button(self):
        from jks import app
        from jks.orchestrator import TurnResult

        root = FakeRoot()
        orchestrator = FakeOrchestrator(
            result=TurnResult(user_text="hello", agent_text="reply", emotion="happy")
        )

        with patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root, orchestrator=orchestrator)
            ui.start_turn()
            ui.start_turn()

        self.assertEqual(orchestrator.starts, 1)
        self.assertEqual(orchestrator.turns, 1)
        self.assertEqual(ui.status.get(), "Ready")
        self.assertIn("You: hello", ui.transcript.get())
        self.assertIn("Agent: reply", ui.transcript.get())
        self.assertEqual(ui.button.options["state"], "normal")
        self.assertEqual(ui.button.text, "Speak")

    def test_ui_audio_degraded_turn_preserves_transcript_and_reports_status(self):
        from jks import app
        from jks.orchestrator import TurnResult

        root = FakeRoot()
        orchestrator = FakeOrchestrator(
            result=TurnResult(
                user_text="hello",
                agent_text="reply",
                emotion="happy",
                audio_error="tts failed",
            )
        )

        with patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root, orchestrator=orchestrator)
            ui.start_turn()
            ui.start_turn()

        self.assertIn("Voice output failed", ui.status.get())
        self.assertIn("tts failed", ui.status.get())
        self.assertIn("You: hello", ui.transcript.get())
        self.assertIn("Agent: reply", ui.transcript.get())
        self.assertEqual(ui.button.options["state"], "normal")
        self.assertEqual(ui.button.text, "Speak")

    def test_ui_maps_orchestrator_state_callback_to_status_text(self):
        from jks import app
        from jks.agent import AgentTraceEvent
        from jks.expression import TurnState
        from jks.orchestrator import TurnResult

        root = FakeRoot()
        captured = {}
        orchestrator = FakeOrchestrator(
            result=TurnResult(user_text="hello", agent_text="reply", emotion="happy")
        )

        def fake_build_orchestrator(
            config,
            status_callback=None,
            display_status_callback=None,
            display_error_callback=None,
            agent_trace_callback=None,
        ):
            captured["status_callback"] = status_callback
            captured["agent_trace_callback"] = agent_trace_callback
            return orchestrator

        with patch.object(app, "load_config", return_value=sample_config()), patch.object(
            app, "build_orchestrator", fake_build_orchestrator
        ), patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root)

        self.assertIsNotNone(captured["status_callback"])
        captured["status_callback"](TurnState.TRANSCRIBING)
        self.assertEqual(ui.status.get(), "Transcribing")
        captured["status_callback"](TurnState.THINKING)
        self.assertEqual(ui.status.get(), "Thinking")
        captured["status_callback"](TurnState.SPEAKING)
        self.assertEqual(ui.status.get(), "Speaking")
        self.assertIsNotNone(captured["agent_trace_callback"])
        captured["agent_trace_callback"](AgentTraceEvent(source="tool", message="terminal exit_code=0"))
        self.assertIn("tool: terminal exit_code=0", ui.agent_trace.get())

    def test_ui_has_oled_screen_preview_and_updates_from_display_intent(self):
        from jks import app
        from jks.display import DisplayIntent
        from jks.orchestrator import TurnResult

        root = FakeRoot()
        orchestrator = FakeOrchestrator(
            result=TurnResult(user_text="hello", agent_text="reply", emotion="happy")
        )
        FakeCanvas.created = []

        with patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.tk, "Canvas", FakeCanvas
        ), patch.object(app.threading, "Thread", ImmediateThread):
            ui = app.JksApp(root, orchestrator=orchestrator)
            ui._show_display_preview(DisplayIntent("surprised", "WOW", duration_ms=700, intensity="high"))

        self.assertTrue(FakeCanvas.created)
        self.assertIn("surprised", ui.display_preview.get())
        self.assertIn("WOW", ui.display_preview.get())
        canvas_ops = FakeCanvas.created[0].operations
        self.assertTrue(any(op[0] == "oval" for op in canvas_ops))
        self.assertTrue(any(op[0] == "text" and op[2].get("text") == "WOW" for op in canvas_ops))

    def test_ui_turn_tracks_full_visible_status_sequence(self):
        from jks import app
        from jks.orchestrator import TurnResult

        root = FakeRoot()

        def fake_build_orchestrator(
            config,
            status_callback=None,
            display_status_callback=None,
            display_error_callback=None,
            agent_trace_callback=None,
        ):
            return ProgressOrchestrator(
                status_callback,
                TurnResult(user_text="hello", agent_text="reply", emotion="happy"),
            )

        with patch.object(app, "load_config", return_value=sample_config()), patch.object(
            app, "build_orchestrator", fake_build_orchestrator
        ), patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root)
            ui.start_turn()
            ui.start_turn()

        self.assertEqual(
            ui.status.history,
            [
                "Ready",
                "Listening",
                "Transcribing",
                "Transcribing",
                "Thinking",
                "Speaking",
                "Ready",
            ],
        )

    def test_ui_shows_serial_degraded_prompt_from_builder(self):
        from jks import app
        from jks.orchestrator import TurnResult

        root = FakeRoot()
        orchestrator = FakeOrchestrator(
            result=TurnResult(user_text="hello", agent_text="reply", emotion="happy")
        )

        def fake_build_orchestrator(
            config,
            status_callback=None,
            display_status_callback=None,
            display_error_callback=None,
            agent_trace_callback=None,
        ):
            display_status_callback(
                "OLED unavailable on /dev/cu.missing; reconnect display and restart if needed."
            )
            return orchestrator

        with patch.object(app, "load_config", return_value=sample_config()), patch.object(
            app, "build_orchestrator", fake_build_orchestrator
        ), patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root)

        self.assertEqual(
            ui.device_status.get(),
            "OLED unavailable on /dev/cu.missing; reconnect display and restart if needed.",
        )

    def test_ui_shows_runtime_display_failure_from_orchestrator(self):
        from jks import app
        from jks.orchestrator import TurnResult

        root = FakeRoot()
        captured = {}
        orchestrator = FakeOrchestrator(
            result=TurnResult(user_text="hello", agent_text="reply", emotion="happy")
        )

        def fake_build_orchestrator(
            config,
            status_callback=None,
            display_status_callback=None,
            display_error_callback=None,
            agent_trace_callback=None,
        ):
            captured["display_error_callback"] = display_error_callback
            return orchestrator

        with patch.object(app, "load_config", return_value=sample_config()), patch.object(
            app, "build_orchestrator", fake_build_orchestrator
        ), patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root)

        self.assertIsNotNone(captured["display_error_callback"])
        captured["display_error_callback"]("OLED update failed: oled disconnected")
        self.assertEqual(ui.device_status.get(), "OLED update failed: oled disconnected")

    def test_ui_first_click_starts_recording_and_waits_for_stop_click(self):
        from jks import app
        from jks.orchestrator import TurnResult

        root = FakeRoot()
        orchestrator = FakeOrchestrator(
            result=TurnResult(user_text="hello", agent_text="reply", emotion="happy")
        )

        with patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root, orchestrator=orchestrator)
            ui.start_turn()

        self.assertEqual(orchestrator.starts, 1)
        self.assertEqual(orchestrator.turns, 0)
        self.assertEqual(ui.status.get(), "Listening")
        self.assertEqual(ui.button.options["state"], "normal")
        self.assertEqual(ui.button.text, "Stop")

    def test_ui_second_click_shows_transcribing_until_worker_reports_progress(self):
        from jks import app
        from jks.orchestrator import TurnResult

        root = FakeRoot()
        orchestrator = FakeOrchestrator(
            result=TurnResult(user_text="hello", agent_text="reply", emotion="happy")
        )
        DeferredThread.created = []

        with patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", DeferredThread
        ):
            ui = app.JksApp(root, orchestrator=orchestrator)
            ui.start_turn()
            ui.start_turn()

        self.assertEqual(ui.status.get(), "Transcribing")
        self.assertEqual(len(DeferredThread.created), 1)

    def test_ui_error_turn_restores_button(self):
        from jks import app

        root = FakeRoot()
        orchestrator = FakeOrchestrator(exc=RuntimeError("agent missing"))

        with patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root, orchestrator=orchestrator)
            ui.start_turn()
            ui.start_turn()

        self.assertIn("agent missing", ui.status.get())
        self.assertEqual(ui.button.options["state"], "normal")
        self.assertEqual(ui.button.text, "Speak")

    def test_ui_error_turn_preserves_partial_turn_context(self):
        from jks import app
        from jks.orchestrator import TurnFailure

        root = FakeRoot()
        orchestrator = FakeOrchestrator(
            exc=TurnFailure(
                "agent failed",
                user_text="hello",
                audio_path=Path("/tmp/jks-test-input.wav"),
            )
        )

        with patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root, orchestrator=orchestrator)
            ui.start_turn()
            ui.start_turn()

        self.assertIn("agent failed", ui.status.get())
        self.assertIn("You: hello", ui.transcript.get())
        self.assertIn("Audio: /tmp/jks-test-input.wav", ui.transcript.get())
        self.assertEqual(ui.button.options["state"], "normal")

    def test_ui_start_recording_error_restores_button(self):
        from jks import app

        root = FakeRoot()
        orchestrator = FakeOrchestrator(start_exc=RuntimeError("microphone unavailable"))

        with patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root, orchestrator=orchestrator)
            ui.start_turn()

        self.assertIn("microphone unavailable", ui.status.get())
        self.assertEqual(ui.button.options["state"], "normal")
        self.assertEqual(ui.button.text, "Speak")

    def test_ui_error_turn_preserves_exception_for_delayed_after_callback(self):
        from jks import app

        root = DelayedRoot()
        orchestrator = FakeOrchestrator(exc=RuntimeError("agent missing"))

        with patch.object(app.tk, "StringVar", FakeStringVar), patch.object(
            app.ttk, "Button", FakeButton
        ), patch.object(app.ttk, "Label", FakeLabel), patch.object(
            app.threading, "Thread", ImmediateThread
        ):
            ui = app.JksApp(root, orchestrator=orchestrator)
            ui.start_turn()
            ui.start_turn()

        root.after_calls[0][1]()

        self.assertIn("agent missing", ui.status.get())
        self.assertEqual(ui.button.options["state"], "normal")


if __name__ == "__main__":
    unittest.main()
