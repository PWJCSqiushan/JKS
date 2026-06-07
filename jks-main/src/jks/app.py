from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional, Sequence, TextIO

from .agent import AgentTraceEvent, build_agent_client
from .audio import AudioPlayer, AudioRecorder
from .config import AppConfig, load_config
from .display import DisplayController, DisplayIntent, NullDisplayController, open_serial_output
from .expression import ExpressionEngine, TurnState
from .orchestrator import ConversationOrchestrator
from .speech import build_speech_client


def build_orchestrator(
    config: AppConfig,
    *,
    open_serial: Callable[[str, int], object] = open_serial_output,
    output_dir: Optional[Path] = None,
    recorder=None,
    player=None,
    status_callback: Optional[Callable[[TurnState], None]] = None,
    display_status_callback: Optional[Callable[[str], None]] = None,
    display_error_callback: Optional[Callable[[str], None]] = None,
    agent_trace_callback: Optional[Callable[[AgentTraceEvent], None]] = None,
    display_update_callback: Optional[Callable[[object], None]] = None,
) -> ConversationOrchestrator:
    output_dir = Path(output_dir) if output_dir is not None else Path(tempfile.gettempdir())

    try:
        serial_output = open_serial(config.oled_port, config.oled_baud)
        display = DisplayController(serial_output, ack_input=serial_output)
    except Exception:
        if display_status_callback is not None:
            display_status_callback(
                f"OLED unavailable on {config.oled_port}; reconnect display and restart if needed."
            )
        display = NullDisplayController()

    speech = build_speech_client(config, output_dir)

    return ConversationOrchestrator(
        recorder=recorder or AudioRecorder(),
        speech=speech,
        agent=build_agent_client(config),
        display=display,
        player=player or AudioPlayer(),
        voice=config.tts_voice,
        status_callback=status_callback,
        display_error_callback=display_error_callback,
        agent_trace_callback=agent_trace_callback,
        display_update_callback=display_update_callback,
    )


STATE_LABELS = {
    TurnState.IDLE: "Ready",
    TurnState.LISTENING: "Listening",
    TurnState.TRANSCRIBING: "Transcribing",
    TurnState.THINKING: "Thinking",
    TurnState.SPEAKING: "Speaking",
    TurnState.ERROR: "Error",
}

DEFAULT_WINDOW_GEOMETRY = "560x420"
MIN_WINDOW_SIZE = (420, 320)


class JksApp:
    def __init__(self, root: tk.Tk, orchestrator: Optional[ConversationOrchestrator] = None):
        self.root = root
        self.root.title("JKS Voice Agent")
        self.root.geometry(DEFAULT_WINDOW_GEOMETRY)
        self.root.minsize(*MIN_WINDOW_SIZE)
        self.status = tk.StringVar(value="Ready")
        self.device_status = tk.StringVar(value="OLED ready")
        self.transcript = tk.StringVar(value="")
        self.agent_trace = tk.StringVar(value="Agent trace will appear here.")
        self.display_preview = tk.StringVar(value="neutral READY")
        self._trace_lines: list[str] = []
        self._expression = ExpressionEngine()
        self._rich_ui = hasattr(root, "tk")
        self._history: list[tuple[str, str]] = []
        self._reply_visible = False
        self._busy = False
        self._speaking = False
        self._animation_running = False
        self._animation_frame = 0
        self.orchestrator = orchestrator or build_orchestrator(
            load_config(),
            status_callback=self._show_turn_state,
            display_status_callback=self._show_display_status,
            display_error_callback=self._show_display_status,
            agent_trace_callback=self._show_agent_trace,
        )
        if hasattr(self.orchestrator, "reply_callback"):
            self.orchestrator.reply_callback = self._show_agent_reply
        if hasattr(self.orchestrator, "display_update_callback"):
            self.orchestrator.display_update_callback = self._show_display_preview
        self._recording = False

        if self._rich_ui:
            self._build_rich_layout()
        else:
            self._build_test_layout()
        self._render_display_preview(self._expression.intent_for_state(TurnState.IDLE))

    def _build_test_layout(self) -> None:
        root = self.root
        self.button = ttk.Button(root, text="Speak", command=self.start_turn)
        self.button.pack(padx=16, pady=12)
        ttk.Label(root, textvariable=self.status).pack(padx=16, pady=4)
        ttk.Label(root, textvariable=self.device_status, wraplength=420).pack(padx=16, pady=4)
        self.display_canvas = _make_display_canvas(root)
        self.display_canvas.pack(padx=16, pady=(8, 2))
        ttk.Label(root, textvariable=self.display_preview, wraplength=420).pack(padx=16, pady=2)
        ttk.Label(root, textvariable=self.transcript, wraplength=420).pack(padx=16, pady=12)
        ttk.Label(root, text="Agent Trace").pack(padx=16, pady=(8, 2))
        ttk.Label(root, textvariable=self.agent_trace, wraplength=520).pack(padx=16, pady=4)

    def _build_rich_layout(self) -> None:
        self.root.geometry("780x560")
        self.root.minsize(680, 500)
        self.root.configure(bg="#f6f1eb")

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("JKS.TButton", font=("Segoe UI", 11), padding=(14, 8))
        style.configure("JKS.Secondary.TButton", font=("Segoe UI", 10), padding=(10, 6))

        shell = tk.Frame(self.root, bg="#f6f1eb")
        shell.pack(fill="both", expand=True, padx=18, pady=18)

        header = tk.Frame(shell, bg="#f6f1eb")
        header.pack(fill="x")
        tk.Label(
            header,
            text="JKS Voice Agent",
            bg="#f6f1eb",
            fg="#2d2520",
            font=("Segoe UI Semibold", 18),
        ).pack(side="left")
        tk.Label(
            header,
            textvariable=self.device_status,
            bg="#f6f1eb",
            fg="#71645b",
            font=("Segoe UI", 9),
        ).pack(side="right")

        body = tk.Frame(shell, bg="#f6f1eb")
        body.pack(fill="both", expand=True, pady=(14, 12))

        left = tk.Frame(body, bg="#eee0d2", highlightbackground="#dac9bb", highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 14))
        self.avatar = tk.Canvas(left, width=190, height=170, bg="#eee0d2", highlightthickness=0)
        self.avatar.pack(padx=14, pady=(16, 8))
        tk.Label(
            left,
            textvariable=self.status,
            bg="#eee0d2",
            fg="#3b3029",
            font=("Segoe UI Semibold", 12),
            wraplength=170,
        ).pack(padx=12, pady=(0, 10))
        self.button = ttk.Button(left, text="Speak", command=self.start_turn, style="JKS.TButton")
        self.button.pack(fill="x", padx=18, pady=(0, 8))
        ttk.Button(
            left,
            text="Clear history",
            command=self.clear_history,
            style="JKS.Secondary.TButton",
        ).pack(fill="x", padx=18, pady=(0, 8))
        ttk.Button(
            left,
            text="Stop voice",
            command=self.stop_voice,
            style="JKS.Secondary.TButton",
        ).pack(fill="x", padx=18, pady=(0, 16))

        self.display_canvas = _make_display_canvas(left)
        self.display_canvas.pack(padx=14, pady=(0, 4))
        tk.Label(
            left,
            textvariable=self.display_preview,
            bg="#eee0d2",
            fg="#5f5147",
            font=("Segoe UI", 9),
            wraplength=170,
        ).pack(padx=12, pady=(0, 12))

        right = tk.Frame(body, bg="#fffaf5", highlightbackground="#e1d2c5", highlightthickness=1)
        right.pack(side="left", fill="both", expand=True)
        tk.Label(
            right,
            text="Conversation",
            bg="#fffaf5",
            fg="#4a3a31",
            font=("Segoe UI Semibold", 12),
        ).pack(anchor="w", padx=14, pady=(12, 0))

        text_frame = tk.Frame(right, bg="#fffaf5")
        text_frame.pack(fill="both", expand=True, padx=14, pady=(8, 8))
        self.history_text = tk.Text(
            text_frame,
            wrap="word",
            relief="flat",
            bg="#fffaf5",
            fg="#2d2520",
            insertbackground="#2d2520",
            font=("Segoe UI", 11),
            padx=8,
            pady=8,
            spacing2=3,
            spacing3=8,
        )
        self.history_text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(text_frame, command=self.history_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.history_text.configure(yscrollcommand=scrollbar.set, state="disabled")

        trace = tk.Label(
            right,
            textvariable=self.agent_trace,
            bg="#fffaf5",
            fg="#75675e",
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
            wraplength=500,
        )
        trace.pack(fill="x", padx=18, pady=(0, 12))
        self._draw_avatar("idle")

    def start_turn(self) -> None:
        if self._speaking:
            self.stop_voice()
            return
        if self._busy and not self._recording:
            return
        if not self._recording:
            self._start_recording()
            return

        self._stop_and_run_turn()

    def _start_recording(self) -> None:
        self.button.configure(state="disabled")
        self.status.set("Listening")
        self._reset_agent_trace()
        try:
            self.orchestrator.start_recording()
        except Exception as exc:
            self._finish_error(exc)
            return

        self._recording = True
        self._reply_visible = False
        self.button.configure(text="Stop", state="normal")

    def _stop_and_run_turn(self) -> None:
        self._recording = False
        self._busy = True
        self.button.configure(state="disabled")
        self.status.set("Transcribing")
        self._start_wait_animation()
        thread = threading.Thread(target=self._run_turn, daemon=True)
        thread.start()

    def _run_turn(self) -> None:
        try:
            result = self.orchestrator.finish_voice_turn()
        except Exception as exc:
            self.root.after(0, lambda exc=exc: self._finish_error(exc))
            return
        self.root.after(0, lambda: self._finish_success(result))

    def _finish_success(self, result) -> None:
        self._recording = False
        self._busy = False
        self._speaking = False
        self._stop_wait_animation()
        if result.audio_error:
            self.status.set(f"Voice output failed: {result.audio_error}")
        else:
            self.status.set("Ready")
        if not self._reply_visible:
            self._append_exchange(result.user_text, result.agent_text)
        if result.emotion:
            self._render_display_preview(
                DisplayIntent(
                    result.emotion,
                    getattr(result, "display_text", "") or result.emotion.upper(),
                    getattr(result, "display_duration_ms", 0) or 1200,
                    getattr(result, "display_intensity", "") or "normal",
                )
            )
        self.button.configure(text="Speak", state="normal")
        self._draw_avatar("idle")

    def _finish_error(self, exc: Exception) -> None:
        self._recording = False
        self._busy = False
        self._speaking = False
        self._stop_wait_animation()
        self.status.set(f"Error: {exc}")
        partial_lines = []
        user_text = getattr(exc, "user_text", "")
        audio_path = getattr(exc, "audio_path", None)
        if user_text:
            partial_lines.append(f"You: {user_text}")
        if audio_path:
            partial_lines.append(f"Audio: {Path(audio_path).as_posix()}")
        if partial_lines:
            self.transcript.set("\n".join(partial_lines))
        self.button.configure(text="Speak", state="normal")
        self._draw_avatar("error")

    def _show_turn_state(self, state: TurnState) -> None:
        label = STATE_LABELS.get(state, str(state))
        intent = self._expression.intent_for_state(state)
        self.root.after(0, lambda label=label, intent=intent, state=state: self._set_turn_state_ui(state, label, intent))

    def _show_display_status(self, message: str) -> None:
        self.root.after(0, lambda message=message: self.device_status.set(message))

    def _show_display_preview(self, intent: object) -> None:
        self.root.after(0, lambda intent=intent: self._render_display_preview(intent))

    def _show_agent_trace(self, event: AgentTraceEvent) -> None:
        self.root.after(0, lambda event=event: self._append_agent_trace(event))

    def _show_agent_reply(self, user_text: str, agent_text: str, spoken_text: str) -> None:
        self.root.after(
            0,
            lambda: self._handle_agent_reply(user_text, agent_text, spoken_text),
        )

    def _handle_agent_reply(self, user_text: str, agent_text: str, spoken_text: str) -> None:
        del spoken_text
        self._append_exchange(user_text, agent_text)
        self._reply_visible = True
        self.status.set("Speaking")
        self._speaking = True
        self._stop_wait_animation()
        self.button.configure(text="Stop voice", state="normal")
        self._draw_avatar("speaking")

    def _append_exchange(self, user_text: str, agent_text: str) -> None:
        self._history.append(("You", user_text))
        self._history.append(("Agent", agent_text))
        self.transcript.set(f"You: {user_text}\nAgent: {agent_text}")
        if not self._rich_ui:
            return
        self.history_text.configure(state="normal")
        self.history_text.insert("end", f"You\n{user_text}\n\n", ("user",))
        self.history_text.insert("end", f"Agent\n{agent_text}\n\n", ("agent",))
        self.history_text.tag_configure("user", foreground="#6b5445", font=("Segoe UI Semibold", 10))
        self.history_text.tag_configure("agent", foreground="#2d2520", font=("Segoe UI", 11))
        self.history_text.see("end")
        self.history_text.configure(state="disabled")

    def clear_history(self) -> None:
        self._history.clear()
        self.transcript.set("")
        clear = getattr(self.orchestrator, "clear_history", None)
        if clear is not None:
            clear()
        if self._rich_ui:
            self.history_text.configure(state="normal")
            self.history_text.delete("1.0", "end")
            self.history_text.configure(state="disabled")

    def stop_voice(self) -> None:
        stop = getattr(self.orchestrator, "stop_playback", None)
        if stop is not None:
            stop()
        self.status.set("Stopping voice")
        self.button.configure(state="disabled")

    def _set_turn_state_ui(self, state: TurnState, label: str, intent: DisplayIntent) -> None:
        self.status.set(label)
        self._render_display_preview(intent)
        if state in {TurnState.TRANSCRIBING, TurnState.THINKING}:
            self._start_wait_animation()
        elif state == TurnState.SPEAKING:
            self._stop_wait_animation()
            self._speaking = True
            self.button.configure(text="Stop voice", state="normal")
        elif state in {TurnState.IDLE, TurnState.ERROR}:
            self._stop_wait_animation()
        self._draw_avatar(str(getattr(state, "value", state)))

    def _render_display_preview(self, intent: object) -> None:
        if not isinstance(intent, DisplayIntent):
            self.display_preview.set("screen clear")
            _clear_display_canvas(self.display_canvas)
            return
        label = _preview_text(intent.text or intent.emotion.upper(), 16)
        self.display_preview.set(f"{intent.emotion} {label}")
        _draw_display_canvas(self.display_canvas, intent.emotion, label)

    def _append_agent_trace(self, event: AgentTraceEvent) -> None:
        source = str(getattr(event, "source", "") or "agent").strip()
        message = str(getattr(event, "message", event)).strip()
        if not message:
            return
        line = f"{source}: {message}" if source else message
        if len(line) > 180:
            line = line[:179].rstrip() + "..."
        self._trace_lines.append(line)
        self._trace_lines = self._trace_lines[-10:]
        self.agent_trace.set("\n".join(self._trace_lines))

    def _reset_agent_trace(self) -> None:
        self._trace_lines = []
        self.agent_trace.set("Recording...")

    def _start_wait_animation(self) -> None:
        if not self._rich_ui or self._animation_running:
            return
        self._animation_running = True
        self._animate_wait()

    def _stop_wait_animation(self) -> None:
        self._animation_running = False
        if self._rich_ui:
            self.avatar.delete("wait")

    def _animate_wait(self) -> None:
        if not self._animation_running or not self._rich_ui:
            return
        self._animation_frame = (self._animation_frame + 1) % 4
        self._draw_avatar("thinking")
        dots = "." * self._animation_frame
        self.avatar.delete("wait")
        self.avatar.create_text(
            95,
            145,
            text=f"thinking{dots}",
            fill="#7c6758",
            font=("Segoe UI", 10),
            tags="wait",
        )
        self.root.after(280, self._animate_wait)

    def _draw_avatar(self, mood: str) -> None:
        if not self._rich_ui:
            return
        canvas = self.avatar
        canvas.delete("avatar")
        colors = {
            "listening": ("#d87255", "#f4b39d"),
            "thinking": ("#c7804f", "#f1c08c"),
            "speaking": ("#d95d4c", "#f19a88"),
            "error": ("#b84b4b", "#ed9b9b"),
            "idle": ("#c96b52", "#f0a18d"),
        }
        fill, accent = colors.get(mood, colors["idle"])
        bob = 2 if self._animation_frame % 2 else 0
        canvas.create_oval(48, 46 + bob, 142, 118 + bob, fill=fill, outline="#7f3b31", width=2, tags="avatar")
        canvas.create_arc(28, 55 + bob, 66, 100 + bob, start=90, extent=230, style="arc", outline="#7f3b31", width=4, tags="avatar")
        canvas.create_arc(124, 55 + bob, 162, 100 + bob, start=220, extent=230, style="arc", outline="#7f3b31", width=4, tags="avatar")
        canvas.create_oval(24, 45 + bob, 49, 70 + bob, fill=accent, outline="#7f3b31", width=2, tags="avatar")
        canvas.create_oval(141, 45 + bob, 166, 70 + bob, fill=accent, outline="#7f3b31", width=2, tags="avatar")
        canvas.create_line(72, 48 + bob, 68, 28 + bob, fill="#7f3b31", width=3, tags="avatar")
        canvas.create_line(118, 48 + bob, 122, 28 + bob, fill="#7f3b31", width=3, tags="avatar")
        canvas.create_oval(61, 22 + bob, 78, 39 + bob, fill="#fffaf5", outline="#7f3b31", width=2, tags="avatar")
        canvas.create_oval(112, 22 + bob, 129, 39 + bob, fill="#fffaf5", outline="#7f3b31", width=2, tags="avatar")
        if mood == "sleepy":
            canvas.create_line(66, 31 + bob, 73, 31 + bob, fill="#2d2520", width=2, tags="avatar")
            canvas.create_line(117, 31 + bob, 124, 31 + bob, fill="#2d2520", width=2, tags="avatar")
        else:
            canvas.create_oval(68, 29 + bob, 73, 34 + bob, fill="#2d2520", outline="", tags="avatar")
            canvas.create_oval(117, 29 + bob, 122, 34 + bob, fill="#2d2520", outline="", tags="avatar")
        if mood == "speaking":
            canvas.create_oval(82, 82 + bob, 108, 98 + bob, outline="#5b2b25", width=3, tags="avatar")
        elif mood == "thinking":
            canvas.create_line(82, 90 + bob, 108, 90 + bob, fill="#5b2b25", width=3, tags="avatar")
        elif mood == "error":
            canvas.create_line(82, 96 + bob, 108, 86 + bob, fill="#5b2b25", width=3, tags="avatar")
        else:
            canvas.create_arc(78, 78 + bob, 112, 103 + bob, start=200, extent=140, style="arc", outline="#5b2b25", width=3, tags="avatar")


class _NullDisplayCanvas:
    def pack(self, **kwargs) -> None:
        return None

    def delete(self, *args) -> None:
        return None

    def create_rectangle(self, *args, **kwargs) -> None:
        return None

    def create_oval(self, *args, **kwargs) -> None:
        return None

    def create_arc(self, *args, **kwargs) -> None:
        return None

    def create_line(self, *args, **kwargs) -> None:
        return None

    def create_text(self, *args, **kwargs) -> None:
        return None


def _make_display_canvas(root) -> object:
    try:
        return tk.Canvas(root, width=192, height=96, bg="#050505", highlightthickness=1)
    except Exception:
        return _NullDisplayCanvas()


def _clear_display_canvas(canvas) -> None:
    canvas.delete("all")
    canvas.create_rectangle(0, 0, 192, 96, fill="#050505", outline="#333333")


def _draw_display_canvas(canvas, emotion: str, label: str) -> None:
    _clear_display_canvas(canvas)
    face = "#d8ff74"
    accent = "#72d7ff"
    canvas.create_rectangle(8, 8, 184, 88, outline="#5dff9a")
    if emotion in {"happy", "speaking"}:
        canvas.create_arc(50, 34, 78, 58, start=180, extent=180, outline=face, width=2)
        canvas.create_arc(114, 34, 142, 58, start=180, extent=180, outline=face, width=2)
        canvas.create_arc(76, 48, 116, 78, start=200, extent=140, outline=face, width=2)
    elif emotion == "surprised":
        canvas.create_oval(52, 34, 76, 58, outline=face, width=2)
        canvas.create_oval(116, 34, 140, 58, outline=face, width=2)
        canvas.create_oval(86, 56, 106, 76, outline=face, width=2)
    elif emotion == "sleepy":
        canvas.create_line(52, 48, 76, 48, fill=face, width=2)
        canvas.create_line(116, 48, 140, 48, fill=face, width=2)
        canvas.create_line(82, 66, 110, 66, fill=face, width=2)
    elif emotion in {"angry", "error"}:
        canvas.create_line(50, 38, 78, 52, fill=face, width=2)
        canvas.create_line(114, 52, 142, 38, fill=face, width=2)
        canvas.create_line(80, 66, 112, 62, fill=face, width=2)
    else:
        canvas.create_oval(54, 38, 72, 54, outline=face, width=2)
        canvas.create_oval(120, 38, 138, 54, outline=face, width=2)
        canvas.create_line(82, 66, 110, 66, fill=face, width=2)
    if emotion in {"thinking", "listening"}:
        canvas.create_text(154, 28, text="...", fill=accent, font=("Menlo", 13, "bold"))
    canvas.create_text(96, 82, text=label, fill="#f6f6f6", font=("Menlo", 12, "bold"))


def _preview_text(text: object, limit: int = 16) -> str:
    printable = "".join(ch for ch in str(text) if " " <= ch <= "~")
    return printable[:limit]


def _print_help(stdout: TextIO) -> None:
    stdout.write(
        "JKS Voice Agent\n"
        "\n"
        "Usage:\n"
        "  python -m jks [--help]\n"
        "\n"
        "Environment:\n"
        "  JKS_AGENT_MODE      local, http, or ssh agent transport\n"
        "  JKS_AGENT_COMMAND   Local Hermes / Grantly command when mode=local\n"
        "  JKS_AGENT_ENDPOINT  Optional Hermes / Gran agent HTTP endpoint\n"
        "  JKS_STT_ENDPOINT    Speech-to-text endpoint\n"
        "  JKS_TTS_ENDPOINT    Text-to-speech endpoint\n"
        "  JKS_OLED_PORT       OLED serial port\n"
    )


def main(argv: Optional[Sequence[str]] = None, stdout: TextIO = sys.stdout) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if "--help" in args or "-h" in args:
        _print_help(stdout)
        return 0

    root = tk.Tk()
    JksApp(root)
    root.mainloop()
    return 0
