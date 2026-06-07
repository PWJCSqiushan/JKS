import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tools.jks_config_check import main


@contextmanager
def clean_cwd():
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            yield
        finally:
            os.chdir(old_cwd)


class ConfigCheckCliTests(unittest.TestCase):
    def test_main_prints_compact_secret_safe_json(self):
        env = {
            "JKS_AGENT_ENDPOINT": "http://127.0.0.1:8787/chat",
            "JKS_AGENT_TOKEN": "secret-token",
            "JKS_STT_ENDPOINT": "http://127.0.0.1:8788/stt",
            "JKS_TTS_ENDPOINT": "http://127.0.0.1:8788/tts",
        }
        output = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, env, clear=True):
            exit_code = main([], stdout=output)

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertNotIn("secret-token", text)
        self.assertNotIn("127.0.0.1:8787", text)
        self.assertNotIn("127.0.0.1:8788", text)
        self.assertNotIn(": ", text)
        payload = json.loads(text)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["agent"]["mode"], "http")
        self.assertTrue(payload["agent"]["endpoint_present"])
        self.assertTrue(payload["agent"]["token_present"])
        self.assertEqual(payload["speech"]["mode"], "http")
        self.assertTrue(payload["speech"]["stt_endpoint_present"])
        self.assertTrue(payload["speech"]["tts_endpoint_present"])

    def test_main_does_not_print_ssh_host_user_or_runtime_paths_by_default(self):
        env = {
            "JKS_AGENT_HOST": "gran.example.com",
            "JKS_AGENT_USER": "jks-user",
            "JKS_AGENT_AUTH_METHOD": "ssh-password",
            "JKS_AGENT_SSH_PASSWORD": "ssh-secret",
            "JKS_AGENT_COMMAND": "/private/hermes/bin/hermes",
            "JKS_AGENT_WORKDIR": "/private/hermes",
            "JKS_STT_PROVIDER": "fish",
            "JKS_TTS_PROVIDER": "fish",
            "JKS_FISH_API_KEY": "fish-secret",
            "JKS_TTS_VOICE": "fish-reference-id-secret",
            "JKS_OLED_PORT": "/dev/cu.private",
        }
        output = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, env, clear=True):
            exit_code = main([], stdout=output)

        text = output.getvalue()
        payload = json.loads(text)
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        for private_value in (
            "gran.example.com",
            "jks-user",
            "ssh-secret",
            "/private/hermes",
            "fish-secret",
            "fish-reference-id-secret",
            "/dev/cu.private",
        ):
            self.assertNotIn(private_value, text)
        self.assertEqual(payload["agent"]["mode"], "ssh")
        self.assertTrue(payload["agent"]["host_present"])
        self.assertTrue(payload["agent"]["ssh_password_present"])
        self.assertEqual(payload["speech"]["mode"], "fish")
        self.assertTrue(payload["speech"]["fish_api_key_present"])
        self.assertTrue(payload["speech"]["voice_present"])
        self.assertTrue(payload["speech"]["voice_custom"])
        self.assertNotIn("voice", payload["speech"])
        self.assertEqual(payload["oled"]["mode"], "serial")
        self.assertTrue(payload["oled"]["port_present"])

    def test_main_does_not_print_local_agent_runtime_paths_by_default(self):
        env = {
            "JKS_AGENT_MODE": "local",
            "JKS_AGENT_COMMAND": "/private/jks/.local/bin/jksgrantly",
            "JKS_AGENT_WORKDIR": "/private/jks/.local/hermes-agent",
            "JKS_STT_PROVIDER": "fish",
            "JKS_TTS_PROVIDER": "fish",
            "JKS_FISH_API_KEY": "fish-secret",
            "JKS_OLED_PORT": "/dev/cu.private",
        }
        output = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, env, clear=True):
            exit_code = main([], stdout=output)

        text = output.getvalue()
        payload = json.loads(text)
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["agent"]["mode"], "local")
        self.assertFalse(payload["agent"]["host_present"])
        self.assertNotIn("/private/jks", text)
        self.assertNotIn("fish-secret", text)

    def test_main_returns_one_when_required_agent_endpoint_is_missing(self):
        output = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, {}, clear=True):
            exit_code = main([], stdout=output)

        self.assertEqual(exit_code, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("JKS_AGENT_ENDPOINT", payload["missing"])

    def test_main_returns_one_when_agent_endpoint_has_fake_speech(self):
        output = io.StringIO()

        with clean_cwd(), patch.dict(
            os.environ,
            {"JKS_AGENT_ENDPOINT": "http://127.0.0.1:8787/chat"},
            clear=True,
        ):
            exit_code = main([], stdout=output)

        self.assertEqual(exit_code, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["ready_for_real"])
        self.assertEqual(payload["speech"]["mode"], "fake")
        self.assertIn("JKS_STT_ENDPOINT", payload["missing"])
        self.assertIn("JKS_TTS_ENDPOINT", payload["missing"])

    def test_main_returns_one_when_dotenv_contains_placeholders(self):
        output = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, {}, clear=True):
            Path(".env").write_text(
                "\n".join(
                    [
                        "JKS_AGENT_ENDPOINT=replace-with-agent-endpoint",
                        "JKS_STT_ENDPOINT=replace-with-stt-endpoint",
                        "JKS_TTS_ENDPOINT=replace-with-tts-endpoint",
                    ]
                )
            )
            exit_code = main([], stdout=output)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ready_for_real"])
        self.assertIn("placeholder values must be replaced before real integration", payload["warnings"])

    def test_main_prints_json_when_config_loading_fails(self):
        output = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, {"JKS_OLED_BAUD": "fast"}, clear=True):
            exit_code = main([], stdout=output)

        self.assertEqual(exit_code, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["error"], "config")
        self.assertIn("JKS_OLED_BAUD", payload["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
