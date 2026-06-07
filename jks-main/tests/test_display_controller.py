import io
import json
import os
import unittest
from contextlib import ExitStack
from unittest import mock

from jks.display import (
    ALLOWED_EMOTIONS,
    DisplayController,
    DisplayIntent,
    NullDisplayController,
    open_serial_output,
)


class FakePort(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.flushed = False

    def flush(self):
        self.flushed = True


class BlockingAckInput:
    def readline(self):
        raise AssertionError("read_ack must not call blocking readline when no data is ready")


class DisplayControllerTests(unittest.TestCase):
    def test_sends_whitelisted_emotion_with_short_text(self):
        port = FakePort()
        display = DisplayController(port)

        display.show(DisplayIntent(emotion="thinking", text="WAIT"))

        self.assertEqual(
            port.getvalue(),
            b'{"cmd":"emotion","name":"thinking","text":"WAIT","duration_ms":1200,"intensity":"normal"}\n',
        )
        self.assertTrue(port.flushed)

    def test_sends_full_display_intent_fields(self):
        port = FakePort()
        display = DisplayController(port)

        display.show(DisplayIntent(emotion="surprised", text="WOW", duration_ms=2400, intensity="high"))

        payload = json.loads(port.getvalue().decode("utf-8"))
        self.assertEqual(
            payload,
            {
                "cmd": "emotion",
                "name": "surprised",
                "text": "WOW",
                "duration_ms": 2400,
                "intensity": "high",
            },
        )

    def test_allowed_emotions_include_required_whitelist(self):
        self.assertGreaterEqual(
            ALLOWED_EMOTIONS,
            {
                "neutral",
                "happy",
                "thinking",
                "speaking",
                "listening",
                "surprised",
                "sleepy",
                "sad",
                "angry",
                "error",
            },
        )

    def test_invalid_emotion_falls_back_to_neutral(self):
        port = FakePort()
        display = DisplayController(port)

        display.show(DisplayIntent(emotion="run_shell", text="BAD"))

        payload = json.loads(port.getvalue().decode("utf-8"))
        self.assertEqual(
            payload,
            {
                "cmd": "emotion",
                "name": "neutral",
                "text": "BAD",
                "duration_ms": 1200,
                "intensity": "normal",
            },
        )

    def test_empty_text_falls_back_to_selected_emotion_label(self):
        port = FakePort()
        display = DisplayController(port)

        display.show(DisplayIntent(emotion="thinking"))
        display.show(DisplayIntent(emotion="run_shell"))

        frames = [json.loads(line) for line in port.getvalue().decode("utf-8").splitlines()]
        self.assertEqual(frames[0]["name"], "thinking")
        self.assertEqual(frames[0]["text"], "THINKING")
        self.assertEqual(frames[1]["name"], "neutral")
        self.assertEqual(frames[1]["text"], "NEUTRAL")

    def test_text_is_ascii_printable_and_clamped_for_oled(self):
        port = FakePort()
        display = DisplayController(port)

        display.show(DisplayIntent(emotion="happy", text="A\nB\tCafé TOO LONGER"))

        payload = json.loads(port.getvalue().decode("utf-8"))
        self.assertEqual(payload["text"], "ABCaf TOO LONG")

    def test_clear_and_probe_send_single_command_frames(self):
        port = FakePort()
        display = DisplayController(port)

        display.clear()
        display.probe()

        self.assertEqual(port.getvalue(), b'{"cmd":"clear"}\n{"cmd":"probe"}\n')

    def test_read_ack_returns_parsed_json_from_ack_input(self):
        ack_input = io.BytesIO(b'{"ok":true,"cmd":"probe"}\n')
        display = DisplayController(FakePort(), ack_input=ack_input)

        self.assertEqual(display.read_ack(), {"ok": True, "cmd": "probe"})

    def test_read_ack_returns_none_without_ack_input_or_data(self):
        self.assertIsNone(DisplayController(FakePort()).read_ack())
        self.assertIsNone(DisplayController(FakePort(), ack_input=io.BytesIO()).read_ack())

    def test_read_ack_does_not_block_when_no_data_is_ready(self):
        display = DisplayController(FakePort(), ack_input=BlockingAckInput())

        with mock.patch("jks.display.select.select", return_value=([], [], [])):
            self.assertIsNone(display.read_ack())

    def test_null_display_controller_is_no_op(self):
        display = NullDisplayController()

        display.show(DisplayIntent(emotion="happy", text="READY"))
        display.clear()
        display.probe()

        self.assertIsNone(display.read_ack())
        self.assertIsNone(display.read_ack(timeout=0.01))

    def test_display_intent_defaults_optional_fields(self):
        intent = DisplayIntent(emotion="listening", text="READY")

        self.assertEqual(intent.duration_ms, 1200)
        self.assertEqual(intent.intensity, "normal")

    def test_open_serial_output_opens_read_write_and_configures_tty(self):
        fake_attrs = [0, 0, 0, 0, 0, 0, 0]
        fake_writer = io.BytesIO()

        with ExitStack() as stack:
            open_mock = stack.enter_context(mock.patch("jks.display.os.open", return_value=12))
            stack.enter_context(mock.patch("jks.display.os.isatty", return_value=True))
            fdopen_mock = stack.enter_context(mock.patch("jks.display.os.fdopen", return_value=fake_writer))
            getattr_mock = stack.enter_context(
                mock.patch("jks.display.termios.tcgetattr", return_value=fake_attrs.copy())
            )
            setattr_mock = stack.enter_context(mock.patch("jks.display.termios.tcsetattr"))
            writer = open_serial_output("/dev/cu.test", 115200)

        self.assertIs(writer, fake_writer)
        open_mock.assert_called_once()
        self.assertEqual(open_mock.call_args.args[0], "/dev/cu.test")
        flags = open_mock.call_args.args[1]
        self.assertEqual(flags & os.O_RDWR, os.O_RDWR)
        self.assertEqual(flags & os.O_WRONLY, 0)
        self.assertEqual(flags & os.O_NOCTTY, os.O_NOCTTY)
        fdopen_mock.assert_called_once_with(12, "r+b", buffering=0)
        getattr_mock.assert_called_once_with(12)
        setattr_mock.assert_called_once()

    def test_open_serial_output_rejects_unsupported_baud_before_opening(self):
        with mock.patch("jks.display.os.open") as open_mock:
            with self.assertRaises(ValueError):
                open_serial_output("/dev/cu.test", 12345)

        open_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
