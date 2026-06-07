import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from tools.jks_contract_probe import main
from tools.jks_fake_services import start_fake_services


@contextmanager
def clean_cwd():
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            yield
        finally:
            os.chdir(old_cwd)


class ContractProbeTests(unittest.TestCase):
    def test_missing_config_returns_redacted_preflight_failure_without_probing(self):
        stdout = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, {}, clear=True):
            exit_code = main([], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["checks"], {})
        self.assertIn("JKS_AGENT_ENDPOINT", payload["preflight"]["missing"])

    def test_probe_uses_configured_fake_services_and_prints_compact_json(self):
        server = start_fake_services()
        stdout = io.StringIO()
        try:
            env = {
                "JKS_AGENT_ENDPOINT": server.base_url + "/v1/chat/completions?token=secret",
                "JKS_AGENT_TOKEN": "secret-token",
                "JKS_AGENT_MODEL": "gran-agent",
                "JKS_STT_ENDPOINT": server.base_url + "/stt?api_key=secret",
                "JKS_TTS_ENDPOINT": server.base_url + "/tts?api_key=secret",
            }

            with clean_cwd(), patch.dict(os.environ, env, clear=True):
                exit_code = main([], stdout=stdout)
        finally:
            server.stop()

        text = stdout.getvalue()
        payload = json.loads(text)
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertNotIn("secret-token", text)
        self.assertNotIn("api_key=secret", text)
        self.assertNotIn(": ", text)
        self.assertEqual(payload["checks"]["agent"]["mode"], "http")
        self.assertGreater(payload["checks"]["agent"]["text_length"], 0)
        self.assertEqual(payload["checks"]["agent"]["emotion"], "happy")
        self.assertTrue(payload["checks"]["agent"]["display_present"])
        self.assertEqual(payload["checks"]["agent"]["display_text_length"], len("DONE"))
        self.assertEqual(payload["checks"]["agent"]["duration_ms"], 1200)
        self.assertEqual(payload["checks"]["agent"]["intensity"], "normal")
        self.assertEqual(payload["checks"]["speech"]["stt_text_length"], len("hello agent"))
        self.assertGreater(payload["checks"]["speech"]["tts_bytes"], 0)
        self.assertEqual([event["kind"] for event in server.events], ["chat", "stt", "tts"])
        self.assertEqual(server.events[0]["format"], "openai")
        self.assertEqual(server.events[0]["model"], "gran-agent")
        self.assertIs(server.events[0]["auth_present"], True)


if __name__ == "__main__":
    unittest.main()
