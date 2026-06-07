"""Shared compact summaries for probe command JSON output."""

from __future__ import annotations

from typing import Mapping

from jks.agent import AgentReply


def summarize_agent_reply(reply: AgentReply, mode: str = "http") -> dict[str, object]:
    display_text_length = 0 if reply.display_text is None else len(str(reply.display_text))
    return {
        "mode": mode,
        "text_length": len(reply.text),
        "emotion": reply.emotion,
        "display_present": bool(
            reply.emotion
            or reply.display_text is not None
            or reply.duration_ms is not None
            or reply.intensity is not None
        ),
        "display_text_length": display_text_length,
        "duration_ms": reply.duration_ms,
        "intensity": reply.intensity,
    }


def summarize_preflight(preflight: Mapping[str, object]) -> dict[str, object]:
    """Return a log-safe preflight summary without hostnames, paths, or secrets."""

    agent = _mapping(preflight.get("agent"))
    speech = _mapping(preflight.get("speech"))
    oled = _mapping(preflight.get("oled"))
    missing = _list(preflight.get("missing"))
    warnings = _list(preflight.get("warnings"))
    voice = _string(speech.get("voice"))
    return {
        "ok": bool(preflight.get("ok")),
        "ready_for_real": bool(preflight.get("ready_for_real", preflight.get("ok"))),
        "agent": {
            "mode": _string(agent.get("mode")),
            "endpoint_present": bool(agent.get("endpoint")),
            "host_present": bool(agent.get("host")),
            "auth_method": _string(agent.get("auth_method")),
            "token_present": bool(agent.get("token")),
            "ssh_password_present": bool(agent.get("ssh_password")),
            "model": _string(agent.get("model")),
        },
        "speech": {
            "mode": _string(speech.get("mode")),
            "stt_provider": _string(speech.get("stt_provider")),
            "stt_endpoint_present": bool(speech.get("stt_endpoint")),
            "stt_token_present": bool(speech.get("stt_token")),
            "tts_provider": _string(speech.get("tts_provider")),
            "tts_endpoint_present": bool(speech.get("tts_endpoint")),
            "tts_token_present": bool(speech.get("tts_token")),
            "fish_api_key_present": bool(speech.get("fish_api_key")),
            "fish_tts_model": _string(speech.get("fish_tts_model")),
            "fish_tts_latency": _string(speech.get("fish_tts_latency")),
            "voice_present": bool(voice),
            "voice_custom": bool(voice and voice != "default"),
        },
        "oled": {
            "mode": _string(oled.get("mode")),
            "port_present": bool(oled.get("port")),
            "baud": oled.get("baud", 0),
        },
        "missing": missing,
        "missing_count": len(missing),
        "warnings": warnings,
        "warning_count": len(warnings),
    }


def summarize_agent_config(config) -> dict[str, object]:
    configured_mode = _string(getattr(config, "agent_mode", "")).strip().lower()
    return {
        "mode": configured_mode
        if configured_mode == "local"
        else (
            "http"
            if getattr(config, "agent_endpoint", "")
            and not _is_placeholder(str(getattr(config, "agent_endpoint", "")))
            else (
                "ssh"
                if getattr(config, "agent_host", "")
                and not _is_placeholder(str(getattr(config, "agent_host", "")))
                else "missing"
            )
        ),
        "endpoint_present": bool(getattr(config, "agent_endpoint", "")),
        "host_present": bool(getattr(config, "agent_host", "")),
        "auth_method": _string(getattr(config, "agent_auth_method", "")),
        "token_present": bool(getattr(config, "agent_token", "")),
        "ssh_password_present": bool(getattr(config, "agent_ssh_password", "")),
        "model": _string(getattr(config, "agent_model", "")),
    }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _string(value: object) -> str:
    return "" if value is None else str(value)


def _is_placeholder(value: str) -> bool:
    return value.strip().lower().startswith("replace-with-")
