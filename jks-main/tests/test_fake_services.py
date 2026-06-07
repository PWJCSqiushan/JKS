import io
import json
import socket
import time
import unittest
import wave

import requests

from tools.jks_fake_services import start_fake_services


class FakeServiceTests(unittest.TestCase):
    def test_fake_service_health_stt_chat_tts_contracts_and_events(self):
        server = start_fake_services()
        try:
            base_url = server.base_url

            health = requests.get(base_url + "/health", timeout=2)
            self.assertEqual(health.status_code, 200)
            self.assertIs(health.json()["ok"], True)

            stt = requests.post(
                base_url + "/stt",
                files={"audio": ("input.wav", b"audio")},
                timeout=2,
            )
            self.assertEqual(stt.status_code, 200)
            self.assertEqual(stt.json()["text"], "hello agent")

            chat = requests.post(
                base_url + "/chat",
                json={"message": "hello", "conversation_id": "c1"},
                timeout=2,
            )
            self.assertEqual(chat.status_code, 200)
            self.assertEqual(
                chat.json(),
                {
                    "text": "Fake reply to: hello",
                    "emotion": "happy",
                    "display_text": "DONE",
                    "duration_ms": 1200,
                    "intensity": "normal",
                },
            )

            openai_chat = requests.post(
                base_url + "/v1/chat/completions",
                json={
                    "model": "gran-agent",
                    "messages": [{"role": "user", "content": "hello openai"}],
                    "stream": False,
                },
                headers={
                    "Authorization": "Bearer secret-token",
                    "X-Hermes-Session-Id": "c-openai",
                },
                timeout=2,
            )
            self.assertEqual(openai_chat.status_code, 200)
            openai_payload = openai_chat.json()
            content = openai_payload["choices"][0]["message"]["content"]
            self.assertEqual(
                json.loads(content),
                {
                    "text": "Fake reply to: hello openai",
                    "emotion": "happy",
                    "display_text": "DONE",
                    "duration_ms": 1200,
                    "intensity": "normal",
                },
            )

            tts = requests.post(
                base_url + "/tts",
                json={"text": "reply", "voice": "warm"},
                timeout=2,
            )
            self.assertEqual(tts.status_code, 200)
            self.assertEqual(tts.content[:4], b"RIFF")
            with wave.open(io.BytesIO(tts.content), "rb") as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getframerate(), 8000)
                self.assertEqual(wav.getnframes(), 400)

            self.assertEqual(
                [event["kind"] for event in server.events],
                ["health", "stt", "chat", "chat", "tts"],
            )
            self.assertEqual(server.events[3]["format"], "openai")
            self.assertEqual(server.events[3]["model"], "gran-agent")
            self.assertEqual(server.events[3]["message"], "hello openai")
            self.assertEqual(server.events[3]["session_id"], "c-openai")
            self.assertIs(server.events[3]["auth_present"], True)
        finally:
            server.stop()

    def test_openai_chat_extracts_user_content_parts(self):
        server = start_fake_services()
        try:
            response = requests.post(
                server.base_url + "/v1/chat/completions",
                json={
                    "model": "gran-agent",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "hello "},
                                {"text": "agent"},
                            ],
                        }
                    ],
                    "stream": False,
                },
                timeout=2,
            )

            self.assertEqual(response.status_code, 200)
            content = response.json()["choices"][0]["message"]["content"]
            self.assertEqual(json.loads(content)["text"], "Fake reply to: hello agent")
            self.assertEqual(server.events[0]["message"], "hello agent")
        finally:
            server.stop()

    def test_invalid_json_requests_return_400_without_recording_events(self):
        server = start_fake_services()
        try:
            for path in ("/chat", "/v1/chat/completions", "/tts"):
                with self.subTest(path=path):
                    before_count = len(server.events)
                    response = requests.post(
                        server.base_url + path,
                        data=b"{invalid",
                        headers={"Content-Type": "application/json"},
                        timeout=2,
                    )

                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json(), {"error": "invalid json"})
                    self.assertEqual(len(server.events), before_count)
        finally:
            server.stop()

    def test_fake_service_returns_404_for_unknown_paths(self):
        server = start_fake_services()
        try:
            response = requests.get(server.base_url + "/missing", timeout=2)

            self.assertEqual(response.status_code, 404)
            self.assertIn("error", response.json())
        finally:
            server.stop()

    def test_stop_closes_loopback_server(self):
        server = start_fake_services()
        thread = server._thread

        try:
            self.assertTrue(thread.is_alive())
            self.assertEqual(requests.get(server.base_url + "/health", timeout=2).status_code, 200)

            server.stop()

            self.assertFalse(thread.is_alive())
            server.stop()
        finally:
            server.stop()

    def test_stop_closes_partial_request_connections(self):
        server = start_fake_services()
        sock = socket.create_connection((server.host, server.port), timeout=2)
        try:
            sock.sendall(
                b"POST /stt HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Length: 999999\r\n"
                b"\r\n"
                b"x"
            )
            deadline = time.time() + 2.0
            while server.active_connection_count == 0 and time.time() < deadline:
                time.sleep(0.01)

            self.assertGreater(server.active_connection_count, 0)

            server.stop()

            self.assertEqual(server.active_connection_count, 0)
        finally:
            sock.close()
            server.stop()


if __name__ == "__main__":
    unittest.main()
