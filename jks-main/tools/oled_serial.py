"""Encode and send newline-delimited JSON commands for the OLED firmware."""

from __future__ import annotations

import argparse
import json
import os
import sys
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
from typing import BinaryIO, Iterable, Mapping, Optional, Sequence

if not hasattr(os, "O_NOCTTY"):
    os.O_NOCTTY = 0


DEFAULT_BAUD = 115200

_BAUD_RATES = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}

for _baud in (230400, 460800, 921600):
    _termios_rate = getattr(termios, f"B{_baud}", None)
    if _termios_rate is not None:
        _BAUD_RATES[_baud] = _termios_rate


def encode_command(command: Mapping[str, object]) -> bytes:
    """Return one compact UTF-8 JSON command frame terminated by LF."""
    line = json.dumps(command, ensure_ascii=False, separators=(",", ":"))
    return (line + "\n").encode("utf-8")


def text_command(text: str) -> dict[str, str]:
    return {"cmd": "text", "text": text}


def emotion_command(emotion: str) -> dict[str, str]:
    return {"cmd": "emotion", "name": emotion}


def clear_command() -> dict[str, str]:
    return {"cmd": "clear"}


def probe_command() -> dict[str, str]:
    return {"cmd": "probe"}


def encode_text(text: str) -> bytes:
    return encode_command(text_command(text))


def encode_emotion(emotion: str) -> bytes:
    return encode_command(emotion_command(emotion))


def encode_clear() -> bytes:
    return encode_command(clear_command())


def encode_probe() -> bytes:
    return encode_command(probe_command())


def _configure_serial_fd(fd: int, baud: int) -> None:
    if baud not in _BAUD_RATES:
        supported = ", ".join(str(rate) for rate in sorted(_BAUD_RATES))
        raise ValueError(f"unsupported baud rate {baud}; choose one of: {supported}")

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
    )
    attrs[1] &= ~termios.OPOST
    attrs[2] &= ~(termios.CSIZE | termios.PARENB)
    attrs[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
    attrs[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
    attrs[4] = _BAUD_RATES[baud]
    attrs[5] = _BAUD_RATES[baud]
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def open_serial(path: str, baud: int = DEFAULT_BAUD) -> BinaryIO:
    fd = os.open(path, os.O_WRONLY | os.O_NOCTTY)
    try:
        if os.isatty(fd):
            _configure_serial_fd(fd, baud)
        return os.fdopen(fd, "wb", buffering=0)
    except Exception:
        os.close(fd)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send one newline-delimited JSON OLED command over serial.",
    )
    parser.add_argument(
        "--port",
        help="Serial device path, for example /dev/tty.usbserial-0001. Defaults to stdout.",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD,
        help=f"Baud rate used when --port is a TTY. Default: {DEFAULT_BAUD}.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    text_parser = subparsers.add_parser("text", help="Display text on the OLED.")
    text_parser.add_argument("text")

    emotion_parser = subparsers.add_parser("emotion", help="Display an emotion state.")
    emotion_parser.add_argument("emotion")

    subparsers.add_parser("clear", help="Clear the OLED.")
    subparsers.add_parser("probe", help="Probe the OLED firmware.")
    return parser


def frame_from_args(args: argparse.Namespace) -> bytes:
    if args.command == "text":
        return encode_text(args.text)
    if args.command == "emotion":
        return encode_emotion(args.emotion)
    if args.command == "clear":
        return encode_clear()
    if args.command == "probe":
        return encode_probe()
    raise ValueError(f"unknown command: {args.command}")


def write_frame(frame: bytes, output: BinaryIO) -> None:
    output.write(frame)
    output.flush()


def main(argv: Optional[Sequence[str]] = None, output: Optional[BinaryIO] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    frame = frame_from_args(args)

    if args.port:
        with open_serial(args.port, args.baud) as port:
            write_frame(frame, port)
    else:
        write_frame(frame, output if output is not None else sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
