"""Probe only the configured JKS Agent endpoint without requiring speech services."""

from __future__ import annotations

import json
import sys
from typing import Optional, Sequence, TextIO
from urllib.parse import urlsplit

from jks.agent import build_agent_client
from jks.config import load_config
from tools.jks_probe_summary import summarize_agent_config, summarize_agent_reply


def _is_http_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def _is_placeholder(value: str) -> bool:
    return value.strip().lower().startswith("replace-with-")


def _empty_summary() -> dict[str, object]:
    return {
        "ok": False,
        "agent": {},
        "checks": {},
        "errors": [],
    }


def run_probe() -> dict[str, object]:
    config = load_config()
    summary = _empty_summary()
    summary["agent"] = summarize_agent_config(config)

    can_use_local = str(getattr(config, "agent_mode", "")).strip().lower() == "local"
    can_use_http = config.agent_endpoint and not _is_placeholder(config.agent_endpoint)
    can_use_ssh = config.agent_host and not _is_placeholder(config.agent_host)
    if not can_use_http and not can_use_ssh and not can_use_local:
        summary["errors"] = [{"error": "agent", "message": "JKS_AGENT_ENDPOINT is required"}]
        return summary
    if can_use_http and not _is_http_url(config.agent_endpoint):
        summary["errors"] = [{"error": "agent", "message": "JKS_AGENT_ENDPOINT must be an http(s) URL"}]
        return summary

    try:
        reply = build_agent_client(config, timeout=60.0).probe_contract()
    except Exception as exc:
        summary["errors"] = [{"error": "agent", "message": str(exc)}]
        return summary

    summary["checks"] = {
        "agent": summarize_agent_reply(
            reply,
            mode="local" if can_use_local else ("http" if can_use_http else "ssh"),
        )
    }
    summary["ok"] = True
    return summary


def main(argv: Optional[Sequence[str]] = None, stdout: TextIO = sys.stdout) -> int:
    try:
        summary = run_probe()
    except Exception as exc:
        summary = _empty_summary()
        summary["errors"] = [{"error": "config", "message": str(exc)}]
    stdout.write(json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0 if summary.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
