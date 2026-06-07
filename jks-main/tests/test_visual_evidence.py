import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import jks_visual_evidence


class FakeProcess:
    def __init__(self, output: Path, returncode=0):
        self.output = output
        self.returncode = returncode
        self.command = None

    def wait(self, timeout=None):
        self.output.write_bytes(b"video")
        return self.returncode


class TimeoutProcess(FakeProcess):
    def __init__(self, output: Path):
        super().__init__(output)
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        if self.terminated:
            return 143
        raise subprocess.TimeoutExpired(["ffmpeg"], timeout)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class VisualEvidenceTests(unittest.TestCase):
    def test_missing_camera_device_returns_argument_error(self):
        output = io.StringIO()

        exit_code = jks_visual_evidence.main([], stdout=output)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"], [{"error": "args", "message": "--camera-device is required"}])

    def test_list_devices_runs_ffmpeg_without_capturing(self):
        output = io.StringIO()
        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="[0] Camera\n")

        exit_code = jks_visual_evidence.main(["--list-devices"], stdout=output, runner=runner)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(commands, [["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]])
        self.assertIn("[0] Camera", payload["devices"])

    def test_list_devices_accepts_avfoundation_output_with_nonzero_exit(self):
        output = io.StringIO()

        def runner(command, **kwargs):
            return subprocess.CompletedProcess(
                command,
                251,
                stdout="",
                stderr="AVFoundation video devices:\n[0] MacBook Pro Camera\n",
            )

        exit_code = jks_visual_evidence.main(["--list-devices"], stdout=output, runner=runner)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertIn("MacBook Pro Camera", payload["devices"])
        self.assertEqual(payload["errors"], [])

    def test_capture_records_camera_runs_oled_smoke_and_screenshot(self):
        output = io.StringIO()
        commands = []
        processes = []

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            def runner(command, **kwargs):
                commands.append(command)
                if command[0] == "screencapture":
                    Path(command[-1]).write_bytes(b"screen")
                return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}\n', stderr="")

            def popen(command, **kwargs):
                commands.append(command)
                process = FakeProcess(output_dir / "oled-camera.mp4")
                process.command = command
                processes.append(process)
                return process

            exit_code = jks_visual_evidence.main(
                [
                    "--camera-device",
                    "2",
                    "--output-dir",
                    str(output_dir),
                    "--seconds",
                    "2",
                    "--hold-ms",
                    "500",
                ],
                stdout=output,
                runner=runner,
                popen_factory=popen,
                sleeper=lambda _: None,
            )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertTrue((output_dir / "oled-camera.mp4").exists())
            self.assertTrue((output_dir / "desktop-screen.png").exists())
            self.assertEqual(payload["camera_video"], str(output_dir / "oled-camera.mp4"))
            self.assertEqual(payload["desktop_screenshot"], str(output_dir / "desktop-screen.png"))
            self.assertEqual(payload["oled_smoke"]["ok"], True)
            self.assertTrue(payload["visual_review_required"])

        self.assertIn(
            [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-f",
                "avfoundation",
                "-framerate",
                "30",
                "-video_size",
                "1920x1440",
                "-t",
                "2",
                "-i",
                "2:none",
                str(output_dir / "oled-camera.mp4"),
            ],
            commands,
        )
        self.assertIn(
            ["screencapture", "-x", str(output_dir / "desktop-screen.png")],
            commands,
        )
        self.assertIn(
            [
                jks_visual_evidence.sys.executable,
                "-m",
                "tools.oled_smoke",
                "--hold-ms",
                "500",
            ],
            commands,
        )

    def test_capture_returns_structured_error_when_ffmpeg_times_out(self):
        output = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            process = TimeoutProcess(output_dir / "oled-camera.mp4")

            def runner(command, **kwargs):
                if command[0] == "screencapture":
                    Path(command[-1]).write_bytes(b"screen")
                return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}\n', stderr="")

            exit_code = jks_visual_evidence.main(
                [
                    "--camera-device",
                    "2",
                    "--output-dir",
                    str(output_dir),
                    "--seconds",
                    "1",
                    "--hold-ms",
                    "500",
                ],
                stdout=output,
                runner=runner,
                popen_factory=lambda *args, **kwargs: process,
                sleeper=lambda _: None,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertTrue(process.terminated)
        self.assertEqual(payload["errors"][0], {"error": "camera_timeout", "message": "ffmpeg timed out after 6s"})


if __name__ == "__main__":
    unittest.main()
