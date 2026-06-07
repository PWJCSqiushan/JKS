from __future__ import annotations

from urllib.parse import parse_qsl, quote_plus, urlsplit, urlunsplit

from .config import AppConfig


def redact_secret(value: str) -> str:
    if not value:
        return ""
    return f"<redacted:{len(value)}>"


def redact_url(value: str) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "<redacted-url>"
    if not parts.scheme or not parts.netloc:
        return value

    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        return "<redacted-url>"
    if port is not None:
        host = f"{host}:{port}"
    query = "&".join(
        f"{quote_plus(key)}=<redacted>" for key, _ in parse_qsl(parts.query, keep_blank_values=True)
    )
    return urlunsplit((parts.scheme, host, parts.path, query, parts.fragment))


def _is_placeholder(value: str) -> bool:
    return value.strip().lower().startswith("replace-with-")


def _is_http_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def analyze_config(config: AppConfig) -> dict[str, object]:
    missing: list[str] = []
    warnings: list[str] = []

    def add_missing(name: str) -> None:
        if name not in missing:
            missing.append(name)

    def add_warning(message: str) -> None:
        if message not in warnings:
            warnings.append(message)

    def field_has_placeholder(value: str, name: str) -> bool:
        if value and _is_placeholder(value):
            add_missing(name)
            add_warning("placeholder values must be replaced before real integration")
            return True
        return False

    def endpoint_is_ready(value: str, name: str) -> bool:
        if not value:
            return False
        if field_has_placeholder(value, name):
            return False
        if not _is_http_url(value):
            add_missing(name)
            add_warning("endpoint values must be valid http(s) URLs")
            return False
        return True

    stt_provider = config.stt_provider.lower()
    tts_provider = config.tts_provider.lower()
    wants_fish_speech = stt_provider == "fish" or tts_provider == "fish"
    wants_google_edge_speech = stt_provider == "google" and tts_provider == "edge"
    wants_http_stt = stt_provider == "http" or (
        bool(config.stt_endpoint) and stt_provider not in {"fish", "google"}
    )
    wants_http_tts = tts_provider == "http" or (
        bool(config.tts_endpoint) and tts_provider not in {"fish", "edge"}
    )
    wants_http_speech = wants_http_stt or wants_http_tts

    raw_agent_endpoint = config.agent_endpoint
    raw_agent_host = config.agent_host
    raw_agent_mode = str(getattr(config, "agent_mode", "")).strip().lower()
    wants_local_agent = raw_agent_mode == "local"
    wants_ssh_agent = bool(raw_agent_host) and not _is_placeholder(raw_agent_host)
    wants_http_agent = bool(raw_agent_endpoint) and not _is_placeholder(raw_agent_endpoint)
    agent_command_placeholder = (
        field_has_placeholder(config.agent_command, "JKS_AGENT_COMMAND")
        if wants_local_agent
        else False
    )

    agent_token_placeholder = (
        field_has_placeholder(config.agent_token, "JKS_AGENT_TOKEN") if wants_http_agent else False
    )
    agent_ssh_password_placeholder = (
        field_has_placeholder(config.agent_ssh_password, "JKS_AGENT_SSH_PASSWORD")
        if wants_ssh_agent
        else False
    )
    stt_token_placeholder = (
        field_has_placeholder(config.stt_token, "JKS_STT_TOKEN") if wants_http_stt else False
    )
    tts_token_placeholder = (
        field_has_placeholder(config.tts_token, "JKS_TTS_TOKEN") if wants_http_tts else False
    )
    fish_api_key_placeholder = (
        field_has_placeholder(config.fish_api_key, "JKS_FISH_API_KEY")
        if wants_fish_speech
        else False
    )
    fish_tts_model_placeholder = (
        field_has_placeholder(config.fish_tts_model, "JKS_FISH_TTS_MODEL")
        if wants_fish_speech
        else False
    )
    fish_tts_latency_placeholder = (
        field_has_placeholder(getattr(config, "fish_tts_latency", ""), "JKS_FISH_TTS_LATENCY")
        if wants_fish_speech
        else False
    )
    tts_voice_placeholder = (
        field_has_placeholder(config.tts_voice, "JKS_TTS_VOICE")
        if wants_fish_speech or wants_http_tts or wants_google_edge_speech
        else False
    )

    agent_endpoint_ready = (
        endpoint_is_ready(config.agent_endpoint, "JKS_AGENT_ENDPOINT")
        if wants_http_agent
        else False
    )
    if wants_local_agent and config.agent_command and not agent_command_placeholder:
        agent_mode = "local"
    elif wants_local_agent:
        agent_mode = "missing"
        add_missing("JKS_AGENT_COMMAND")
    elif agent_endpoint_ready:
        agent_mode = "http"
    elif wants_ssh_agent:
        agent_mode = "ssh"
    else:
        agent_mode = "missing"
        if (not config.agent_endpoint or _is_placeholder(config.agent_endpoint)) and not config.agent_host:
            add_missing("JKS_AGENT_ENDPOINT")

    stt_endpoint_ready = (
        endpoint_is_ready(config.stt_endpoint, "JKS_STT_ENDPOINT") if wants_http_stt else False
    )
    tts_endpoint_ready = (
        endpoint_is_ready(config.tts_endpoint, "JKS_TTS_ENDPOINT") if wants_http_tts else False
    )

    if wants_fish_speech:
        if (
            stt_provider == "fish"
            and tts_provider == "fish"
            and config.fish_api_key
            and not fish_api_key_placeholder
            and not fish_tts_model_placeholder
            and not fish_tts_latency_placeholder
        ):
            speech_mode = "fish"
        else:
            speech_mode = "partial"
            if stt_provider != "fish":
                add_missing("JKS_STT_PROVIDER")
            if tts_provider != "fish":
                add_missing("JKS_TTS_PROVIDER")
            if not config.fish_api_key or fish_api_key_placeholder:
                add_missing("JKS_FISH_API_KEY")
            if fish_tts_latency_placeholder:
                add_missing("JKS_FISH_TTS_LATENCY")
            add_warning("Fish Audio integration requires both speech providers set to fish")
    elif wants_google_edge_speech:
        speech_mode = "google-edge"
    elif stt_endpoint_ready and tts_endpoint_ready:
        speech_mode = "http"
    elif not wants_http_speech:
        speech_mode = "fake"
    else:
        speech_mode = "partial"
        if not stt_endpoint_ready:
            add_missing("JKS_STT_ENDPOINT")
        if not tts_endpoint_ready:
            add_missing("JKS_TTS_ENDPOINT")
        add_warning("JKS_STT_ENDPOINT and JKS_TTS_ENDPOINT must be configured together")

    if agent_mode == "http" and speech_mode == "fake":
        add_missing("JKS_STT_ENDPOINT")
        add_missing("JKS_TTS_ENDPOINT")
        add_warning("Real agent integration requires Fish Audio or custom STT/TTS endpoints")

    oled_port_placeholder = field_has_placeholder(config.oled_port, "JKS_OLED_PORT")
    oled_mode = "serial" if config.oled_port and not oled_port_placeholder else "disabled"
    if not config.oled_port:
        add_missing("JKS_OLED_PORT")

    ready_for_real = (
        agent_mode in {"http", "ssh", "local"}
        and speech_mode in {"http", "fish", "google-edge"}
        and oled_mode == "serial"
        and not agent_token_placeholder
        and not agent_ssh_password_placeholder
        and not agent_command_placeholder
        and not stt_token_placeholder
        and not tts_token_placeholder
        and not fish_api_key_placeholder
        and not fish_tts_model_placeholder
        and not fish_tts_latency_placeholder
        and not tts_voice_placeholder
    )
    ok = ready_for_real
    return {
        "ok": ok,
        "ready_for_real": ready_for_real,
        "agent": {
            "mode": agent_mode,
            "agent_mode": getattr(config, "agent_mode", ""),
            "endpoint": redact_url(config.agent_endpoint),
            "host": config.agent_host,
            "user": config.agent_user,
            "auth_method": config.agent_auth_method,
            "token": redact_secret(config.agent_token),
            "ssh_password": redact_secret(config.agent_ssh_password),
            "command": config.agent_command,
            "workdir": config.agent_workdir,
            "model": config.agent_model,
        },
        "speech": {
            "mode": speech_mode,
            "stt_provider": config.stt_provider,
            "stt_endpoint": redact_url(config.stt_endpoint),
            "stt_token": redact_secret(config.stt_token),
            "tts_provider": config.tts_provider,
            "tts_endpoint": redact_url(config.tts_endpoint),
            "tts_token": redact_secret(config.tts_token),
            "fish_api_key": redact_secret(config.fish_api_key),
            "fish_tts_model": config.fish_tts_model,
            "fish_tts_latency": getattr(config, "fish_tts_latency", "low"),
            "voice": config.tts_voice,
        },
        "oled": {
            "mode": oled_mode,
            "port": config.oled_port,
            "baud": config.oled_baud,
        },
        "missing": missing,
        "warnings": warnings,
    }
