from pathlib import Path
import unittest


REQUIRED_KEYS = (
    "JKS_AGENT_MODE",
    "JKS_AGENT_HOST",
    "JKS_AGENT_USER",
    "JKS_AGENT_AUTH_METHOD",
    "JKS_AGENT_SSH_PASSWORD",
    "JKS_AGENT_COMMAND",
    "JKS_AGENT_WORKDIR",
    "JKS_AGENT_ENDPOINT",
    "JKS_AGENT_TOKEN",
    "JKS_AGENT_MODEL",
    "JKS_STT_PROVIDER",
    "JKS_STT_ENDPOINT",
    "JKS_STT_TOKEN",
    "JKS_TTS_PROVIDER",
    "JKS_TTS_ENDPOINT",
    "JKS_TTS_TOKEN",
    "JKS_TTS_VOICE",
    "JKS_FISH_API_KEY",
    "JKS_FISH_TTS_MODEL",
    "JKS_FISH_TTS_LATENCY",
    "JKS_OLED_PORT",
    "JKS_OLED_BAUD",
)


class EnvExampleTests(unittest.TestCase):
    def test_env_example_documents_required_keys_without_real_secrets(self):
        env_example = Path(".env.example")
        self.assertTrue(env_example.exists(), ".env.example should exist")
        text = env_example.read_text()

        for key in REQUIRED_KEYS:
            self.assertIn(key + "=", text)

        for forbidden in ("Bearer ", "root", "Qq", "secret-token", '="password"'):
            self.assertNotIn(forbidden, text)

        self.assertIn("replace-with-", text)

    def test_env_example_defaults_to_fish_without_active_http_speech_placeholders(self):
        lines = Path(".env.example").read_text().splitlines()
        active_lines = [line for line in lines if line and not line.startswith("#")]
        active_text = "\n".join(active_lines)

        self.assertIn('JKS_STT_PROVIDER="fish"', active_text)
        self.assertIn('JKS_TTS_PROVIDER="fish"', active_text)
        self.assertNotIn("JKS_STT_ENDPOINT=", active_text)
        self.assertNotIn("JKS_STT_TOKEN=", active_text)
        self.assertNotIn("JKS_TTS_ENDPOINT=", active_text)
        self.assertNotIn("JKS_TTS_TOKEN=", active_text)


if __name__ == "__main__":
    unittest.main()
