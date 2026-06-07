import io
import importlib
import json
import os
import tempfile
import unittest


def load_oled_serial():
    try:
        return importlib.import_module("tools.oled_serial")
    except ModuleNotFoundError as exc:
        raise AssertionError("tools.oled_serial must exist") from exc


class OledSerialProtocolTests(unittest.TestCase):
    def test_text_helper_encodes_compact_utf8_ndjson(self):
        oled_serial = load_oled_serial()

        frame = oled_serial.encode_text("Hello, OLED")

        self.assertEqual(frame, b'{"cmd":"text","text":"Hello, OLED"}\n')

    def test_text_helper_escapes_embedded_newline_inside_single_json_line(self):
        oled_serial = load_oled_serial()

        frame = oled_serial.encode_text("line 1\nline 2")

        self.assertEqual(frame, b'{"cmd":"text","text":"line 1\\nline 2"}\n')
        self.assertEqual(frame.count(b"\n"), 1)

    def test_emotion_helper_encodes_ndjson_command(self):
        oled_serial = load_oled_serial()

        frame = oled_serial.encode_emotion("happy")

        self.assertEqual(frame, b'{"cmd":"emotion","name":"happy"}\n')

    def test_clear_helper_encodes_ndjson_command(self):
        oled_serial = load_oled_serial()

        frame = oled_serial.encode_clear()

        self.assertEqual(frame, b'{"cmd":"clear"}\n')

    def test_probe_helper_encodes_ndjson_command(self):
        oled_serial = load_oled_serial()

        frame = oled_serial.encode_probe()

        self.assertEqual(oled_serial.probe_command(), {"cmd": "probe"})
        self.assertEqual(frame, b'{"cmd":"probe"}\n')

    def test_each_frame_decodes_as_one_json_object(self):
        oled_serial = load_oled_serial()

        frames = [
            oled_serial.encode_text("Hi"),
            oled_serial.encode_emotion("sleepy"),
            oled_serial.encode_clear(),
        ]

        decoded = [json.loads(frame.decode("utf-8")) for frame in frames]
        self.assertEqual(
            decoded,
            [
                {"cmd": "text", "text": "Hi"},
                {"cmd": "emotion", "name": "sleepy"},
                {"cmd": "clear"},
            ],
        )

    def test_cli_writes_selected_command_to_binary_output(self):
        oled_serial = load_oled_serial()
        output = io.BytesIO()

        result = oled_serial.main(["text", "Status ready"], output=output)

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), b'{"cmd":"text","text":"Status ready"}\n')

    def test_cli_writes_probe_command_to_binary_output(self):
        oled_serial = load_oled_serial()
        output = io.BytesIO()

        result = oled_serial.main(["probe"], output=output)

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), b'{"cmd":"probe"}\n')

    def test_cli_can_write_command_to_device_path(self):
        oled_serial = load_oled_serial()
        fd, path = tempfile.mkstemp()
        os.close(fd)

        try:
            result = oled_serial.main(["--port", path, "emotion", "focused"])

            self.assertEqual(result, 0)
            with open(path, "rb") as output:
                self.assertEqual(output.read(), b'{"cmd":"emotion","name":"focused"}\n')
        finally:
            os.unlink(path)

    def test_high_baud_rates_without_termios_support_are_not_silently_remapped(self):
        oled_serial = load_oled_serial()

        for baud in (230400, 460800, 921600):
            with self.subTest(baud=baud):
                if not hasattr(oled_serial.termios, f"B{baud}"):
                    self.assertNotIn(baud, oled_serial._BAUD_RATES)


if __name__ == "__main__":
    unittest.main()
