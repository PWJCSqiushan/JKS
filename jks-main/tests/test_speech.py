import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jks.speech import FakeSpeechClient, FishAudioSpeechClient, HttpSpeechClient, SpeechProviderError


class SpeechTests(unittest.TestCase):
    def test_fake_speech_client_is_deterministic(self):
        client = FakeSpeechClient(text="hello agent")

        self.assertEqual(client.transcribe(Path("input.wav")), "hello agent")
        output = client.synthesize("reply", "warm")

        self.assertTrue(output.exists())
        self.assertGreater(output.stat().st_size, 0)
        self.assertEqual(output.read_bytes()[:4], b"RIFF")

    def test_http_stt_uploads_audio_file_and_returns_text(self):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"text": "transcribed text"}

        def fake_post(endpoint, *, files, timeout):
            self.assertEqual(endpoint, "https://speech.test/stt")
            self.assertEqual(timeout, 60)
            uploaded = files["audio"]
            self.assertEqual(uploaded.name, str(audio_path))
            self.assertEqual(uploaded.read(), b"audio-bytes")
            return FakeResponse()

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "input.wav"
            audio_path.write_bytes(b"audio-bytes")

            with patch("jks.speech.requests.post", side_effect=fake_post) as post:
                client = HttpSpeechClient(
                    stt_endpoint="https://speech.test/stt",
                    tts_endpoint="https://speech.test/tts",
                    output_dir=Path(temp_dir),
                )

                result = client.transcribe(audio_path)

        self.assertEqual(result, "transcribed text")
        post.assert_called_once()

    def test_http_tts_posts_json_and_writes_unique_audio_files(self):
        class FakeResponse:
            content = b"audio-bytes"

            def raise_for_status(self):
                pass

            def json(self):
                return {"text": "ignored"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("jks.speech.requests.post", return_value=FakeResponse()) as post:
                client = HttpSpeechClient(
                    stt_endpoint="https://speech.test/stt",
                    tts_endpoint="https://speech.test/tts",
                    output_dir=Path(temp_dir),
                )
                first_output = client.synthesize("hello", "warm")
                second_output = client.synthesize("hello again", "warm")

            self.assertEqual(first_output.parent, Path(temp_dir))
            self.assertTrue(first_output.name.startswith("tts-output-"))
            self.assertTrue(first_output.name.endswith(".wav"))
            self.assertTrue(first_output.exists())
            self.assertEqual(first_output.read_bytes(), b"audio-bytes")
            self.assertEqual(second_output.parent, Path(temp_dir))
            self.assertTrue(second_output.name.startswith("tts-output-"))
            self.assertTrue(second_output.name.endswith(".wav"))
            self.assertTrue(second_output.exists())
            self.assertEqual(second_output.read_bytes(), b"audio-bytes")
            self.assertNotEqual(first_output, second_output)

        post.assert_any_call(
            "https://speech.test/tts",
            json={"text": "hello", "voice": "warm"},
            timeout=60,
        )
        post.assert_any_call(
            "https://speech.test/tts",
            json={"text": "hello again", "voice": "warm"},
            timeout=60,
        )
        self.assertEqual(post.call_count, 2)

    def test_http_stt_sends_bearer_token_when_configured(self):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"text": "transcribed text"}

        def fake_post(endpoint, *, files, headers, timeout):
            self.assertEqual(headers, {"Authorization": "Bearer stt-secret"})
            return FakeResponse()

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "input.wav"
            audio_path.write_bytes(b"audio-bytes")

            with patch("jks.speech.requests.post", side_effect=fake_post):
                client = HttpSpeechClient(
                    stt_endpoint="https://speech.test/stt",
                    tts_endpoint="https://speech.test/tts",
                    output_dir=Path(temp_dir),
                    stt_token="stt-secret",
                )

                result = client.transcribe(audio_path)

        self.assertEqual(result, "transcribed text")

    def test_http_tts_sends_bearer_token_when_configured(self):
        class FakeResponse:
            content = b"audio-bytes"

            def raise_for_status(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("jks.speech.requests.post", return_value=FakeResponse()) as post:
                client = HttpSpeechClient(
                    stt_endpoint="https://speech.test/stt",
                    tts_endpoint="https://speech.test/tts",
                    output_dir=Path(temp_dir),
                    tts_token="tts-secret",
                )

                client.synthesize("hello", "warm")

        post.assert_called_once_with(
            "https://speech.test/tts",
            json={"text": "hello", "voice": "warm"},
            headers={"Authorization": "Bearer tts-secret"},
            timeout=60,
        )

    def test_fish_audio_stt_posts_audio_with_bearer_auth(self):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"text": "fish transcript", "duration": 1.2, "segments": []}

        def fake_post(endpoint, *, files, data, headers, timeout):
            self.assertEqual(endpoint, "https://api.fish.audio/v1/asr")
            self.assertEqual(headers, {"Authorization": "Bearer fish-secret"})
            self.assertEqual(data, {"ignore_timestamps": "true"})
            self.assertEqual(timeout, 60)
            self.assertEqual(files["audio"].read(), b"audio-bytes")
            return FakeResponse()

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "input.wav"
            audio_path.write_bytes(b"audio-bytes")
            with patch("jks.speech.requests.post", side_effect=fake_post):
                client = FishAudioSpeechClient(
                    api_key="fish-secret",
                    output_dir=Path(temp_dir),
                )
                result = client.transcribe(audio_path)

        self.assertEqual(result, "fish transcript")

    def test_fish_audio_tts_posts_low_latency_streaming_payload_and_writes_mp3(self):
        class FakeResponse:
            closed = False

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size):
                self.chunk_size = chunk_size
                yield b"mp3-"
                yield b"bytes"
                yield b""

            def close(self):
                self.closed = True

        response = FakeResponse()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("jks.speech.requests.post", return_value=response) as post:
                client = FishAudioSpeechClient(
                    api_key="fish-secret",
                    output_dir=Path(temp_dir),
                    tts_model="s2-pro",
                    tts_latency="low",
                )
                output = client.synthesize("hello", "fish-voice-id")
                output_bytes = output.read_bytes()

        self.assertEqual(output.suffix, ".mp3")
        self.assertEqual(output_bytes, b"mp3-bytes")
        self.assertEqual(response.chunk_size, 8192)
        self.assertTrue(response.closed)
        post.assert_called_once_with(
            "https://api.fish.audio/v1/tts",
            json={
                "text": "hello",
                "format": "mp3",
                "latency": "low",
                "chunk_length": 100,
                "min_chunk_length": 0,
                "reference_id": "fish-voice-id",
            },
            headers={
                "Authorization": "Bearer fish-secret",
                "Content-Type": "application/json",
                "model": "s2-pro",
            },
            timeout=60,
            stream=True,
        )

    def test_fish_audio_tts_omits_default_voice_reference(self):
        class FakeResponse:
            content = b"mp3-bytes"

            def raise_for_status(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("jks.speech.requests.post", return_value=FakeResponse()) as post:
                client = FishAudioSpeechClient("fish-secret", Path(temp_dir))
                client.synthesize("hello", "default")

        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "text": "hello",
                "format": "mp3",
                "latency": "low",
                "chunk_length": 100,
                "min_chunk_length": 0,
            },
        )

    def test_fish_audio_tts_streams_chunks_directly_to_player(self):
        class FakeResponse:
            closed = False

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size):
                self.chunk_size = chunk_size
                yield b"mp3-"
                yield b"bytes"

            def close(self):
                self.closed = True

        class FakePlayer:
            def __init__(self):
                self.streams = []

            def play_stream(self, chunks, suffix):
                self.streams.append((list(chunks), suffix))

        response = FakeResponse()
        player = FakePlayer()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("jks.speech.requests.post", return_value=response) as post:
                client = FishAudioSpeechClient(
                    api_key="fish-secret",
                    output_dir=Path(temp_dir),
                    tts_model="s2-pro",
                    tts_latency="low",
                )
                result = client.synthesize_and_play("hello", "fish-voice-id", player)

        self.assertIsNone(result)
        self.assertEqual(player.streams, [([b"mp3-", b"bytes"], ".mp3")])
        self.assertEqual(response.chunk_size, 8192)
        self.assertTrue(response.closed)
        self.assertEqual(post.call_args.kwargs["stream"], True)

    def test_stt_provider_failures_are_wrapped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "input.wav"
            audio_path.write_bytes(b"audio-bytes")
            client = HttpSpeechClient(
                stt_endpoint="https://speech.test/stt",
                tts_endpoint="https://speech.test/tts",
                output_dir=Path(temp_dir),
            )

            with patch("jks.speech.requests.post", side_effect=OSError("offline")):
                with self.assertRaises(SpeechProviderError):
                    client.transcribe(audio_path)

    def test_stt_json_and_key_failures_are_wrapped(self):
        class InvalidJsonResponse:
            def raise_for_status(self):
                pass

            def json(self):
                raise ValueError("not json")

        class MissingTextResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"message": "missing text"}

        class NullTextResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"text": None}

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "input.wav"
            audio_path.write_bytes(b"audio-bytes")
            client = HttpSpeechClient(
                stt_endpoint="https://speech.test/stt",
                tts_endpoint="https://speech.test/tts",
                output_dir=Path(temp_dir),
            )

            with patch("jks.speech.requests.post", return_value=InvalidJsonResponse()):
                with self.assertRaises(SpeechProviderError):
                    client.transcribe(audio_path)

            with patch("jks.speech.requests.post", return_value=MissingTextResponse()):
                with self.assertRaises(SpeechProviderError):
                    client.transcribe(audio_path)

            with patch("jks.speech.requests.post", return_value=NullTextResponse()):
                with self.assertRaises(SpeechProviderError):
                    client.transcribe(audio_path)

    def test_stt_audio_file_failures_are_wrapped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = HttpSpeechClient(
                stt_endpoint="https://speech.test/stt",
                tts_endpoint="https://speech.test/tts",
                output_dir=Path(temp_dir),
            )

            with self.assertRaises(SpeechProviderError):
                client.transcribe(Path(temp_dir) / "missing.wav")

    def test_tts_provider_failures_are_wrapped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = HttpSpeechClient(
                stt_endpoint="https://speech.test/stt",
                tts_endpoint="https://speech.test/tts",
                output_dir=Path(temp_dir),
            )

            with patch("jks.speech.requests.post", side_effect=OSError("offline")):
                with self.assertRaises(SpeechProviderError):
                    client.synthesize("hello", "warm")

    def test_tts_file_failures_are_wrapped(self):
        class FakeResponse:
            content = b"audio-bytes"

            def raise_for_status(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "not-a-directory"
            output_dir.write_text("occupied")
            client = HttpSpeechClient(
                stt_endpoint="https://speech.test/stt",
                tts_endpoint="https://speech.test/tts",
                output_dir=output_dir,
            )

            with patch("jks.speech.requests.post", return_value=FakeResponse()):
                with self.assertRaises(SpeechProviderError):
                    client.synthesize("hello", "warm")

    def test_missing_stt_endpoint_fails_before_network_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "input.wav"
            audio_path.write_bytes(b"audio-bytes")
            client = HttpSpeechClient(
                stt_endpoint="",
                tts_endpoint="https://speech.test/tts",
                output_dir=Path(temp_dir),
            )

            with patch("jks.speech.requests.post") as post:
                with self.assertRaises(RuntimeError):
                    client.transcribe(audio_path)

        post.assert_not_called()

    def test_missing_tts_endpoint_fails_before_network_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = HttpSpeechClient(
                stt_endpoint="https://speech.test/stt",
                tts_endpoint="",
                output_dir=Path(temp_dir),
            )

            with patch("jks.speech.requests.post") as post:
                with self.assertRaises(RuntimeError):
                    client.synthesize("hello", "warm")

        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
