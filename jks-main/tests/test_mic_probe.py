import io
import json
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

from tools.jks_mic_probe import main


def write_wav(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        frames = b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in samples)
        wav.writeframes(frames)


class FakeRecorder:
    def __init__(self, sample_rate=16000, output_dir=None):
        self.output_dir = Path(output_dir or tempfile.gettempdir())
        self.sample_rate = sample_rate
        self.started = False
        self.stopped = False

    def start_recording(self):
        self.started = True

    def stop_recording(self):
        self.stopped = True
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / "probe.wav"
        write_wav(output, [0, 1000, -1000, 2000, -2000])
        return output


class SilentRecorder(FakeRecorder):
    def stop_recording(self):
        self.stopped = True
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / "silent.wav"
        write_wav(output, [0, 0, 0, 0])
        return output


class HangingRecorder(FakeRecorder):
    def start_recording(self):
        time.sleep(1.0)


class MicProbeCliTests(unittest.TestCase):
    def test_missing_duration_value_returns_error_without_recorder(self):
        stdout = io.StringIO()

        exit_code = main(["--duration"], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"], [{"error": "args", "message": "--duration requires seconds"}])

    def test_probe_records_audio_and_reports_signal_without_transcript(self):
        stdout = io.StringIO()

        with mock.patch("tools.jks_mic_probe.AudioRecorder", FakeRecorder):
            exit_code = main(["--duration", "0.25", "--min-rms", "0.001"], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["checks"]["duration_seconds"], 0.25)
        self.assertTrue(payload["checks"]["started"])
        self.assertTrue(payload["checks"]["stopped"])
        self.assertGreater(payload["checks"]["bytes"], 0)
        self.assertEqual(payload["checks"]["frames"], 5)
        self.assertGreater(payload["checks"]["rms"], 0)
        self.assertGreater(payload["checks"]["peak"], 0)
        self.assertNotIn("transcript", payload)

    def test_probe_fails_when_recorded_signal_is_below_min_rms(self):
        stdout = io.StringIO()

        with mock.patch("tools.jks_mic_probe.AudioRecorder", SilentRecorder):
            exit_code = main(["--min-rms", "0.001"], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["error"], "mic_signal")
        self.assertEqual(payload["checks"]["rms"], 0)

    def test_probe_times_out_when_audio_backend_hangs(self):
        stdout = io.StringIO()
        started = time.monotonic()

        with mock.patch("tools.jks_mic_probe.AudioRecorder", HangingRecorder):
            exit_code = main(["--duration", "0.01", "--timeout", "0.05"], stdout=stdout)

        elapsed = time.monotonic() - started
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertLess(elapsed, 0.5)
        self.assertEqual(payload["errors"], [{"error": "mic_timeout", "message": "microphone probe timed out after 0.05s"}])


if __name__ == "__main__":
    unittest.main()
