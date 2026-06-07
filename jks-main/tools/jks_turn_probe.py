"""Run one configured STT -> Agent -> TTS turn from a provided WAV file."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from typing import Optional, Sequence, TextIO
from uuid import uuid4

from jks.agent import build_agent_client
from jks.audio import AudioPlayer
from jks.config import load_config
from jks.display import DisplayController, DisplayIntent, open_serial_output
from jks.expression import ExpressionEngine, TurnState
from jks.preflight import analyze_config
from jks.speech import build_speech_client
from tools.jks_probe_summary import summarize_agent_reply, summarize_preflight


DISPLAY_ACK_TIMEOUT = 2.5


def _empty_summary() -> dict[str, object]:
    return {
        "ok": False,
        "preflight": {},
        "checks": {},
        "server_events": [],
        "display_events": [],
        "errors": [],
    }


def _parse_args(argv: Sequence[str]) -> tuple[Optional[Path], bool, bool, bool, bool, float, list[dict[str, str]]]:
    audio_path: Optional[Path] = None
    play = False
    verbose = False
    display = False
    require_display_ack = False
    display_ack_timeout = DISPLAY_ACK_TIMEOUT
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
        if arg == "--verbose":
            verbose = True
            index += 1
            continue
        if arg == "--display":
            display = True
            index += 1
            continue
        if arg == "--require-display-ack":
            display = True
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
        errors.append({"error": "args", "message": f"unsupported argument: {arg}"})
        index += 1

    if audio_path is None and not errors:
        errors.append({"error": "audio", "message": "--audio is required"})
    return audio_path, play, verbose, display, require_display_ack, display_ack_timeout, errors


def _dumps_compact_redacted_safe(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(": ", "\\u003a ")


def _ack_detail(ack: dict[str, object]) -> str:
    return str(ack.get("detail", ack.get("cmd", "")))


def _ack_is_ok(ack: dict[str, object]) -> bool:
    status = ack.get("status")
    if status is not None and status != "ok":
        return False
    return ack.get("ok") is not False


def _display_checks(
    display_enabled: bool,
    require_ack: bool,
    display_events: list[dict[str, object]],
) -> dict[str, object]:
    missing = [
        str(event["stage"])
        for event in display_events
        if require_ack and not event.get("ack_present")
    ]
    return {
        "enabled": display_enabled,
        "require_ack": require_ack,
        "event_count": len(display_events),
        "ack_count": sum(1 for event in display_events if event.get("ack_present")),
        "missing": missing,
    }


def _show_display(
    *,
    display: Optional[DisplayController],
    stage: str,
    intent: DisplayIntent,
    require_ack: bool,
    ack_timeout: float,
    display_events: list[dict[str, object]],
    errors: list[dict[str, str]],
) -> bool:
    if display is None:
        return True

    event: dict[str, object] = {
        "stage": stage,
        "emotion": intent.emotion,
        "text_length": len(intent.text),
        "ack_present": False,
    }
    try:
        display.show(intent)
    except Exception as exc:
        event["write_ok"] = False
        display_events.append(event)
        errors.append({"error": "display", "stage": stage, "message": str(exc)})
        return False

    event["write_ok"] = True
    if require_ack:
        try:
            ack = display.read_ack(timeout=ack_timeout)
        except Exception as exc:
            display_events.append(event)
            errors.append({"error": "display_ack", "stage": stage, "message": str(exc)})
            return False

        if ack is None:
            display_events.append(event)
            errors.append({"error": "display_ack", "stage": stage, "message": "missing OLED ACK"})
            return False

        event["ack_present"] = True
        event["ack_detail"] = _ack_detail(ack)
        if not _ack_is_ok(ack):
            display_events.append(event)
            errors.append(
                {
                    "error": "display_ack",
                    "stage": stage,
                    "message": f"OLED ACK was not ok: {_ack_detail(ack)}",
                }
            )
            return False

    display_events.append(event)
    return True


def _open_display_controller(config) -> tuple[Optional[object], Optional[DisplayController], Optional[dict[str, str]]]:
    try:
        opened_port = open_serial_output(config.oled_port, config.oled_baud)
    except Exception as exc:
        return None, None, {"error": "display", "message": str(exc)}
    return opened_port, DisplayController(opened_port, ack_input=opened_port), None


def _close_display_port(display_port: Optional[object]) -> None:
    if display_port is None:
        return None
    try:
        display_port.close()
    except Exception:
        return None
    return None


def run_turn_probe(argv: Sequence[str]) -> dict[str, object]:
    summary = _empty_summary()
    (
        audio_path,
        play,
        verbose,
        display_enabled,
        require_display_ack,
        display_ack_timeout,
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
    summary["preflight"] = summarize_preflight(preflight)
    if not preflight.get("ok"):
        return summary

    checks: dict[str, object] = {}
    server_events: list[str] = []
    display_events: list[dict[str, object]] = []
    errors = []
    output_dir = Path(tempfile.gettempdir()) / "jks-turn-probe"
    speech = build_speech_client(config, output_dir)
    agent = build_agent_client(config)
    expression = ExpressionEngine()
    display_port = None
    display: Optional[DisplayController] = None

    if display_enabled:
        display_port, display, display_error = _open_display_controller(config)
        if display_error is not None:
            errors.append(display_error)
            checks["display"] = _display_checks(display_enabled, require_display_ack, display_events)
            summary["checks"] = checks
            summary["display_events"] = display_events
            summary["errors"] = errors
            return summary

    try:
        if not _show_display(
            display=display,
            stage="listening",
            intent=expression.intent_for_state(TurnState.LISTENING),
            require_ack=require_display_ack,
            ack_timeout=display_ack_timeout,
            display_events=display_events,
            errors=errors,
        ):
            checks["display"] = _display_checks(display_enabled, require_display_ack, display_events)
            summary["checks"] = checks
            summary["display_events"] = display_events
            summary["errors"] = errors
            _close_display_port(display_port)
            return summary

        if not _show_display(
            display=display,
            stage="transcribing",
            intent=expression.intent_for_state(TurnState.TRANSCRIBING),
            require_ack=require_display_ack,
            ack_timeout=display_ack_timeout,
            display_events=display_events,
            errors=errors,
        ):
            checks["display"] = _display_checks(display_enabled, require_display_ack, display_events)
            summary["checks"] = checks
            summary["display_events"] = display_events
            summary["errors"] = errors
            _close_display_port(display_port)
            return summary

        user_text = speech.transcribe(audio_path)
        server_events.append("stt")
        checks["stt"] = {"text_length": len(user_text)}
        if verbose:
            checks["stt"]["text"] = user_text
    except Exception as exc:
        errors.append({"error": "stt", "message": str(exc)})
        summary["checks"] = checks
        summary["server_events"] = server_events
        summary["display_events"] = display_events
        summary["errors"] = errors
        _close_display_port(display_port)
        return summary

    try:
        if not _show_display(
            display=display,
            stage="thinking",
            intent=expression.intent_for_state(TurnState.THINKING),
            require_ack=require_display_ack,
            ack_timeout=display_ack_timeout,
            display_events=display_events,
            errors=errors,
        ):
            checks["display"] = _display_checks(display_enabled, require_display_ack, display_events)
            summary["checks"] = checks
            summary["server_events"] = server_events
            summary["display_events"] = display_events
            summary["errors"] = errors
            _close_display_port(display_port)
            return summary

        reply = agent.send_message(user_text, f"turn-probe-{uuid4().hex}")
        server_events.append("chat")
        checks["agent"] = summarize_agent_reply(
            reply,
            mode=str(preflight.get("agent", {}).get("mode", "http")),
        )
        if verbose:
            checks["agent"]["text"] = reply.text
    except Exception as exc:
        errors.append({"error": "agent", "message": str(exc)})
        summary["checks"] = checks
        summary["server_events"] = server_events
        summary["display_events"] = display_events
        summary["errors"] = errors
        _close_display_port(display_port)
        return summary

    try:
        if not _show_display(
            display=display,
            stage="speaking",
            intent=expression.intent_for_state(TurnState.SPEAKING),
            require_ack=require_display_ack,
            ack_timeout=display_ack_timeout,
            display_events=display_events,
            errors=errors,
        ):
            checks["display"] = _display_checks(display_enabled, require_display_ack, display_events)
            summary["checks"] = checks
            summary["server_events"] = server_events
            summary["display_events"] = display_events
            summary["errors"] = errors
            _close_display_port(display_port)
            return summary

        audio_reply = speech.synthesize(reply.text, config.tts_voice)
        server_events.append("tts")
        checks["tts"] = {
            "bytes": audio_reply.stat().st_size,
            "voice": config.tts_voice,
        }

        if play:
            AudioPlayer().play(audio_reply)
            checks["playback"] = {"played": True}

        _show_display(
            display=display,
            stage="agent",
            intent=expression.intent_from_agent(
                {
                    "emotion": reply.emotion or "happy",
                    "display_text": reply.display_text if reply.display_text is not None else "DONE",
                    "duration_ms": reply.duration_ms,
                    "intensity": reply.intensity,
                }
            ),
            require_ack=require_display_ack,
            ack_timeout=display_ack_timeout,
            display_events=display_events,
            errors=errors,
        )
    except Exception as exc:
        errors.append({"error": "tts", "message": str(exc)})
    finally:
        _close_display_port(display_port)

    checks["display"] = _display_checks(display_enabled, require_display_ack, display_events)
    summary["checks"] = checks
    summary["server_events"] = server_events
    summary["display_events"] = display_events
    summary["errors"] = errors
    summary["ok"] = not errors and server_events == ["stt", "chat", "tts"]
    return summary


def main(argv: Optional[Sequence[str]] = None, stdout: TextIO = sys.stdout) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    try:
        summary = run_turn_probe(args)
    except Exception as exc:
        summary = _empty_summary()
        summary["errors"] = [{"error": "config", "message": str(exc)}]
    stdout.write(_dumps_compact_redacted_safe(summary) + "\n")
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
