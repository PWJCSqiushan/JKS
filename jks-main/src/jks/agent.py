from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import threading
import time
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import requests


@dataclass(frozen=True)
class AgentReply:
    text: str
    emotion: str = ""
    display_text: Any = None
    duration_ms: Any = None
    intensity: Any = None
    display_sequence: Any = None
    display_commands: Any = None


@dataclass(frozen=True)
class AgentTraceEvent:
    source: str
    message: str


class AgentProviderError(RuntimeError):
    """Raised when the remote agent transport or response contract fails."""


def parse_agent_reply(payload: Any) -> AgentReply:
    if isinstance(payload, str):
        structured = _parse_json_object(payload)
        if structured is not None:
            return parse_agent_reply(structured)
        return AgentReply(text=payload)
    if isinstance(payload, dict):
        normalized = _unwrap_envelope(payload)
        structured = _extract_structured_content(normalized)
        if structured is not None:
            normalized = structured
        text = _extract_text(normalized, allow_legacy_dict_stringify=normalized is payload)
        display_fields = _extract_display_fields(payload)
        if normalized is not payload:
            display_fields.update(
                {
                    key: value
                    for key, value in _extract_display_fields(normalized).items()
                    if value is not None and value != ""
                }
            )
        emotion = display_fields.get("emotion", "")
        return AgentReply(
            text=text,
            emotion=str(emotion),
            display_text=display_fields.get("display_text"),
            duration_ms=display_fields.get("duration_ms"),
            intensity=display_fields.get("intensity"),
            display_sequence=display_fields.get("display_sequence"),
            display_commands=display_fields.get("display_commands"),
        )
    return AgentReply(text=str(payload))


def _first_present(mapping: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _parse_json_object(value: str) -> dict[str, Any] | None:
    stripped = value.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        return None
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_structured_content(payload: dict[str, Any]) -> dict[str, Any] | None:
    content = _assistant_content(payload)
    if not isinstance(content, str):
        return None
    parsed = _parse_json_object(content)
    if parsed is None:
        return None
    if _first_present(parsed, ("text", "reply", "message", "content")) is None:
        return None
    return parsed


def _assistant_content(payload: dict[str, Any]) -> Any:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message")
            if isinstance(message, dict):
                return message.get("content")
            if first_choice.get("text") is not None:
                return first_choice.get("text")

    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        selected = None
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "assistant":
                selected = message
        if selected is None:
            for message in reversed(messages):
                if isinstance(message, dict):
                    selected = message
                    break
        if isinstance(selected, dict):
            return selected.get("content")

    direct = _first_present(payload, ("message", "content"))
    if isinstance(direct, dict):
        return direct.get("content")
    return direct


def _content_to_text(content: Any, allow_dict_stringify: bool = False) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type in {"text", "output_text"} and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif item_type in {"text", "output_text"} and isinstance(item.get("content"), str):
                    parts.append(item["content"])
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    if isinstance(content, dict):
        if allow_dict_stringify:
            return str(content)
        nested = _first_present(content, ("text", "content", "message"))
        if nested is not None:
            return _content_to_text(nested)
        return ""
    return str(content)


def _extract_display_fields(payload: dict[str, Any]) -> dict[str, Any]:
    display = {}
    nested = _first_present(payload, ("display", "display_intent", "expression"))
    if isinstance(nested, dict):
        display.update(
            {
                "emotion": nested.get("emotion", nested.get("name", "")),
                "display_text": nested.get("display_text", nested.get("text")),
                "duration_ms": nested.get("duration_ms"),
                "intensity": nested.get("intensity"),
                "display_sequence": _list_or_none(nested.get("display_sequence")),
                "display_commands": _list_or_none(nested.get("display_commands")),
            }
        )

    display.update(
        {
            "emotion": payload.get("emotion", display.get("emotion", "")),
            "display_text": payload.get("display_text", display.get("display_text")),
            "duration_ms": payload.get("duration_ms", display.get("duration_ms")),
            "intensity": payload.get("intensity", display.get("intensity")),
            "display_sequence": _list_or_none(
                payload.get("display_sequence", display.get("display_sequence"))
            ),
            "display_commands": _list_or_none(
                payload.get("display_commands", display.get("display_commands"))
            ),
        }
    )
    return display


def _list_or_none(value: Any) -> list[Any] | None:
    return value if isinstance(value, list) else None


def _unwrap_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    current = payload
    for _ in range(4):
        direct_value = _first_present(
            current,
            (
                "text",
                "reply",
                "message",
                "content",
                "choices",
                "messages",
            ),
        )
        if direct_value is not None:
            return current

        nested = _first_present(current, ("result", "data", "output", "response"))
        if not isinstance(nested, dict):
            return current
        current = nested
    return current


def _extract_text(payload: dict[str, Any], allow_legacy_dict_stringify: bool = False) -> str:
    legacy_direct = _first_present(payload, ("text", "reply"))
    if legacy_direct is not None:
        return _content_to_text(
            legacy_direct,
            allow_dict_stringify=allow_legacy_dict_stringify,
        )

    direct = _first_present(payload, ("message", "content"))
    if direct is not None:
        text = _content_to_text(direct)
        if text:
            return text

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            if first_choice.get("text") is not None:
                return _content_to_text(first_choice.get("text"))
            message = first_choice.get("message")
            if isinstance(message, dict):
                return _content_to_text(message.get("content"))

    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        selected = None
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "assistant":
                selected = message
        if selected is None:
            for message in reversed(messages):
                if isinstance(message, dict):
                    selected = message
                    break
        if isinstance(selected, dict):
            return _content_to_text(selected.get("content"))

    return ""


class HttpAgentClient:
    def __init__(
        self,
        endpoint: str,
        token: str = "",
        timeout: float = 30.0,
        model: str = "gran-agent",
    ):
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self.model = model or "gran-agent"

    def send_message(
        self,
        text: str,
        conversation_id: str,
        history: list[dict[str, str]] | None = None,
        trace_callback: Callable[[AgentTraceEvent], None] | None = None,
    ) -> AgentReply:
        if not self.endpoint:
            raise RuntimeError("JKS_AGENT_ENDPOINT is not configured")
        _emit_trace(trace_callback, "process", "HTTP agent request started")

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if _uses_openai_chat_completions(self.endpoint):
            body = {
                "model": self.model,
                "messages": _chat_messages(text, history),
                "stream": False,
            }
            if conversation_id:
                headers["X-Hermes-Session-Id"] = conversation_id
        else:
            body = {"message": text, "conversation_id": conversation_id}
            cleaned_history = _clean_history(history)
            if cleaned_history:
                body["history"] = cleaned_history
                body["system"] = _voice_json_contract()

        try:
            response = requests.post(
                self.endpoint,
                json=body,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except Exception as exc:
            raise AgentProviderError("agent request failed") from exc

        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        reply = parse_agent_reply(payload)
        _emit_trace(trace_callback, "process", "HTTP agent response received")
        _reject_provider_error_text(reply.text)
        if not reply.text.strip():
            raise AgentProviderError("agent response did not contain text")
        return reply

    def probe_contract(self) -> AgentReply:
        return self.send_message("JKS contract probe", "contract-probe")


class LocalHermesAgentClient:
    def __init__(
        self,
        command: str = "/usr/local/lib/hermes-agent/venv/bin/hermes",
        workdir: str = "/usr/local/lib/hermes-agent",
        timeout: float = 120.0,
        model: str = "",
    ):
        self.command = _absolute_runtime_path(command or "/usr/local/lib/hermes-agent/venv/bin/hermes")
        self.workdir = _absolute_runtime_path(workdir or "/usr/local/lib/hermes-agent")
        self.timeout = timeout
        self.model = model

    def send_message(
        self,
        text: str,
        conversation_id: str,
        history: list[dict[str, str]] | None = None,
        trace_callback: Callable[[AgentTraceEvent], None] | None = None,
    ) -> AgentReply:
        if not self.command:
            raise RuntimeError("JKS_AGENT_COMMAND is not configured")

        session_name = _ssh_session_name(conversation_id)
        prompt = _voice_json_prompt(text, history)
        command = self._build_command(session_name, prompt)
        if trace_callback is None:
            stdout = self._run_command(command)
        else:
            stdout = self._run_command_with_trace(command, session_name, trace_callback)

        reply = parse_agent_reply(stdout.strip())
        _reject_provider_error_text(reply.text)
        if not reply.text.strip():
            raise AgentProviderError("agent response did not contain text")
        return reply

    def _build_command(self, session_name: str, prompt: str) -> list[str]:
        command = [self.command, "--continue", session_name]
        if self.model:
            command.extend(["--model", self.model])
        command.extend(["-z", prompt])
        return command

    def _run_command(self, command: list[str]) -> str:
        try:
            completed = subprocess.run(
                command,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                check=True,
                timeout=self.timeout,
                env=os.environ.copy(),
            )
        except Exception as exc:
            raise AgentProviderError("local hermes request failed") from exc
        return completed.stdout

    def _run_command_with_trace(
        self,
        command: list[str],
        session_name: str,
        trace_callback: Callable[[AgentTraceEvent], None],
    ) -> str:
        started_at = time.time()
        stop_event = threading.Event()
        watcher = threading.Thread(
            target=self._watch_session_trace,
            args=(session_name, started_at, trace_callback, stop_event),
            daemon=True,
        )
        _emit_trace(trace_callback, "process", "Hermes request started")
        watcher.start()
        try:
            process = subprocess.Popen(
                command,
                cwd=self.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=os.environ.copy(),
            )
            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(command, self.timeout, output=stdout, stderr=stderr) from exc
            if process.returncode:
                raise subprocess.CalledProcessError(
                    process.returncode,
                    command,
                    output=stdout,
                    stderr=stderr,
                )
        except Exception as exc:
            raise AgentProviderError("local hermes request failed") from exc
        finally:
            stop_event.set()
            watcher.join(timeout=1.0)

        _emit_trace(trace_callback, "process", "Hermes final response received")
        return stdout

    def _watch_session_trace(
        self,
        session_name: str,
        started_at: float,
        trace_callback: Callable[[AgentTraceEvent], None],
        stop_event: threading.Event,
    ) -> None:
        del session_name
        session_dirs = self._candidate_session_dirs()
        seen_by_file: dict[Path, set[int]] = {}
        while True:
            recent_files = _recent_session_files(session_dirs, started_at)
            for session_file in recent_files[-1:]:
                seen = seen_by_file.setdefault(session_file, set())
                for event in _trace_events_from_session_file(session_file, seen):
                    _emit_trace(trace_callback, event.source, event.message)
            if stop_event.is_set():
                break
            stop_event.wait(0.25)

    def _candidate_session_dirs(self) -> list[Path]:
        candidates: list[Path] = []
        env_home = os.environ.get("HERMES_HOME", "").strip()
        if env_home:
            candidates.append(Path(env_home) / "sessions")

        command_path = Path(self.command).resolve()
        if command_path.name == "jksgrantly":
            runtime_dir = command_path.parent.parent
            candidates.append(
                runtime_dir
                / "hermes-home"
                / ".hermes"
                / "profiles"
                / "jksgrantly"
                / "sessions"
            )
            candidates.append(runtime_dir / "hermes-home" / ".hermes" / "sessions")

        candidates.append(Path.home() / ".hermes" / "sessions")
        unique: list[Path] = []
        for candidate in candidates:
            if candidate in unique:
                continue
            if candidate.is_dir():
                unique.append(candidate)
        return unique

    def probe_contract(self) -> AgentReply:
        return self.send_message("JKS contract probe", "contract-probe")


class SshHermesAgentClient:
    def __init__(
        self,
        host: str,
        user: str = "root",
        password: str = "",
        command: str = "/usr/local/lib/hermes-agent/venv/bin/hermes",
        workdir: str = "/usr/local/lib/hermes-agent",
        timeout: float = 120.0,
        retries: int = 1,
        model: str = "",
    ):
        self.host = host
        self.user = user or ""
        self.password = password
        self.command = command or "/usr/local/lib/hermes-agent/venv/bin/hermes"
        self.workdir = workdir or "/usr/local/lib/hermes-agent"
        self.timeout = timeout
        self.retries = max(0, retries)
        self.model = model

    def send_message(
        self,
        text: str,
        conversation_id: str,
        history: list[dict[str, str]] | None = None,
        trace_callback: Callable[[AgentTraceEvent], None] | None = None,
    ) -> AgentReply:
        if not self.host:
            raise RuntimeError("JKS_AGENT_HOST is not configured")
        _emit_trace(trace_callback, "process", "SSH Hermes request started")

        target = f"{self.user}@{self.host}" if self.user else self.host
        session_name = _ssh_session_name(conversation_id)
        prompt = _voice_json_prompt(text, history)
        hermes_args = [self.command, "--continue", session_name]
        if self.model:
            hermes_args.extend(["--model", self.model])
        hermes_args.extend(["-z", prompt])
        remote_command = f"cd {shlex.quote(self.workdir)} && {shlex.join(hermes_args)}"
        ssh_command = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ControlMaster=auto",
            "-o",
            "ControlPersist=60",
            "-o",
            "ControlPath=~/.ssh/jks-%r@%h:%p",
            target,
            remote_command,
        ]
        command = ssh_command
        env = os.environ.copy()
        if self.password:
            command = ["sshpass", "-e", *ssh_command]
            env["SSHPASS"] = self.password
        else:
            env.pop("SSHPASS", None)

        for attempt in range(self.retries + 1):
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=self.timeout,
                    env=env,
                )
                break
            except subprocess.CalledProcessError as exc:
                if exc.returncode == 255 and attempt < self.retries:
                    _emit_trace(trace_callback, "process", "SSH retrying after transient failure")
                    continue
                raise AgentProviderError("hermes ssh request failed") from exc
            except Exception as exc:
                raise AgentProviderError("hermes ssh request failed") from exc

        reply = parse_agent_reply(completed.stdout.strip())
        _emit_trace(trace_callback, "process", "SSH Hermes response received")
        _reject_provider_error_text(reply.text)
        if not reply.text.strip():
            raise AgentProviderError("agent response did not contain text")
        return reply

    def probe_contract(self) -> AgentReply:
        return self.send_message("JKS contract probe", "contract-probe")


def _uses_openai_chat_completions(endpoint: str) -> bool:
    try:
        path = urlsplit(endpoint).path.rstrip("/")
    except ValueError:
        return False
    return path.endswith("/v1/chat/completions")


def build_agent_client(config, timeout: float = 120.0):
    agent_mode = str(getattr(config, "agent_mode", "")).strip().lower()
    if agent_mode == "local":
        return LocalHermesAgentClient(
            command=getattr(config, "agent_command", ""),
            workdir=getattr(config, "agent_workdir", ""),
            timeout=timeout,
            model=_command_model_override(config),
        )

    endpoint = getattr(config, "agent_endpoint", "")
    if endpoint and not _is_placeholder(endpoint):
        return HttpAgentClient(
            endpoint,
            getattr(config, "agent_token", ""),
            timeout=timeout,
            model=getattr(config, "agent_model", "gran-agent"),
        )
    host = getattr(config, "agent_host", "")
    if host and not _is_placeholder(host):
        return SshHermesAgentClient(
            host=host,
            user=getattr(config, "agent_user", "") or "root",
            password=getattr(config, "agent_ssh_password", ""),
            command=getattr(config, "agent_command", ""),
            workdir=getattr(config, "agent_workdir", ""),
            timeout=timeout,
            model=_command_model_override(config),
        )
    return HttpAgentClient(
        endpoint,
        getattr(config, "agent_token", ""),
        timeout=timeout,
        model=getattr(config, "agent_model", "gran-agent"),
    )


def _is_placeholder(value: str) -> bool:
    return value.strip().lower().startswith("replace-with-")


def _command_model_override(config) -> str:
    command = str(getattr(config, "agent_command", ""))
    if os.path.basename(command).lower() == "jksgrantly":
        return ""
    return getattr(config, "agent_model", "")


def _absolute_runtime_path(value: str) -> str:
    if value.startswith("/"):
        return value
    if os.path.isabs(value):
        return value.replace("\\", "/")
    return os.path.abspath(value).replace("\\", "/")


def _ssh_model_override(config) -> str:
    return _command_model_override(config)


def _reject_provider_error_text(text: str) -> None:
    normalized = text.strip().lower()
    if normalized.startswith("api call failed after") or normalized.startswith("api call failed:"):
        raise AgentProviderError("agent provider failure")
    if normalized.startswith("http 503:") or normalized.startswith("service temporarily unavailable"):
        raise AgentProviderError("agent provider failure")


def _ssh_session_name(conversation_id: str) -> str:
    safe = []
    for char in conversation_id:
        safe.append(char if char.isalnum() or char in {"-", "_"} else "-")
    value = "".join(safe).strip("-_")[:80]
    return f"jks-{value or 'session'}"


def _voice_json_prompt(text: str, history: list[dict[str, str]] | None = None) -> str:
    history_text = _history_prompt(history)
    if history_text:
        return f"{_voice_json_contract()}\nRecent conversation:\n{history_text}\nUser said: {text}"
    return f"{_voice_json_contract()}\nUser said: {text}"


def _voice_json_contract() -> str:
    return (
        "JKS voice call turn. Return only compact JSON with keys text, emotion, "
        "display_text, duration_ms, intensity, display_sequence, display_commands. "
        "Keep text concise for voice conversation, normally within 80 Chinese characters "
        "unless the user asks for detail. Do not use markdown, bullet markers, or asterisks. "
        "emotion must be one of neutral, happy, thinking, speaking, listening, "
        "surprised, sleepy, sad, angry, error. display_text must be a short ASCII "
        "OLED label. Optional display_sequence may contain up to 4 objects with "
        "emotion, display_text, duration_ms, intensity for OLED screen steps. "
        "Optional display_commands may contain up to 4 whitelisted commands: "
        "emotion, text, or clear."
    )


def _chat_messages(
    text: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": _voice_json_contract()}]
    messages.extend(_clean_history(history))
    messages.append({"role": "user", "content": text})
    return messages


def _clean_history(history: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant", "system"} or not content:
            continue
        cleaned.append({"role": role, "content": content})
    return cleaned[-10:]


def _history_prompt(history: list[dict[str, str]] | None = None) -> str:
    lines = []
    for item in _clean_history(history):
        role = item["role"]
        content = _sanitize_trace_text(item["content"], max_chars=240)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _emit_trace(
    trace_callback: Callable[[AgentTraceEvent], None] | None,
    source: str,
    message: str,
) -> None:
    if trace_callback is None:
        return
    try:
        trace_callback(AgentTraceEvent(source=source, message=message))
    except Exception:
        return


def _recent_session_files(session_dirs: list[Path], started_at: float) -> list[Path]:
    files: list[Path] = []
    for session_dir in session_dirs:
        try:
            for session_file in session_dir.glob("session_*.json"):
                if session_file.stat().st_mtime >= started_at:
                    files.append(session_file)
        except OSError:
            continue
    return sorted(files, key=lambda path: path.stat().st_mtime)


def _trace_events_from_session_file(
    session_file: Path,
    seen_indices: set[int],
) -> list[AgentTraceEvent]:
    try:
        payload = json.loads(session_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return []
    return list(_trace_events_from_messages(messages, seen_indices))


def _trace_events_from_messages(
    messages: list[Any],
    seen_indices: set[int],
) -> Iterable[AgentTraceEvent]:
    for index, message in enumerate(messages):
        if index in seen_indices:
            continue
        seen_indices.add(index)
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "user":
            yield AgentTraceEvent(source="user", message="prompt accepted")
            continue
        if role == "assistant":
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                for tool_call in tool_calls:
                    name = _tool_call_name(tool_call)
                    yield AgentTraceEvent(source="assistant", message=f"tool call: {name}")
                continue
            if str(message.get("content") or "").strip():
                yield AgentTraceEvent(source="assistant", message="final response received")
            continue
        if role == "tool":
            yield AgentTraceEvent(
                source="tool",
                message=_summarize_tool_result(message),
            )


def _tool_call_name(tool_call: Any) -> str:
    if not isinstance(tool_call, dict):
        return "unknown"
    function = tool_call.get("function")
    if isinstance(function, dict) and function.get("name"):
        return _sanitize_trace_text(str(function["name"]), max_chars=80)
    return _sanitize_trace_text(str(tool_call.get("name") or tool_call.get("type") or "unknown"), max_chars=80)


def _summarize_tool_result(message: dict[str, Any]) -> str:
    name = _sanitize_trace_text(str(message.get("name") or "tool"), max_chars=80)
    content = message.get("content")
    exit_code = None
    output = content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            exit_code = parsed.get("exit_code")
            output = parsed.get("output") or parsed.get("error") or ""
    detail = _sanitize_trace_text(str(output or ""), max_chars=180)
    if exit_code is not None:
        return f"{name} exit_code={exit_code} output={detail}"
    if detail:
        return f"{name} output={detail}"
    return f"{name} completed"


_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|bearer|token)\\s*[:=]\\s*\\S+"),
]


def _sanitize_trace_text(value: str, max_chars: int = 180) -> str:
    cleaned = value.replace("\r", " ").replace("\n", " ").strip()
    cleaned = "".join(char if char.isprintable() else " " for char in cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    if len(cleaned) > max_chars:
        return cleaned[: max_chars - 1].rstrip() + "..."
    return cleaned
