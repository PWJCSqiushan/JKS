"""Run the no-GUI app orchestrator path with a provided audio file."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Optional, Sequence, TextIO

from jks import app as app_module
from jks.app import JksApp, build_orchestrator
from jks.audio import AudioPlayer
from jks.config import load_config
from jks.display import open_serial_output
from jks.preflight import analyze_config
from tools.jks_probe_summary import summarize_agent_reply, summarize_preflight


DEFAULT_DISPLAY_ACK_TIMEOUT = 2.5
EXPECTED_DISPLAY_ACKS = 5


class FileRecorder:
    def __init__(self, audio_path: Path):
        self.audio_path = Path(audio_path)
        self.started = False
        self.stopped = False

    def start_recording(self) -> None:
        self.started = True

    def stop_recording(self) -> Path:
        if not self.started:
            raise RuntimeError("recording was not started")
        self.stopped = True
        return self.audio_path


class NoOpPlayer(AudioPlayer):
    def __init__(self):
        self.played = []
        self.streamed_chunks = []

    def play(self, audio_path: Path) -> None:
        self.played.append(Path(audio_path))

    def play_stream(self, chunks, suffix=".mp3") -> None:
        for chunk in chunks:
            if chunk:
                self.streamed_chunks.append(bytes(chunk))


class FakeRoot:
    def __init__(self):
        self.after_calls = []
        self.title_text = ""
        self.geometry_value = None
        self.minsize_value = None

    def title(self, text):
        self.title_text = text

    def geometry(self, value):
        self.geometry_value = value

    def minsize(self, width, height):
        self.minsize_value = (width, height)

    def after(self, delay_ms, callback):
        self.after_calls.append(delay_ms)
        callback()


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

    def pack(self, **kwargs):
        return None

    def configure(self, **kwargs):
        self.options.update(kwargs)
        if "text" in kwargs:
            self.text = kwargs["text"]


class FakeLabel:
    def __init__(self, root, **kwargs):
        self.root = root
        self.kwargs = kwargs

    def pack(self, **kwargs):
        return None


class ImmediateThread:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


class FakeThreadingModule:
    Thread = ImmediateThread


class NoGuiWidgets:
    def __enter__(self):
        self._old_string_var = app_module.tk.StringVar
        self._old_button = app_module.ttk.Button
        self._old_label = app_module.ttk.Label
        self._old_threading = app_module.threading
        app_module.tk.StringVar = FakeStringVar
        app_module.ttk.Button = FakeButton
        app_module.ttk.Label = FakeLabel
        app_module.threading = FakeThreadingModule
        return self

    def __exit__(self, exc_type, exc, traceback):
        app_module.tk.StringVar = self._old_string_var
        app_module.ttk.Button = self._old_button
        app_module.ttk.Label = self._old_label
        app_module.threading = self._old_threading
        return False


class ProbeOrchestrator:
    def __init__(self, inner):
        self.inner = inner
        self.starts = 0
        self.finishes = 0
        self.run_voice_turn_calls = 0
        self.last_result = None
        self.last_error = None

    @property
    def display(self):
        return self.inner.display

    def start_recording(self):
        self.starts += 1
        return self.inner.start_recording()

    def finish_voice_turn(self):
        self.finishes += 1
        try:
            self.last_result = self.inner.finish_voice_turn()
        except Exception as exc:
            self.last_error = exc
            raise
        return self.last_result

    def run_voice_turn(self):
        self.run_voice_turn_calls += 1
        raise RuntimeError("app probe must use split start/finish recording")


def _empty_summary() -> dict[str, object]:
    return {
        "ok": False,
        "preflight": {},
        "checks": {},
        "server_events": [],
        "display_events": [],
        "errors": [],
    }


def _parse_args(argv: Sequence[str]) -> tuple[Optional[Path], bool, bool, float, bool, list[dict[str, str]]]:
    audio_path: Optional[Path] = None
    play = False
    require_display_ack = False
    display_ack_timeout = DEFAULT_DISPLAY_ACK_TIMEOUT
    verbose = False
    errors: list[dict[str, str]] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--audio":
            if index + 1 >= len(argv):
                errors.append({"error": "audio", "message": "--audio requires a path"})
                break
            audio_path = Path(argv[index + 1])
            index += 2
            continue
        if arg == "--play":
            play = True
            index += 1
            continue
        if arg == "--require-display-ack":
            require_display_ack = True
            index += 1
            continue
        if arg == "--display-ack-timeout":
            if index + 1 >= len(argv):
                errors.append({"error": "args", "message": "--display-ack-timeout requires seconds"})
                break
            try:
                display_ack_timeout = float(argv[index + 1])
            except ValueError:
                errors.append({"error": "args", "message": "--display-ack-timeout must be a number"})
                break
            if display_ack_timeout <= 0:
                errors.append({"error": "args", "message": "--display-ack-timeout must be positive"})
                break
            index += 2
            continue
        if arg == "--verbose":
            verbose = True
            index += 1
            continue
        errors.append({"error": "args", "message": f"unsupported argument: {arg}"})
        index += 1

    if audio_path is None and not errors:
        errors.append({"error": "audio", "message": "--audio is required"})
    return audio_path, play, require_display_ack, display_ack_timeout, verbose, errors


def _dumps_compact_redacted_safe(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(": ", "\\u003a ")


def _ack_detail(ack: dict[str, object]) -> str:
    return str(ack.get("detail", ack.get("cmd", "")))


def _ack_is_ok(ack: dict[str, object]) -> bool:
    status = ack.get("status")
    if status is not None and status != "ok":
        return False
    return ack.get("ok") is not False


def _read_display_acks(
    display,
    expected_details: Sequence[str],
    timeout: float,
) -> tuple[list[dict[str, object]], list[dict[str, str]], list[str]]:
    acks: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    skipped: list[str] = []
    for expected in expected_details:
        deadline = time.monotonic() + timeout
        while True:
            remaining = max(deadline - time.monotonic(), 0.0)
            if remaining <= 0:
                errors.append({"error": "display_ack", "message": f"missing OLED ACK for {expected}"})
                return acks, errors, skipped
            try:
                ack = display.read_ack(timeout=remaining)
            except Exception as exc:
                skipped.append(f"invalid:{exc.__class__.__name__}")
                continue
            if ack is None:
                errors.append({"error": "display_ack", "message": f"missing OLED ACK for {expected}"})
                return acks, errors, skipped
            detail = _ack_detail(ack)
            if detail != expected:
                skipped.append(detail)
                continue
            acks.append(ack)
            if not _ack_is_ok(ack):
                errors.append({"error": "display_ack", "message": f"OLED ACK was not ok: {detail}"})
                return acks, errors, skipped
            break
    return acks, errors, skipped


def _drain_display_input(display, timeout: float = 0.05) -> list[str]:
    details = []
    while True:
        try:
            ack = display.read_ack(timeout=timeout)
        except Exception as exc:
            details.append(f"invalid:{exc.__class__.__name__}")
            continue
        if ack is None:
            return details
        details.append(_ack_detail(ack))


def _display_checks(
    require_display_ack: bool,
    acks: list[dict[str, object]],
    errors: list[dict[str, str]],
    drained_details: list[str],
    skipped_details: list[str],
) -> dict[str, object]:
    missing_count = max(EXPECTED_DISPLAY_ACKS - len(acks), 0) if require_display_ack else 0
    return {
        "require_ack": require_display_ack,
        "event_count": EXPECTED_DISPLAY_ACKS,
        "ack_count": len(acks),
        "ack_details": [_ack_detail(ack) for ack in acks],
        "drained_count": len(drained_details),
        "skipped_count": len(skipped_details),
        "skipped_details": skipped_details[:10],
        "missing": [f"ack_{index + 1}" for index in range(len(acks), len(acks) + missing_count)],
        "errors": errors,
    }


def _close_display(orchestrator) -> None:
    display_output = getattr(getattr(orchestrator, "display", None), "_output", None)
    close = getattr(display_output, "close", None)
    if close is None:
        return None
    try:
        close()
    except Exception:
        return None
    return None


def run_app_probe(argv: Sequence[str]) -> dict[str, object]:
    summary = _empty_summary()
    audio_path, play, require_display_ack, display_ack_timeout, verbose, errors = _parse_args(argv)
    if errors:
        summary["errors"] = errors
        return summary

    assert audio_path is not None
    if not audio_path.exists():
        summary["errors"] = [{"error": "audio", "message": f"audio file not found: {audio_path}"}]
        return summary

    config = load_config()
    preflight = analyze_config(config)
    summary["preflight"] = summarize_preflight(preflight)
    if not preflight.get("ok"):
        return summary

    recorder = FileRecorder(audio_path)
    player = AudioPlayer() if play else NoOpPlayer()
    status_events: list[str] = []
    display_status: list[str] = []
    display_errors: list[str] = []
    output_dir = Path(tempfile.gettempdir()) / "jks-app-probe"
    orchestrator = None
    probe_orchestrator: Optional[ProbeOrchestrator] = None
    ui = None
    checks: dict[str, object] = {}
    display_events: list[dict[str, object]] = []
    drained_display_details: list[str] = []
    skipped_display_details: list[str] = []

    try:
        orchestrator = build_orchestrator(
            config,
            open_serial=open_serial_output,
            output_dir=output_dir,
            recorder=recorder,
            player=player,
            status_callback=lambda state: status_events.append(str(getattr(state, "value", state))),
            display_status_callback=display_status.append,
            display_error_callback=display_errors.append,
        )
        probe_orchestrator = ProbeOrchestrator(orchestrator)
        if require_display_ack:
            drained_display_details = _drain_display_input(orchestrator.display)
        with NoGuiWidgets():
            ui = JksApp(FakeRoot(), orchestrator=probe_orchestrator)
            ui.start_turn()
            ui.start_turn()

        result = probe_orchestrator.last_result
        if result is None:
            detail = str(probe_orchestrator.last_error or ui.status.get())
            raise RuntimeError(f"app probe did not finish a voice turn: {detail}")

        acks: list[dict[str, object]] = []
        ack_errors: list[dict[str, str]] = []
        if require_display_ack:
            expected_details = ["listening", "thinking", "thinking", "speaking", result.emotion]
            acks, ack_errors, skipped_display_details = _read_display_acks(
                orchestrator.display,
                expected_details,
                display_ack_timeout,
            )
            display_events = [
                {"ack_present": True, "ack_detail": _ack_detail(ack), "ack_ok": _ack_is_ok(ack)}
                for ack in acks
            ]
            errors.extend(ack_errors)

        if play and result.audio_error:
            errors.append({"error": "playback", "message": result.audio_error})

        checks = {
            "ui": {
                "clicks": 2,
                "button_text": getattr(ui.button, "text", ""),
                "button_state": str(getattr(ui.button, "options", {}).get("state", "")),
                "status": ui.status.get(),
                "status_history": list(ui.status.history),
                "transcript_length": len(ui.transcript.get()),
            },
            "recording": {"started": recorder.started, "stopped": recorder.stopped},
            "orchestrator": {
                "start_calls": probe_orchestrator.starts,
                "finish_calls": probe_orchestrator.finishes,
                "run_voice_turn_calls": probe_orchestrator.run_voice_turn_calls,
            },
            "stt": {"text_length": len(result.user_text)},
            "agent": summarize_agent_reply(
                type(
                    "ReplySummary",
                    (),
                    {
                        "text": result.agent_text,
                        "emotion": result.emotion,
                        "display_text": getattr(result, "display_text", None),
                        "duration_ms": getattr(result, "display_duration_ms", None),
                        "intensity": getattr(result, "display_intensity", None),
                    },
                )(),
                mode=str(preflight.get("agent", {}).get("mode", "http")),
            ),
            "playback": {"played": play, **({"audio_error": result.audio_error} if result.audio_error else {})},
            "display": _display_checks(
                require_display_ack,
                acks,
                ack_errors,
                drained_display_details,
                skipped_display_details,
            ),
            "status_events": status_events,
            "display_status": display_status,
            "display_errors": display_errors,
        }
        if verbose:
            checks["stt"]["text"] = result.user_text
            checks["agent"]["text"] = result.agent_text
    except Exception as exc:
        errors.append({"error": "app_probe", "message": str(exc)})
    finally:
        if orchestrator is not None:
            _close_display(orchestrator)

    summary["checks"] = checks
    summary["server_events"] = ["stt", "chat", "tts"] if not errors or checks.get("stt") else []
    summary["display_events"] = display_events
    summary["errors"] = errors
    summary["ok"] = not errors and bool(checks)
    return summary


def main(argv: Optional[Sequence[str]] = None, stdout: TextIO = sys.stdout) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    try:
        summary = run_app_probe(args)
    except Exception as exc:
        summary = _empty_summary()
        summary["errors"] = [{"error": "config", "message": str(exc)}]
    stdout.write(_dumps_compact_redacted_safe(summary) + "\n")
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
