import io
import json
import socket
import threading
import time
import unittest
from unittest import mock

from tools.oled_smoke import DEFAULT_TIMEOUT, main, run_oled_smoke


EXPECTED_DETAILS = [
    "probe",
    "neutral",
    "listening",
    "thinking",
    "speaking",
    "happy",
    "surprised",
    "sleepy",
    "sad",
    "angry",
    "error",
    "text",
    "clear",
]


class FakePort:
    def __init__(self, lines):
        self._lines = list(lines)
        self.writes = []
        self.flush_count = 0
        self.closed = False

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        self.flush_count += 1

    def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False


class EchoingFakePort(FakePort):
    drain_stale_input = True

    def write(self, data):
        super().write(data)
        payload = json.loads(data.decode("utf-8"))
        if payload["cmd"] == "probe":
            detail = "probe"
        elif payload["cmd"] == "emotion":
            detail = payload["name"]
        else:
            detail = payload["cmd"]
        self._lines.append(json.dumps({"status": "ok", "detail": detail, "fresh": True}).encode() + b"\n")
        return len(data)


def decoded_writes(port):
    return [json.loads(frame.decode("utf-8")) for frame in port.writes]


class OledSmokeTests(unittest.TestCase):
    def test_default_timeout_covers_micro_python_probe_animation(self):
        self.assertGreaterEqual(DEFAULT_TIMEOUT, 2.0)

    def test_oled_smoke_sends_commands_and_collects_acks(self):
        port = FakePort([json.dumps({"status": "ok", "detail": detail}).encode() + b"\n" for detail in EXPECTED_DETAILS])

        result = run_oled_smoke(port=port)

        self.assertTrue(result["ok"])
        writes = decoded_writes(port)
        self.assertEqual(writes[0], {"cmd": "probe"})
        self.assertEqual([payload.get("name", payload["cmd"]) for payload in writes], EXPECTED_DETAILS)
        happy = next(payload for payload in writes if payload.get("name") == "happy")
        self.assertEqual(happy["text"], "SMOKE OK")
        self.assertEqual(happy["duration_ms"], 1200)
        self.assertEqual(happy["intensity"], "high")
        self.assertEqual([ack["detail"] for ack in result["acks"]], EXPECTED_DETAILS)
        self.assertEqual(result["details"], EXPECTED_DETAILS)
        self.assertEqual(result["missing"], [])
        self.assertEqual(port.flush_count, len(EXPECTED_DETAILS))

    def test_fake_port_does_not_open_serial(self):
        port = FakePort([json.dumps({"status": "ok", "detail": detail}).encode() + b"\n" for detail in EXPECTED_DETAILS])

        with mock.patch("jks.display.open_serial_output") as open_serial:
            result = run_oled_smoke(port=port)

        self.assertTrue(result["ok"])
        open_serial.assert_not_called()

    def test_oled_smoke_reports_missing_ack_details(self):
        port = FakePort([b'{"status":"ok","detail":"probe"}\n'])

        result = run_oled_smoke(port=port)

        self.assertFalse(result["ok"])
        self.assertEqual(result["details"], ["probe"])
        self.assertEqual(result["missing"], EXPECTED_DETAILS[1:])

    def test_oled_smoke_ignores_stale_boot_ack_before_command_acks(self):
        port = FakePort(
            [
                b'JKS MicroPython OLED controller boot\n',
                b'{"status":"ok","detail":"boot"}\n',
                *[json.dumps({"status": "ok", "detail": detail}).encode() + b"\n" for detail in EXPECTED_DETAILS],
            ]
        )

        result = run_oled_smoke(port=port)

        self.assertTrue(result["ok"])
        self.assertEqual(result["details"], EXPECTED_DETAILS)

    def test_oled_smoke_drains_stale_same_detail_acks_before_running(self):
        port = EchoingFakePort([json.dumps({"status": "ok", "detail": detail}).encode() + b"\n" for detail in EXPECTED_DETAILS])

        result = run_oled_smoke(port=port)

        self.assertTrue(result["ok"])
        self.assertEqual(result["details"], EXPECTED_DETAILS)
        self.assertTrue(all(ack.get("fresh") is True for ack in result["acks"]))

    def test_oled_smoke_reports_non_json_lines_when_ack_is_missing(self):
        port = FakePort([b"not-json\n"])

        result = run_oled_smoke(port=port)

        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["error"], "json")
        self.assertEqual(result["errors"][0]["line"], "not-json")

    def test_oled_smoke_times_out_on_partial_serial_line_without_newline(self):
        port_socket, peer_socket = socket.socketpair()
        port = port_socket.makefile("rwb", buffering=0)
        try:
            peer_socket.sendall(b'{"status":"ok"')
            result_box = {}

            thread = threading.Thread(
                target=lambda: result_box.setdefault("result", run_oled_smoke(port=port, timeout=0.05)),
                daemon=True,
            )
            start = time.monotonic()
            thread.start()
            max_elapsed = len(EXPECTED_DETAILS) * 0.05 + 1.0
            thread.join(max_elapsed)
            if thread.is_alive():
                peer_socket.close()
                thread.join(0.25)
                self.fail("OLED smoke blocked on a partial line beyond its timeout")

            self.assertLess(time.monotonic() - start, max_elapsed)
            result = result_box["result"]
            self.assertFalse(result["ok"])
            self.assertEqual(result["errors"][0]["error"], "json")
            self.assertEqual(result["errors"][0]["line"], '{"status":"ok"')
        finally:
            port.close()
            port_socket.close()
            peer_socket.close()

    def test_main_opens_serial_and_prints_compact_json(self):
        port = FakePort([json.dumps({"status": "ok", "detail": detail}).encode() + b"\n" for detail in EXPECTED_DETAILS])
        stdout = io.StringIO()

        with mock.patch("jks.display.open_serial_output", return_value=port) as open_serial:
            exit_code = main(["--port", "/dev/cu.fake", "--baud", "57600", "--timeout", "2.5"], stdout=stdout)

        self.assertEqual(exit_code, 0)
        open_serial.assert_called_once_with("/dev/cu.fake", 57600)
        output = stdout.getvalue()
        self.assertNotIn(": ", output)
        self.assertNotIn(", ", output)
        payload = json.loads(output)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["details"], EXPECTED_DETAILS)
        self.assertTrue(port.closed)

    def test_main_uses_configured_port_and_baud_when_not_explicit(self):
        port = FakePort([json.dumps({"status": "ok", "detail": detail}).encode() + b"\n" for detail in EXPECTED_DETAILS])
        stdout = io.StringIO()

        with mock.patch("jks.display.open_serial_output", return_value=port) as open_serial:
            with mock.patch.dict(
                "os.environ",
                {"JKS_OLED_PORT": "/dev/cu.configured", "JKS_OLED_BAUD": "57600"},
                clear=True,
            ):
                exit_code = main([], stdout=stdout)

        self.assertEqual(exit_code, 0)
        open_serial.assert_called_once_with("/dev/cu.configured", 57600)

    def test_hold_ms_overrides_emotion_durations_for_visual_acceptance(self):
        port = FakePort([json.dumps({"status": "ok", "detail": detail}).encode() + b"\n" for detail in EXPECTED_DETAILS])

        result = run_oled_smoke(port=port, hold_ms=2000)

        self.assertTrue(result["ok"])
        for payload in decoded_writes(port):
            if payload["cmd"] == "emotion":
                self.assertEqual(payload["duration_ms"], 2000)

    def test_main_returns_one_for_incomplete_ack_sequence(self):
        stdout = io.StringIO()

        with mock.patch("jks.display.open_serial_output", return_value=FakePort([b'{"status":"ok","detail":"probe"}\n'])):
            exit_code = main(["--port", "/dev/cu.fake"], stdout=stdout)

        self.assertEqual(exit_code, 1)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])

    def test_main_returns_json_error_when_serial_open_fails(self):
        stdout = io.StringIO()

        with mock.patch("jks.display.open_serial_output", side_effect=OSError("missing port")):
            exit_code = main(["--port", "/dev/cu.fake"], stdout=stdout)

        self.assertEqual(exit_code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["error"], "open_serial")


if __name__ == "__main__":
    unittest.main()
