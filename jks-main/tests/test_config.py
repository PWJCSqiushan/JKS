import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jks.config import AppConfig, load_config


class ConfigTests(unittest.TestCase):
    def test_loads_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = load_config(env_file=None)

        self.assertIsInstance(config, AppConfig)
        self.assertEqual(getattr(config, "agent_host", None), "")
        self.assertEqual(getattr(config, "agent_mode", ""), "")
        self.assertEqual(getattr(config, "agent_user", None), "")
        self.assertEqual(getattr(config, "agent_auth_method", None), "")
        self.assertEqual(config.agent_ssh_password, "")
        self.assertEqual(config.agent_command, "/usr/local/lib/hermes-agent/venv/bin/hermes")
        self.assertEqual(config.agent_workdir, "/usr/local/lib/hermes-agent")
        self.assertEqual(config.agent_endpoint, "")
        self.assertEqual(config.agent_token, "")
        self.assertEqual(config.agent_model, "gran-agent")
        self.assertEqual(getattr(config, "stt_provider", None), "")
        self.assertEqual(config.stt_endpoint, "")
        self.assertEqual(config.stt_token, "")
        self.assertEqual(getattr(config, "tts_provider", None), "")
        self.assertEqual(config.tts_endpoint, "")
        self.assertEqual(config.tts_token, "")
        self.assertEqual(config.fish_api_key, "")
        self.assertEqual(config.fish_tts_model, "s2-pro")
        self.assertEqual(config.fish_tts_latency, "low")
        self.assertEqual(config.tts_voice, "default")
        self.assertEqual(config.oled_port, "/dev/cu.usbmodem5B900048301")
        self.assertEqual(config.oled_baud, 115200)

    def test_loads_remote_speech_and_oled_settings(self):
        env = {
            "JKS_AGENT_HOST": "gran.example.com",
            "JKS_AGENT_MODE": "local",
            "JKS_AGENT_USER": "jks",
            "JKS_AGENT_AUTH_METHOD": "ssh-password",
            "JKS_AGENT_SSH_PASSWORD": "ssh-secret",
            "JKS_AGENT_COMMAND": "/opt/hermes/bin/hermes",
            "JKS_AGENT_WORKDIR": "/opt/hermes",
            "JKS_AGENT_ENDPOINT": "http://127.0.0.1:8787/chat",
            "JKS_AGENT_TOKEN": "secret-token",
            "JKS_AGENT_MODEL": "gran-agent",
            "JKS_STT_PROVIDER": "whisper",
            "JKS_STT_ENDPOINT": "http://127.0.0.1:8788/stt",
            "JKS_STT_TOKEN": "stt-secret",
            "JKS_TTS_PROVIDER": "piper",
            "JKS_TTS_ENDPOINT": "http://127.0.0.1:8788/tts",
            "JKS_TTS_TOKEN": "tts-secret",
            "JKS_FISH_API_KEY": "fish-secret",
            "JKS_FISH_TTS_MODEL": "s1",
            "JKS_FISH_TTS_LATENCY": "balanced",
            "JKS_TTS_VOICE": "warm",
            "JKS_OLED_PORT": "/dev/cu.test",
            "JKS_OLED_BAUD": "57600",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config(env_file=None)

        self.assertEqual(getattr(config, "agent_host", None), "gran.example.com")
        self.assertEqual(config.agent_mode, "local")
        self.assertEqual(getattr(config, "agent_user", None), "jks")
        self.assertEqual(getattr(config, "agent_auth_method", None), "ssh-password")
        self.assertEqual(config.agent_ssh_password, "ssh-secret")
        self.assertEqual(config.agent_command, "/opt/hermes/bin/hermes")
        self.assertEqual(config.agent_workdir, "/opt/hermes")
        self.assertEqual(config.agent_endpoint, env["JKS_AGENT_ENDPOINT"])
        self.assertEqual(config.agent_token, "secret-token")
        self.assertEqual(config.agent_model, "gran-agent")
        self.assertEqual(getattr(config, "stt_provider", None), "whisper")
        self.assertEqual(config.stt_endpoint, env["JKS_STT_ENDPOINT"])
        self.assertEqual(config.stt_token, "stt-secret")
        self.assertEqual(getattr(config, "tts_provider", None), "piper")
        self.assertEqual(config.tts_endpoint, env["JKS_TTS_ENDPOINT"])
        self.assertEqual(config.tts_token, "tts-secret")
        self.assertEqual(config.fish_api_key, "fish-secret")
        self.assertEqual(config.fish_tts_model, "s1")
        self.assertEqual(config.fish_tts_latency, "balanced")
        self.assertEqual(config.tts_voice, "warm")
        self.assertEqual(config.oled_port, "/dev/cu.test")
        self.assertEqual(config.oled_baud, 57600)

    def test_loads_settings_from_dotenv_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "# local JKS config",
                        'JKS_AGENT_ENDPOINT="http://127.0.0.1:8787/chat"',
                        "export JKS_STT_ENDPOINT='http://127.0.0.1:8788/stt'",
                        "JKS_TTS_ENDPOINT=http://127.0.0.1:8788/tts",
                        "JKS_TTS_VOICE=warm",
                        "JKS_OLED_BAUD=57600",
                    ]
                )
            )

            with patch.dict(os.environ, {}, clear=True):
                config = load_config(env_file=env_file)

        self.assertEqual(config.agent_endpoint, "http://127.0.0.1:8787/chat")
        self.assertEqual(config.stt_endpoint, "http://127.0.0.1:8788/stt")
        self.assertEqual(config.tts_endpoint, "http://127.0.0.1:8788/tts")
        self.assertEqual(config.tts_voice, "warm")
        self.assertEqual(config.oled_baud, 57600)

    def test_environment_overrides_dotenv_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "JKS_AGENT_ENDPOINT=http://file-agent/chat",
                        "JKS_TTS_VOICE=file-voice",
                    ]
                )
            )

            with patch.dict(
                os.environ,
                {
                    "JKS_AGENT_ENDPOINT": "http://env-agent/chat",
                    "JKS_TTS_VOICE": "env-voice",
                },
                clear=True,
            ):
                config = load_config(env_file=env_file)

        self.assertEqual(config.agent_endpoint, "http://env-agent/chat")
        self.assertEqual(config.tts_voice, "env-voice")

    def test_fish_api_key_falls_back_to_upstream_env_name(self):
        with patch.dict(os.environ, {"FISH_API_KEY": "fish-secret"}, clear=True):
            config = load_config(env_file=None)

        self.assertEqual(config.fish_api_key, "fish-secret")

    def test_fish_api_key_falls_back_to_fish_audio_env_name(self):
        with patch.dict(os.environ, {"FISH_AUDIO_API_KEY": "fish-audio-secret"}, clear=True):
            config = load_config(env_file=None)

        self.assertEqual(config.fish_api_key, "fish-audio-secret")

    def test_invalid_baud_fails_cleanly(self):
        with patch.dict(os.environ, {"JKS_OLED_BAUD": "fast"}, clear=True):
            with self.assertRaises(ValueError):
                load_config(env_file=None)


if __name__ == "__main__":
    unittest.main()
