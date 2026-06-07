"""Probe local microphone recording without sending audio to any service."""

from __future__ import annotations

import json
from queue import Queue
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Optional, Sequence, TextIO
import wave

from jks.audio import AudioRecorder


DEFAULT_DURATION_SECONDS = 1.0
DEFAULT_MIN_RMS = 0.0
DEFAULT_TIMEOUT_SECONDS = 10.0


def _empty_summary() -> dict[str, object]:
    return {"ok": False, "checks": {}, "errors": []}


def _parse_args(argv: Sequence[str]) -> tuple[float, float, Optional[float], list[dict[str, str]]]:
    duration = DEFAULT_DURATION_SECONDS
    min_rms = DEFAULT_MIN_RMS
    timeout = None
    errors: list[dict[str, str]] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--duration":
            if index + 1 >= len(argv):
                errors.append({"error": "args", "message": "--duration requires seconds"})
                break
            try:
                duration = float(argv[index + 1])
            except ValueError:
                errors.append({"error": "args", "message": "--duration must be a number"})
                break
            if duration <= 0:
                errors.append({"error": "args", "message": "--duration must be positive"})
                break
            index += 2
            continue
        if arg == "--min-rms":
            if index + 1 >= len(argv):
                errors.append({"error": "args", "message": "--min-rms requires a value"})
                break
            try:
                min_rms = float(argv[index + 1])
            except ValueError:
                errors.append({"error": "args", "message": "--min-rms must be a number"})
                break
            if min_rms < 0:
                errors.append({"error": "args", "message": "--min-rms must be non-negative"})
                break
            index += 2
            continue
        if arg == "--timeout":
            if index + 1 >= len(argv):
                errors.append({"error": "args", "message": "--timeout requires seconds"})
                break
            try:
                timeout = float(argv[index + 1])
            except ValueError:
                errors.append({"error": "args", "message": "--timeout must be a number"})
                break
            if timeout <= 0:
                errors.append({"error": "args", "message": "--timeout must be positive"})
                break
            index += 2
            continue
        errors.append({"error": "args", "message": f"unsupported argument: {arg}"})
        index += 1
    return duration, min_rms, timeout, errors


def _analyze_wav(path: Path) -> dict[str, object]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.getnframes()
        raw = wav.readframes(frames)
    if channels < 1:
        raise ValueError("recording has no channels")
    samples = _pcm_samples(raw, sample_width)
    scale = float(2 ** (8 * sample_width - 1))
    if samples:
        rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5 / scale
        peak = max(abs(sample) for sample in samples) / scale
    else:
        rms = 0.0
        peak = 0.0
    return {
        "path": str(path),
        "bytes": Path(path).stat().st_size,
        "frames": frames,
        "channels": channels,
        "sample_width": sample_width,
        "sample_rate": sample_rate,
        "rms": rms,
        "peak": peak,
    }


def _pcm_samples(raw: bytes, sample_width: int) -> list[int]:
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError(f"unsupported WAV sample width: {sample_width}")
    if sample_width == 1:
        return [byte - 128 for byte in raw]

    samples = []
    for offset in range(0, len(raw) - (len(raw) % sample_width), sample_width):
        chunk = raw[offset : offset + sample_width]
        if sample_width == 3:
            sign = b"\xff" if chunk[-1] & 0x80 else b"\x00"
            chunk = chunk + sign
        samples.append(int.from_bytes(chunk, "little", signed=True))
    return samples


def run_mic_probe(argv: Sequence[str]) -> dict[str, object]:
    summary = _empty_summary()
    duration, min_rms, timeout, errors = _parse_args(argv)
    if errors:
        summary["errors"] = errors
        return summary

    deadline = timeout if timeout is not None else max(DEFAULT_TIMEOUT_SECONDS, duration + 5.0)
    results: Queue[dict[str, object]] = Queue(maxsize=1)

    def worker() -> None:
        results.put(_run_recording_probe(duration, min_rms))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(deadline)
    if thread.is_alive():
        summary["errors"] = [
            {
                "error": "mic_timeout",
                "message": f"microphone probe timed out after {deadline:g}s",
            }
        ]
        return summary
    if results.empty():
        summary["errors"] = [{"error": "mic", "message": "microphone probe returned no result"}]
        return summary
    return results.get()


def _run_recording_probe(duration: float, min_rms: float) -> dict[str, object]:
    summary = _empty_summary()
    try:
        output_dir = Path(tempfile.gettempdir()) / "jks-mic-probe"
        output_dir.mkdir(parents=True, exist_ok=True)
        recorder = AudioRecorder(output_dir=output_dir)
        recorder.start_recording()
        time.sleep(duration)
        audio_path = recorder.stop_recording()
        checks = _analyze_wav(audio_path)
        checks["duration_seconds"] = duration
        checks["min_rms"] = min_rms
        checks["started"] = bool(getattr(recorder, "started", True))
        checks["stopped"] = bool(getattr(recorder, "stopped", True))
        summary["checks"] = checks
        if checks["rms"] < min_rms:
            summary["errors"] = [
                {
                    "error": "mic_signal",
                    "message": f"recorded RMS {checks['rms']:.6f} below threshold {min_rms:.6f}",
                }
            ]
            return summary
    except Exception as exc:
        summary["errors"] = [{"error": "mic", "message": str(exc)}]
        return summary

    summary["ok"] = True
    return summary


def main(argv: Optional[Sequence[str]] = None, stdout: TextIO = sys.stdout) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    summary = run_mic_probe(args)
    stdout.write(json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
