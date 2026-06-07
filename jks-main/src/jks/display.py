from __future__ import annotations

from dataclasses import dataclass
import json
import os
import select
import time
try:
    import termios
except ModuleNotFoundError:
    class _TermiosFallback:
        IGNBRK = 0
        BRKINT = 0
        PARMRK = 0
        ISTRIP = 0
        INLCR = 0
        IGNCR = 0
        ICRNL = 0
        IXON = 0
        IXOFF = 0
        IXANY = 0
        OPOST = 0
        CSIZE = 0
        PARENB = 0
        CS8 = 0
        CLOCAL = 0
        CREAD = 0
        ECHO = 0
        ECHONL = 0
        ICANON = 0
        ISIG = 0
        IEXTEN = 0
        TCSANOW = 0
        B9600 = 9600
        B19200 = 19200
        B38400 = 38400
        B57600 = 57600
        B115200 = 115200

        @staticmethod
        def tcgetattr(fd: int):
            raise OSError("termios is not available on this platform")

        @staticmethod
        def tcsetattr(fd: int, when: int, attrs) -> None:
            raise OSError("termios is not available on this platform")

    termios = _TermiosFallback()
from typing import BinaryIO, Mapping, Optional

if not hasattr(os, "O_NOCTTY"):
    os.O_NOCTTY = 0


ALLOWED_EMOTIONS = {
    "neutral",
    "happy",
    "thinking",
    "speaking",
    "listening",
    "surprised",
    "sleepy",
    "sad",
    "angry",
    "error",
}

def _build_baud_rates() -> dict[int, int]:
    rates = {}
    for baud in (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600):
        name = f"B{baud}"
        if hasattr(termios, name):
            rates[baud] = getattr(termios, name)
    return rates


_BAUD_RATES = _build_baud_rates()


@dataclass(frozen=True)
class DisplayIntent:
    emotion: str
    text: str = ""
    duration_ms: int = 1200
    intensity: str = "normal"


def _oled_text(text: object, limit: int = 14) -> str:
    printable = "".join(ch for ch in str(text) if " " <= ch <= "~")
    return printable[:limit]


class DisplayController:
    def __init__(self, output: BinaryIO, ack_input: Optional[BinaryIO] = None):
        self._output = output
        self._ack_input = ack_input

    def show(self, intent: DisplayIntent) -> None:
        emotion = intent.emotion if intent.emotion in ALLOWED_EMOTIONS else "neutral"
        text = intent.text or emotion.upper()
        self._write(
            {
                "cmd": "emotion",
                "name": emotion,
                "text": _oled_text(text),
                "duration_ms": _duration_ms(intent.duration_ms),
                "intensity": _intensity(intent.intensity),
            }
        )

    def clear(self) -> None:
        self._write({"cmd": "clear"})

    def probe(self) -> None:
        self._write({"cmd": "probe"})

    def read_ack(self, timeout: float = 0.0) -> Optional[dict[str, object]]:
        if self._ack_input is None:
            return None

        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            remaining = max(deadline - time.monotonic(), 0.0)
            try:
                ready, _, _ = select.select([self._ack_input], [], [], remaining)
            except (OSError, TypeError, ValueError):
                ready = [self._ack_input]
            if not ready:
                return None

            line = self._ack_input.readline()
            if line:
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    if timeout <= 0 or time.monotonic() >= deadline:
                        return None
                    continue

            if timeout <= 0 or time.monotonic() >= deadline:
                return None

    def _write(self, payload: Mapping[str, object]) -> None:
        frame = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._output.write(frame.encode("utf-8") + b"\n")
        self._output.flush()


class NullDisplayController:
    def show(self, intent: DisplayIntent) -> None:
        return None

    def clear(self) -> None:
        return None

    def probe(self) -> None:
        return None

    def read_ack(self, timeout: float = 0.0) -> None:
        return None


def _baud_constant(baud: int) -> int:
    if baud not in _BAUD_RATES:
        supported = ", ".join(str(rate) for rate in sorted(_BAUD_RATES))
        raise ValueError(f"unsupported baud rate {baud}; choose one of: {supported}")
    return _BAUD_RATES[baud]


def _duration_ms(raw: object) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1200
    return max(200, min(value, 5000))


def _intensity(raw: object) -> str:
    value = str(raw)
    if value in {"soft", "normal", "high"}:
        return value
    return "normal"


def _configure_serial_fd(fd: int, baud: int) -> None:
    baud_constant = _baud_constant(baud)
    attrs = termios.tcgetattr(fd)
    attrs[0] &= ~(
        termios.IGNBRK
        | termios.BRKINT
        | termios.PARMRK
        | termios.ISTRIP
        | termios.INLCR
        | termios.IGNCR
        | termios.ICRNL
        | termios.IXON
        | termios.IXOFF
        | termios.IXANY
    )
    attrs[1] &= ~termios.OPOST
    attrs[2] &= ~(termios.CSIZE | termios.PARENB)
    attrs[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
    attrs[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
    attrs[4] = baud_constant
    attrs[5] = baud_constant
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def open_serial_output(path: str, baud: int) -> BinaryIO:
    """Open serial port for OLED communication. Works on Windows and Unix."""
    _baud_constant(baud)

    try:
        import serial

        ser = serial.Serial(path, baud, timeout=0.05, write_timeout=1)
        wrapper = _SerialWrapper(ser)
        wrapper.settle_on_open()
        return wrapper
    except ImportError:
        pass
    except Exception as exc:
        if os.name == "nt" and not path.startswith("/"):
            raise OSError(f"Failed to open serial port {path}: {exc}") from exc

    fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
    try:
        if os.isatty(fd):
            _configure_serial_fd(fd, baud)
        return os.fdopen(fd, "r+b", buffering=0)
    except Exception:
        os.close(fd)
        raise


class _SerialWrapper:
    """Small adapter that lets pyserial behave like a binary file object."""

    def __init__(self, ser):
        self._ser = ser
        self.drain_stale_input = True
        self.startup_delay = 4.0

    def write(self, data: bytes) -> int:
        return self._ser.write(data)

    def flush(self) -> None:
        self._ser.flush()

    def readline(self) -> bytes:
        return self._ser.readline()

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self._ser.read_all()
        return self._ser.read(size)

    def close(self) -> None:
        self._ser.close()

    def settle_on_open(self) -> None:
        if self.startup_delay <= 0:
            return
        time.sleep(self.startup_delay)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if self.readline():
                continue
            time.sleep(0.05)
        self.startup_delay = 0.0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False
