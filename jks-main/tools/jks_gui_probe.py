"""Run a real Tk JKS button probe with a provided audio file."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from typing import Optional, Sequence, TextIO

from jks.app import JksApp, build_orchestrator
from jks.audio import AudioPlayer
from jks.config import load_config
from jks.display import open_serial_output
from jks.preflight import analyze_config
from tools.jks_app_probe import (
    DEFAULT_DISPLAY_ACK_TIMEOUT,
    FileRecorder,
    NoOpPlayer,
    ProbeOrchestrator,
    _close_display,
    _display_checks,
    _drain_display_input,
    _dumps_compact_redacted_safe,
    _read_display_acks,
)
from tools.jks_probe_summary import summarize_agent_reply


DEFAULT_GUI_TIMEOUT = 120.0


def _empty_summary() -> dict[str, object]:
    return {
        "ok": False,
        "preflight": {},
        "checks": {},
        "server_events": [],
        "display_events": [],
        "errors": [],
    }


def _preflight_summary(preflight: dict[str, object]) -> dict[str, object]:
    agent = preflight.get("agent", {})
    speech = preflight.get("speech", {})
    oled = preflight.get("oled", {})
    return {
        "ok": bool(preflight.get("ok")),
        "ready_for_real": bool(preflight.get("ready_for_real", preflight.get("ok"))),
        "agent_mode": str(agent.get("mode", "")) if isinstance(agent, dict) else "",
        "speech_mode": str(speech.get("mode", "")) if isinstance(speech, dict) else "",
        "oled_mode": str(oled.get("mode", "")) if isinstance(oled, dict) else "",
        "missing_count": len(preflight.get("missing", [])) if isinstance(preflight.get("missing", []), list) else 0,
        "warning_count": len(preflight.get("warnings", [])) if isinstance(preflight.get("warnings", []), list) else 0,
    }


def _parse_args(
    argv: Sequence[str],
) -> tuple[Optional[Path], bool, bool, float, float, bool, bool, list[dict[str, str]]]:
    audio_path: Optional[Path] = None
    play = False
    require_display_ack = False
    display_ack_timeout = DEFAULT_DISPLAY_ACK_TIMEOUT
    gui_timeout = DEFAULT_GUI_TIMEOUT
    show = False
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
        if arg == "--gui-timeout":
            if index + 1 >= len(argv):
                errors.append({"error": "args", "message": "--gui-timeout requires seconds"})
                break
            try:
                gui_timeout = float(argv[index + 1])
            except ValueError:
                errors.append({"error": "args", "message": "--gui-timeout must be a number"})
                break
            if gui_timeout <= 0:
                errors.append({"error": "args", "message": "--gui-timeout must be positive"})
                break
            index += 2
            continue
        if arg == "--show":
            show = True
            index += 1
            continue
        if arg == "--verbose":
            verbose = True
            index += 1
            continue
        errors.append({"error": "args", "message": f"unsupported argument: {arg}"})
        index += 1

    if audio_path is None and not errors:
        errors.append({"error": "audio", "message": "--audio is required"})
    return audio_path, play, require_display_ack, display_ack_timeout, gui_timeout, show, verbose, errors


def _root_title(root) -> str:
    try:
        return str(root.title())
    except TypeError:
        return ""


def _button_option(button, name: str) -> str:
    try:
        return str(button.cget(name))
    except Exception:
        return str(getattr(button, name, ""))


def _var_value(var) -> str:
    try:
        return str(var.get())
    except Exception:
        return ""


def _invoke(button) -> None:
    result = button.invoke()
    if result is False:
        raise RuntimeError("button invoke failed")


def _run_button_mainloop(root, ui, probe_orchestrator, gui_timeout: float) -> Optional[str]:
    error: list[str] = []

    def fail(message: str) -> None:
        error.append(message)
        try:
            root.quit()
        except Exception:
            return None
        return None

    def click_start() -> None:
        try:
            _invoke(ui.button)
        except Exception as exc:
            fail(str(exc))
            return
        root.after(50, click_stop)

    def click_stop() -> None:
        try:
            _invoke(ui.button)
        except Exception as exc:
            fail(str(exc))
            return
        root.after(50, monitor)

    def monitor() -> None:
        if (
            probe_orchestrator.last_result is not None
            and _button_option(ui.button, "text") == "Speak"
            and _button_option(ui.button, "state") == "normal"
        ):
            root.quit()
            return
        if probe_orchestrator.last_error is not None:
            fail(str(probe_orchestrator.last_error))
            return
        root.after(50, monitor)

    def timeout() -> None:
        if probe_orchestrator.last_result is None:
            fail(f"GUI probe did not finish a voice turn: {_var_value(ui.status)}")
            return
        root.quit()

    root.after(0, click_start)
    root.after(int(gui_timeout * 1000), timeout)
    root.mainloop()
    return error[0] if error else None


def run_gui_probe(argv: Sequence[str]) -> dict[str, object]:
    summary = _empty_summary()
    (
        audio_path,
        play,
        require_display_ack,
        display_ack_timeout,
        gui_timeout,
        show,
        verbose,
        errors,
    ) = _parse_args(argv)
    if errors:
        summary["errors"] = errors
        return summary

    assert audio_path is not None
    if not audio_path.exists():
        summary["errors"] = [{"error": "audio", "message": f"audio file not found: {audio_path}"}]
        return summary

    config = load_config()
    preflight = analyze_config(config)
    summary["preflight"] = _preflight_summary(preflight)
    if not preflight.get("ok"):
        return summary

    recorder = FileRecorder(audio_path)
    player = AudioPlayer() if play else NoOpPlayer()
    status_events: list[str] = []
    display_status: list[str] = []
    display_errors: list[str] = []
    output_dir = Path(tempfile.gettempdir()) / "jks-gui-probe"
    root = None
    orchestrator = None
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

        root = tk.Tk()
        if not show:
            root.withdraw()
        ui = JksApp(root, orchestrator=probe_orchestrator)
        root.update_idletasks()
        root.update()
        mainloop_error = _run_button_mainloop(root, ui, probe_orchestrator, gui_timeout)
        if mainloop_error:
            raise RuntimeError(mainloop_error)
        if probe_orchestrator.last_result is None:
            detail = str(probe_orchestrator.last_error or _var_value(ui.status))
            raise RuntimeError(f"GUI probe did not finish a voice turn: {detail}")

        result = probe_orchestrator.last_result
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
                {"ack_present": True, "ack_detail": str(ack.get("detail", "")), "ack_ok": ack.get("status") in (None, "ok")}
                for ack in acks
            ]
            errors.extend(ack_errors)

        if play and result.audio_error:
            errors.append({"error": "playback", "message": result.audio_error})

        checks = {
            "gui": {
                "created": True,
                "shown": show,
                "title": _root_title(root),
                "clicks": 2,
                "button_text": _button_option(ui.button, "text"),
                "button_state": _button_option(ui.button, "state"),
                "status": _var_value(ui.status),
                "transcript_length": len(_var_value(ui.transcript)),
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
                        "display_text": None,
                        "duration_ms": None,
                        "intensity": None,
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
        errors.append({"error": "gui_probe", "message": str(exc)})
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
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
        summary = run_gui_probe(args)
    except Exception as exc:
        summary = _empty_summary()
        summary["errors"] = [{"error": "config", "message": str(exc)}]
    stdout.write(_dumps_compact_redacted_safe(summary) + "\n")
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
