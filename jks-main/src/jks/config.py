from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Optional, Union


@dataclass(frozen=True)
class AppConfig:
    agent_host: str
    agent_user: str
    agent_auth_method: str
    agent_ssh_password: str
    agent_command: str
    agent_workdir: str
    agent_endpoint: str
    agent_token: str
    agent_model: str
    stt_provider: str
    stt_endpoint: str
    stt_token: str
    tts_provider: str
    tts_endpoint: str
    tts_token: str
    fish_api_key: str
    fish_tts_model: str
    fish_tts_latency: str
    tts_voice: str
    oled_port: str
    oled_baud: int
    agent_mode: str = ""
    http_proxy: str = ""
    https_proxy: str = ""


def _int_setting(settings: Mapping[str, str], name: str, default: int) -> int:
    raw = settings.get(name)
    if raw is None or raw == "":
        return default

    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _read_env_file(path: Optional[Path]) -> dict[str, str]:
    if path is None or not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _strip_quotes(value.strip())
    return values


def _settings(env_file: Optional[Path]) -> dict[str, str]:
    values = _read_env_file(env_file)
    values.update(os.environ)
    return values


def load_config(env_file: Optional[Union[os.PathLike[str], str]] = ".env") -> AppConfig:
    settings = _settings(Path(env_file) if env_file is not None else None)
    return AppConfig(
        agent_host=settings.get("JKS_AGENT_HOST", ""),
        agent_user=settings.get("JKS_AGENT_USER", ""),
        agent_auth_method=settings.get("JKS_AGENT_AUTH_METHOD", ""),
        agent_ssh_password=settings.get("JKS_AGENT_SSH_PASSWORD", settings.get("SSHPASS", "")),
        agent_command=settings.get(
            "JKS_AGENT_COMMAND",
            "/usr/local/lib/hermes-agent/venv/bin/hermes",
        ),
        agent_workdir=settings.get("JKS_AGENT_WORKDIR", "/usr/local/lib/hermes-agent"),
        agent_endpoint=settings.get("JKS_AGENT_ENDPOINT", ""),
        agent_token=settings.get("JKS_AGENT_TOKEN", ""),
        agent_model=settings.get("JKS_AGENT_MODEL", "gran-agent"),
        stt_provider=settings.get("JKS_STT_PROVIDER", ""),
        stt_endpoint=settings.get("JKS_STT_ENDPOINT", ""),
        stt_token=settings.get("JKS_STT_TOKEN", ""),
        tts_provider=settings.get("JKS_TTS_PROVIDER", ""),
        tts_endpoint=settings.get("JKS_TTS_ENDPOINT", ""),
        tts_token=settings.get("JKS_TTS_TOKEN", ""),
        fish_api_key=settings.get(
            "JKS_FISH_API_KEY",
            settings.get("FISH_API_KEY", settings.get("FISH_AUDIO_API_KEY", "")),
        ),
        fish_tts_model=settings.get("JKS_FISH_TTS_MODEL", "s2-pro"),
        fish_tts_latency=settings.get("JKS_FISH_TTS_LATENCY", "low"),
        tts_voice=settings.get("JKS_TTS_VOICE", "default"),
        oled_port=settings.get("JKS_OLED_PORT", "/dev/cu.usbmodem5B900048301"),
        oled_baud=_int_setting(settings, "JKS_OLED_BAUD", 115200),
        agent_mode=settings.get("JKS_AGENT_MODE", ""),
        http_proxy=settings.get("HTTP_PROXY", settings.get("http_proxy", "")),
        https_proxy=settings.get("HTTPS_PROXY", settings.get("https_proxy", "")),
    )
