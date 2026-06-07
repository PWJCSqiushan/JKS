import io
import json
import socket
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse


class FakeServiceServer:
    def __init__(
        self,
        base_url: str,
        httpd: ThreadingHTTPServer,
        thread: threading.Thread,
        events: list[dict[str, object]],
    ):
        self.base_url = base_url
        self.events = events
        self._httpd = httpd
        self._thread = thread
        self._stopped = False
        self._stop_lock = threading.Lock()
        self.host, self.port = httpd.server_address[:2]

    @property
    def active_connection_count(self) -> int:
        return self._httpd.active_connection_count

    def stop(self) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True

        self._httpd.close_active_connections()
        self._httpd.shutdown()
        self._httpd.close_active_connections()
        self._httpd.server_close()
        self._thread.join(timeout=2)
        self._httpd.close_active_connections()
        self._httpd.wait_until_idle(timeout=1.0)


class TrackingThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self._active_connections = set()
        self._active_connections_lock = threading.Lock()

    @property
    def active_connection_count(self) -> int:
        with self._active_connections_lock:
            return len(self._active_connections)

    def finish_request(self, request, client_address) -> None:
        try:
            request.settimeout(0.25)
        except OSError:
            pass

        with self._active_connections_lock:
            self._active_connections.add(request)
        try:
            super().finish_request(request, client_address)
        finally:
            with self._active_connections_lock:
                self._active_connections.discard(request)
            self._close_connection(request)

    def close_active_connections(self) -> None:
        with self._active_connections_lock:
            connections = list(self._active_connections)
        for connection in connections:
            self._close_connection(connection)

    def wait_until_idle(self, timeout: float) -> None:
        deadline = time.monotonic() + max(timeout, 0.0)
        while self.active_connection_count > 0 and time.monotonic() < deadline:
            time.sleep(0.01)

    @staticmethod
    def _close_connection(connection) -> None:
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            connection.close()
        except OSError:
            pass


def start_fake_services(host: str = "127.0.0.1", port: int = 0) -> FakeServiceServer:
    events: list[dict[str, object]] = []
    events_lock = threading.Lock()
    handler = _make_handler(events, events_lock)
    httpd = TrackingThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = httpd.server_address[:2]
    base_host = host or actual_host
    base_url = f"http://{base_host}:{actual_port}"
    thread = threading.Thread(
        target=httpd.serve_forever,
        kwargs={"poll_interval": 0.05},
        name="jks-fake-services",
        daemon=True,
    )
    thread.start()
    return FakeServiceServer(base_url, httpd, thread, events)


def _make_handler(events: list[dict[str, object]], events_lock: threading.Lock):
    class FakeServiceHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/health":
                self._record("health")
                self._send_json(200, {"ok": True})
                return

            self._send_not_found(path)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/stt":
                self._read_body()
                self._record("stt")
                self._send_json(200, {"text": "hello agent"})
                return

            if path == "/chat":
                payload = self._read_json()
                if payload is None:
                    self._send_json(400, {"error": "invalid json"})
                    return

                message = str(payload.get("message", ""))
                conversation_id = payload.get("conversation_id")
                self._record(
                    "chat",
                    format="legacy",
                    message=message,
                    conversation_id=conversation_id,
                )
                self._send_json(
                    200,
                    {
                        "text": f"Fake reply to: {message}",
                        "emotion": "happy",
                        "display_text": "DONE",
                        "duration_ms": 1200,
                        "intensity": "normal",
                    },
                )
                return

            if path == "/v1/chat/completions":
                payload = self._read_json()
                if payload is None:
                    self._send_json(400, {"error": "invalid json"})
                    return

                message = self._last_user_message(payload)
                reply_payload = {
                    "text": f"Fake reply to: {message}",
                    "emotion": "happy",
                    "display_text": "DONE",
                    "duration_ms": 1200,
                    "intensity": "normal",
                }
                self._record(
                    "chat",
                    format="openai",
                    message=message,
                    model=payload.get("model"),
                    stream=payload.get("stream"),
                    session_id=self.headers.get("X-Hermes-Session-Id", ""),
                    auth_present=bool(self.headers.get("Authorization")),
                )
                self._send_json(
                    200,
                    {
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": json.dumps(reply_payload),
                                },
                                "finish_reason": "stop",
                            }
                        ]
                    },
                )
                return

            if path == "/tts":
                payload = self._read_json()
                if payload is None:
                    self._send_json(400, {"error": "invalid json"})
                    return

                self._record(
                    "tts",
                    text=payload.get("text"),
                    voice=payload.get("voice"),
                )
                self._send_bytes(200, _make_wav_bytes(), "audio/wav")
                return

            self._read_body()
            self._send_not_found(path)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _read_body(self) -> bytes:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            if content_length <= 0:
                return b""
            try:
                return self.rfile.read(content_length)
            except OSError:
                return b""

        def _read_json(self) -> Optional[dict[str, object]]:
            body = self._read_body()
            if not body:
                return {}
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            if not isinstance(payload, dict):
                return {}
            return payload

        def _record(self, kind: str, **fields: object) -> None:
            event = {"kind": kind}
            event.update(fields)
            with events_lock:
                events.append(event)

        def _last_user_message(self, payload: dict[str, object]) -> str:
            messages = payload.get("messages")
            if not isinstance(messages, list):
                return ""

            fallback = ""
            selected = ""
            for item in messages:
                if not isinstance(item, dict):
                    continue
                content = self._content_to_text(item.get("content"))
                if content:
                    fallback = content
                if item.get("role") == "user" and content:
                    selected = content
            return selected or fallback

        def _content_to_text(self, content: object) -> str:
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                return "".join(parts)
            return ""

        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self._send_bytes(status, body, "application/json")

        def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                return

        def _send_not_found(self, path: str) -> None:
            self._send_json(404, {"error": "not found", "path": path})

    return FakeServiceHandler


def _make_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 400)
    return buffer.getvalue()
