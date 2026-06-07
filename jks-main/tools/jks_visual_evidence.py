"""Capture screen and camera evidence while cycling OLED visual states."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Optional, Sequence, TextIO


DEFAULT_OUTPUT_DIR = Path("/tmp/jks-acceptance-evidence")
DEFAULT_SECONDS = 20.0
DEFAULT_HOLD_MS = 1000
DEFAULT_VIDEO_SIZE = "1920x1440"
DEFAULT_FRAMERATE = "30"


def _empty_summary() -> dict[str, object]:
    return {"ok": False, "errors": []}


def _parse_args(argv: Sequence[str]) -> tuple[dict[str, object], list[dict[str, str]]]:
    options: dict[str, object] = {
        "camera_device": "",
        "output_dir": DEFAULT_OUTPUT_DIR,
        "seconds": DEFAULT_SECONDS,
        "hold_ms": DEFAULT_HOLD_MS,
        "video_size": DEFAULT_VIDEO_SIZE,
        "framerate": DEFAULT_FRAMERATE,
        "list_devices": False,
    }
    errors: list[dict[str, str]] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--list-devices":
            options["list_devices"] = True
            index += 1
            continue
        if arg in {"--camera-device", "--output-dir", "--seconds", "--hold-ms", "--video-size", "--framerate"}:
            if index + 1 >= len(argv):
                errors.append({"error": "args", "message": f"{arg} requires a value"})
                break
            value = argv[index + 1]
            if arg == "--camera-device":
                options["camera_device"] = value
            elif arg == "--output-dir":
                options["output_dir"] = Path(value)
            elif arg == "--seconds":
                try:
                    seconds = float(value)
                except ValueError:
                    errors.append({"error": "args", "message": "--seconds must be a number"})
                    break
                if seconds <= 0:
                    errors.append({"error": "args", "message": "--seconds must be positive"})
                    break
                options["seconds"] = seconds
            elif arg == "--hold-ms":
                try:
                    hold_ms = int(value)
                except ValueError:
                    errors.append({"error": "args", "message": "--hold-ms must be an integer"})
                    break
                if hold_ms < 0:
                    errors.append({"error": "args", "message": "--hold-ms must be non-negative"})
                    break
                options["hold_ms"] = hold_ms
            elif arg == "--video-size":
                options["video_size"] = value
            elif arg == "--framerate":
                options["framerate"] = value
            index += 2
            continue
        errors.append({"error": "args", "message": f"unsupported argument: {arg}"})
        index += 1

    if not options["list_devices"] and not options["camera_device"] and not errors:
        errors.append({"error": "args", "message": "--camera-device is required"})
    return options, errors


def run_visual_evidence(
    argv: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    options, errors = _parse_args(argv)
    if errors:
        summary = _empty_summary()
        summary["errors"] = errors
        return summary

    if options["list_devices"]:
        return _list_devices(runner)

    output_dir = Path(options["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    camera_video = output_dir / "oled-camera.mp4"
    screenshot = output_dir / "desktop-screen.png"

    ffmpeg = popen_factory(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-f",
            "avfoundation",
            "-framerate",
            str(options["framerate"]),
            "-video_size",
            str(options["video_size"]),
            "-t",
            _format_number(float(options["seconds"])),
            "-i",
            f"{options['camera_device']}:none",
            str(camera_video),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sleeper(1.0)
    screen_result = runner(["screencapture", "-x", str(screenshot)], capture_output=True, text=True)
    smoke_result = runner(
        [sys.executable, "-m", "tools.oled_smoke", "--hold-ms", str(options["hold_ms"])],
        capture_output=True,
        text=True,
    )
    camera_wait_timeout = float(options["seconds"]) + 5.0
    camera_returncode, camera_timeout = _wait_camera(ffmpeg, camera_wait_timeout)

    summary = {
        "ok": False,
        "camera_video": str(camera_video),
        "desktop_screenshot": str(screenshot),
        "camera_returncode": camera_returncode,
        "screen_returncode": screen_result.returncode,
        "oled_smoke_returncode": smoke_result.returncode,
        "oled_smoke": _parse_json(smoke_result.stdout),
        "visual_review_required": True,
        "errors": [],
    }
    if camera_timeout:
        summary["errors"].append(
            {
                "error": "camera_timeout",
                "message": f"ffmpeg timed out after {_format_number(camera_wait_timeout)}s",
            }
        )
    if camera_returncode != 0:
        summary["errors"].append({"error": "camera", "message": f"ffmpeg exited {camera_returncode}"})
    if screen_result.returncode != 0:
        summary["errors"].append({"error": "screen", "message": "screencapture failed"})
    if smoke_result.returncode != 0:
        summary["errors"].append({"error": "oled_smoke", "message": "OLED smoke failed"})
    if not camera_video.exists():
        summary["errors"].append({"error": "camera", "message": "camera video was not created"})
    if not screenshot.exists():
        summary["errors"].append({"error": "screen", "message": "desktop screenshot was not created"})
    summary["ok"] = not summary["errors"]
    return summary


def _wait_camera(process, timeout: float) -> tuple[int, bool]:
    try:
        return int(process.wait(timeout=timeout)), False
    except subprocess.TimeoutExpired:
        try:
            process.terminate()
        except Exception:
            pass
        try:
            return int(process.wait(timeout=2.0)), True
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception:
                pass
            return -1, True


def _list_devices(runner: Callable[..., subprocess.CompletedProcess]) -> dict[str, object]:
    command = ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
    result = runner(command, capture_output=True, text=True)
    devices = (result.stdout or "") + (result.stderr or "")
    listed = "AVFoundation video devices:" in devices or "AVFoundation audio devices:" in devices
    ok = result.returncode == 0 or listed
    return {
        "ok": ok,
        "devices": devices,
        "errors": [] if ok else [{"error": "ffmpeg", "message": f"ffmpeg exited {result.returncode}"}],
    }


def _parse_json(value: str) -> dict[str, object]:
    try:
        payload = json.loads(value)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _format_number(value: float) -> str:
    return f"{value:g}"


def main(
    argv: Optional[Sequence[str]] = None,
    stdout: TextIO = sys.stdout,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    summary = run_visual_evidence(
        args,
        runner=runner,
        popen_factory=popen_factory,
        sleeper=sleeper,
    )
    stdout.write(json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
