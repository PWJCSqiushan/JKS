from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .display import ALLOWED_EMOTIONS, DisplayIntent


class TurnState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


STATE_INTENTS = {
    TurnState.IDLE: DisplayIntent("neutral", "READY", duration_ms=1800, intensity="soft"),
    TurnState.LISTENING: DisplayIntent("listening", "HEAR", duration_ms=1000, intensity="high"),
    TurnState.TRANSCRIBING: DisplayIntent("thinking", "TEXT", duration_ms=1000),
    TurnState.THINKING: DisplayIntent("thinking", "WAIT", duration_ms=1400),
    TurnState.SPEAKING: DisplayIntent("speaking", "TALK", duration_ms=900, intensity="high"),
    TurnState.ERROR: DisplayIntent("error", "OOPS", duration_ms=900, intensity="high"),
}

MAX_AGENT_DISPLAY_STEPS = 4
MAX_AGENT_DISPLAY_TOTAL_MS = 8000

EMOTION_DEFAULTS = {
    "neutral": (1200, "soft"),
    "happy": (1200, "high"),
    "thinking": (1400, "normal"),
    "speaking": (900, "high"),
    "listening": (1000, "high"),
    "surprised": (1000, "high"),
    "sleepy": (1800, "soft"),
    "sad": (1200, "normal"),
    "angry": (900, "high"),
    "error": (900, "high"),
}


@dataclass(frozen=True)
class ExpressionFrame:
    emotion: str
    text: str
    duration_ms: int


@dataclass(frozen=True)
class DisplayCommand:
    command: str
    intent: Optional[DisplayIntent] = None


def _clamp_oled_text(text: object, limit: int = 14) -> str:
    printable = "".join(ch for ch in str(text) if " " <= ch <= "~")
    return printable[:limit]


class ExpressionEngine:
    def intent_for_state(self, state: TurnState) -> DisplayIntent:
        return STATE_INTENTS[state]

    def intent_from_agent(self, payload: Optional[Mapping[str, object]]) -> DisplayIntent:
        return self._intent_from_mapping(payload or {})

    def intents_from_agent(self, payload: Optional[Mapping[str, object]]) -> list[DisplayIntent]:
        return [
            action.intent
            for action in self.display_actions_from_agent(payload)
            if action.command == "show" and action.intent is not None
        ]

    def display_actions_from_agent(
        self,
        payload: Optional[Mapping[str, object]],
    ) -> list[DisplayCommand]:
        if payload is None:
            payload = {}
        items = self._agent_display_items(payload)
        if items is None:
            return [DisplayCommand("show", self.intent_from_agent(payload))]

        actions: list[DisplayCommand] = []
        total_ms = 0
        for item in items:
            if not isinstance(item, Mapping):
                continue
            command = self._command_from_item(item)
            if command == "face":
                command = "emotion"
            if command in {"probe", "diagnostic"}:
                continue
            if command == "clear":
                actions.append(DisplayCommand("clear"))
            elif command == "text":
                intent = self._text_command_intent(item)
                intent = self._fit_total_duration(intent, total_ms)
                if intent is None:
                    break
                total_ms += intent.duration_ms
                actions.append(DisplayCommand("show", intent))
            elif command == "emotion":
                intent = self._intent_from_mapping(item)
                intent = self._fit_total_duration(intent, total_ms)
                if intent is None:
                    break
                total_ms += intent.duration_ms
                actions.append(DisplayCommand("show", intent))

            if len(actions) >= MAX_AGENT_DISPLAY_STEPS:
                break

        if actions:
            return actions
        return [DisplayCommand("show", self.intent_from_agent(payload))]

    def _agent_display_items(self, payload: Mapping[str, object]) -> object:
        commands = payload.get("display_commands")
        if isinstance(commands, list):
            return commands
        sequence = payload.get("display_sequence")
        if isinstance(sequence, list):
            return sequence
        return None

    def _command_from_item(self, item: Mapping[str, object]) -> str:
        raw_command = item.get("cmd", item.get("type"))
        if raw_command is None:
            if item.get("emotion") is not None or item.get("name") is not None:
                return "emotion"
            if item.get("text") is not None or item.get("display_text") is not None:
                return "text"
            return "emotion"
        return str(raw_command).strip().lower()

    def _intent_from_mapping(self, payload: Mapping[str, object]) -> DisplayIntent:
        raw_emotion = payload.get("emotion", payload.get("name", "neutral"))
        raw_emotion = str(raw_emotion)
        emotion = raw_emotion if raw_emotion in ALLOWED_EMOTIONS else "neutral"
        raw_text = payload.get("display_text")
        if raw_text is None:
            raw_text = payload.get("text")
        if raw_text is None:
            raw_text = emotion.upper()
        text = _clamp_oled_text(raw_text)
        default_duration, default_intensity = EMOTION_DEFAULTS.get(emotion, (1200, "normal"))
        raw_duration = payload.get("duration_ms")
        if raw_duration is None:
            raw_duration = default_duration
        duration_ms = self._clamp_duration(raw_duration)
        raw_intensity = payload.get("intensity")
        if raw_intensity is None:
            raw_intensity = default_intensity
        intensity = self._clamp_intensity(raw_intensity, default="normal")
        return DisplayIntent(
            emotion=emotion,
            text=text,
            duration_ms=duration_ms,
            intensity=intensity,
        )

    def _text_command_intent(self, payload: Mapping[str, object]) -> DisplayIntent:
        raw_text = payload.get("display_text", payload.get("text", ""))
        raw_duration = payload.get("duration_ms")
        if raw_duration is None:
            raw_duration = 500
        duration_ms = self._clamp_duration(raw_duration)
        raw_intensity = payload.get("intensity")
        if raw_intensity is None:
            raw_intensity = "soft"
        intensity = self._clamp_intensity(raw_intensity, default="soft")
        return DisplayIntent(
            emotion="neutral",
            text=_clamp_oled_text(raw_text),
            duration_ms=duration_ms,
            intensity=intensity,
        )

    def _fit_total_duration(
        self,
        intent: DisplayIntent,
        current_total_ms: int,
    ) -> Optional[DisplayIntent]:
        remaining = MAX_AGENT_DISPLAY_TOTAL_MS - current_total_ms
        if remaining < 200:
            return None
        if intent.duration_ms <= remaining:
            return intent
        return DisplayIntent(
            emotion=intent.emotion,
            text=intent.text,
            duration_ms=remaining,
            intensity=intent.intensity,
        )

    def frames_for(self, emotion: str) -> list[ExpressionFrame]:
        if emotion == "speaking":
            return [
                ExpressionFrame("speaking", "TALK", 120),
                ExpressionFrame("speaking", "talk", 140),
                ExpressionFrame("speaking", "TALK!", 160),
                ExpressionFrame("speaking", "mm", 120),
            ]
        if emotion == "thinking":
            return [
                ExpressionFrame("thinking", "WAIT", 220),
                ExpressionFrame("thinking", "hmm?", 220),
                ExpressionFrame("thinking", "..", 220),
                ExpressionFrame("thinking", "...", 280),
            ]
        if emotion == "happy":
            return [
                ExpressionFrame("happy", "YAY", 140),
                ExpressionFrame("happy", "^_^", 160),
                ExpressionFrame("happy", "yay!", 140),
                ExpressionFrame("happy", "DONE", 220),
            ]
        if emotion == "listening":
            return [
                ExpressionFrame("listening", "HEAR", 160),
                ExpressionFrame("listening", "o_o", 180),
                ExpressionFrame("listening", ".o_", 180),
                ExpressionFrame("listening", "...", 240),
            ]
        if emotion == "surprised":
            return [
                ExpressionFrame("surprised", "WOW", 140),
                ExpressionFrame("surprised", "O_O", 160),
                ExpressionFrame("surprised", "!!", 140),
                ExpressionFrame("surprised", "WOW!", 220),
            ]
        if emotion == "sleepy":
            return [
                ExpressionFrame("sleepy", "zzz", 420),
                ExpressionFrame("sleepy", "-_-", 420),
                ExpressionFrame("sleepy", "Zzz", 520),
            ]
        if emotion == "sad":
            return [
                ExpressionFrame("sad", "oh", 260),
                ExpressionFrame("sad", "T_T", 360),
                ExpressionFrame("sad", "...", 420),
            ]
        if emotion == "angry":
            return [
                ExpressionFrame("angry", "HEY", 180),
                ExpressionFrame("angry", ">_<", 180),
                ExpressionFrame("angry", "!!", 220),
            ]
        if emotion == "neutral":
            return [
                ExpressionFrame("neutral", "READY", 420),
                ExpressionFrame("neutral", "-_-", 120),
                ExpressionFrame("neutral", "READY", 520),
            ]
        if emotion == "error":
            return [
                ExpressionFrame("error", "OOPS", 180),
                ExpressionFrame("error", "! !", 180),
                ExpressionFrame("neutral", "READY", 600),
            ]
        return self.frames_for("neutral")

    def _clamp_duration(self, raw: object) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 1200
        return max(200, min(value, 5000))

    def _clamp_intensity(self, raw: object, default: str = "normal") -> str:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            if raw >= 0.75:
                return "high"
            if raw <= 0.35:
                return "soft"
            return "normal"
        value = str(raw)
        if value in {"soft", "normal", "high"}:
            return value
        return default
