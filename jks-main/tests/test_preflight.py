import json
import unittest

from jks.config import AppConfig
from jks.preflight import analyze_config, redact_secret, redact_url


def config(**overrides):
    data = {
        "agent_host": "",
        "agent_mode": "",
        "agent_user": "",
        "agent_auth_method": "",
        "agent_ssh_password": "",
        "agent_command": "/usr/local/lib/hermes-agent/venv/bin/hermes",
        "agent_workdir": "/usr/local/lib/hermes-agent",
        "agent_endpoint": "",
        "agent_token": "",
        "agent_model": "gran-agent",
        "stt_provider": "",
        "stt_endpoint": "",
        "stt_token": "",
        "tts_provider": "",
        "tts_endpoint": "",
        "tts_token": "",
        "tts_voice": "default",
        "fish_api_key": "",
        "fish_tts_model": "s2-pro",
        "fish_tts_latency": "low",
        "oled_port": "/dev/cu.usbmodem5B900048301",
        "oled_baud": 115200,
    }
    data.update(overrides)
    return AppConfig(**data)


class PreflightTests(unittest.TestCase):
    def test_missing_agent_is_not_ready_but_fake_speech_is_allowed(self):
        summary = analyze_config(config())

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["agent"]["mode"], "missing")
        self.assertEqual(summary["speech"]["mode"], "fake")
        self.assertEqual(summary["oled"]["mode"], "serial")
        self.assertIn("JKS_AGENT_ENDPOINT", summary["missing"])

    def test_http_agent_and_http_speech_are_ready(self):
        summary = analyze_config(
            config(
                agent_endpoint="http://127.0.0.1:8787/chat",
                agent_token="secret-token",
                agent_model="gran-agent",
                stt_provider="http",
                stt_endpoint="http://127.0.0.1:8788/stt",
                stt_token="stt-secret",
                tts_provider="http",
                tts_endpoint="http://127.0.0.1:8788/tts",
                tts_token="tts-secret",
                tts_voice="warm",
            )
        )

        self.assertTrue(summary["ok"])
        self.assertTrue(summary["ready_for_real"])
        self.assertEqual(summary["agent"]["mode"], "http")
        self.assertEqual(summary["agent"]["token"], "<redacted:12>")
        self.assertEqual(summary["agent"]["model"], "gran-agent")
        self.assertEqual(summary["speech"]["mode"], "http")
        self.assertEqual(summary["speech"]["stt_token"], "<redacted:10>")
        self.assertEqual(summary["speech"]["tts_token"], "<redacted:10>")
        self.assertEqual(summary["speech"]["voice"], "warm")

    def test_ssh_agent_and_fish_speech_are_ready_without_http_endpoint(self):
        summary = analyze_config(
            config(
                agent_host="gran.example.com",
                agent_user="jks",
                agent_auth_method="ssh-password",
                agent_ssh_password="ssh-secret",
                agent_endpoint="replace-with-agent-endpoint",
                agent_token="replace-with-agent-token",
                stt_provider="fish",
                tts_provider="fish",
                fish_api_key="fish-secret",
            )
        )

        self.assertTrue(summary["ok"])
        self.assertTrue(summary["ready_for_real"])
        self.assertEqual(summary["agent"]["mode"], "ssh")
        self.assertEqual(summary["agent"]["host"], "gran.example.com")
        self.assertEqual(summary["agent"]["user"], "jks")
        self.assertEqual(summary["agent"]["ssh_password"], "<redacted:10>")
        self.assertNotIn("JKS_AGENT_ENDPOINT", summary["missing"])
        self.assertNotIn("JKS_AGENT_TOKEN", summary["missing"])

    def test_local_agent_and_fish_speech_are_ready_without_remote_or_http_endpoint(self):
        summary = analyze_config(
            config(
                agent_mode="local",
                agent_host="",
                agent_endpoint="replace-with-agent-endpoint",
                agent_token="replace-with-agent-token",
                agent_command="/Users/cornna/project/jks/.local/bin/jksgrantly",
                agent_workdir="/Users/cornna/project/jks/.local/hermes-agent",
                stt_provider="fish",
                tts_provider="fish",
                fish_api_key="fish-secret",
            )
        )

        self.assertTrue(summary["ok"])
        self.assertTrue(summary["ready_for_real"])
        self.assertEqual(summary["agent"]["mode"], "local")
        self.assertEqual(summary["agent"]["host"], "")
        self.assertNotIn("JKS_AGENT_ENDPOINT", summary["missing"])
        self.assertNotIn("JKS_AGENT_HOST", summary["missing"])

    def test_fish_speech_provider_is_ready_with_api_key_and_default_endpoints(self):
        summary = analyze_config(
            config(
                agent_endpoint="http://agent.local/chat",
                stt_provider="fish",
                tts_provider="fish",
                fish_api_key="fish-secret",
                tts_voice="fish-voice-id",
            )
        )

        self.assertTrue(summary["ok"])
        self.assertTrue(summary["ready_for_real"])
        self.assertEqual(summary["speech"]["mode"], "fish")
        self.assertEqual(summary["speech"]["fish_api_key"], "<redacted:11>")
        self.assertEqual(summary["speech"]["fish_tts_model"], "s2-pro")
        self.assertEqual(summary["speech"]["fish_tts_latency"], "low")

    def test_fish_speech_ignores_unused_http_speech_placeholders(self):
        summary = analyze_config(
            config(
                agent_endpoint="http://agent.local/chat",
                stt_provider="fish",
                stt_endpoint="replace-with-stt-endpoint",
                stt_token="replace-with-stt-token",
                tts_provider="fish",
                tts_endpoint="replace-with-tts-endpoint",
                tts_token="replace-with-tts-token",
                fish_api_key="fish-secret",
            )
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["speech"]["mode"], "fish")
        self.assertNotIn("JKS_STT_ENDPOINT", summary["missing"])
        self.assertNotIn("JKS_TTS_ENDPOINT", summary["missing"])
        self.assertNotIn("JKS_STT_TOKEN", summary["missing"])
        self.assertNotIn("JKS_TTS_TOKEN", summary["missing"])

    def test_fish_speech_provider_requires_api_key(self):
        summary = analyze_config(
            config(
                agent_endpoint="http://agent.local/chat",
                stt_provider="fish",
                tts_provider="fish",
                tts_voice="fish-voice-id",
            )
        )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["speech"]["mode"], "partial")
        self.assertIn("JKS_FISH_API_KEY", summary["missing"])

    def test_agent_endpoint_with_fake_speech_is_not_ready_for_real_services(self):
        summary = analyze_config(config(agent_endpoint="http://agent.local/chat"))

        self.assertFalse(summary["ok"])
        self.assertFalse(summary["ready_for_real"])
        self.assertEqual(summary["agent"]["mode"], "http")
        self.assertEqual(summary["speech"]["mode"], "fake")
        self.assertIn("JKS_STT_ENDPOINT", summary["missing"])
        self.assertIn("JKS_TTS_ENDPOINT", summary["missing"])
        self.assertIn(
            "Real agent integration requires Fish Audio or custom STT/TTS endpoints",
            summary["warnings"],
        )

    def test_http_speech_provider_without_endpoints_reports_partial(self):
        summary = analyze_config(
            config(
                agent_endpoint="http://agent.local/chat",
                stt_provider="http",
                tts_provider="http",
            )
        )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["speech"]["mode"], "partial")
        self.assertIn("JKS_STT_ENDPOINT", summary["missing"])
        self.assertIn("JKS_TTS_ENDPOINT", summary["missing"])

    def test_placeholder_endpoints_are_not_ready(self):
        summary = analyze_config(
            config(
                agent_endpoint="replace-with-agent-endpoint",
                stt_endpoint="replace-with-stt-endpoint",
                tts_endpoint="replace-with-tts-endpoint",
            )
        )

        self.assertFalse(summary["ok"])
        self.assertFalse(summary["ready_for_real"])
        self.assertEqual(summary["agent"]["mode"], "missing")
        self.assertEqual(summary["speech"]["mode"], "partial")
        self.assertIn("JKS_AGENT_ENDPOINT", summary["missing"])
        self.assertIn("JKS_STT_ENDPOINT", summary["missing"])
        self.assertIn("JKS_TTS_ENDPOINT", summary["missing"])
        self.assertIn("placeholder values must be replaced before real integration", summary["warnings"])

    def test_malformed_urls_are_not_ready(self):
        summary = analyze_config(
            config(
                agent_endpoint="not-a-url",
                stt_endpoint="ftp://speech.local/stt",
                tts_endpoint="http://",
            )
        )

        self.assertFalse(summary["ok"])
        self.assertFalse(summary["ready_for_real"])
        self.assertEqual(summary["agent"]["mode"], "missing")
        self.assertEqual(summary["speech"]["mode"], "partial")
        self.assertIn("JKS_AGENT_ENDPOINT", summary["missing"])
        self.assertIn("JKS_STT_ENDPOINT", summary["missing"])
        self.assertIn("JKS_TTS_ENDPOINT", summary["missing"])
        self.assertIn("endpoint values must be valid http(s) URLs", summary["warnings"])

    def test_placeholder_runtime_fields_are_not_ready(self):
        summary = analyze_config(
            config(
                agent_endpoint="http://agent.local/chat",
                agent_token="replace-with-agent-token",
                stt_endpoint="http://speech.local/stt",
                stt_token="replace-with-stt-token",
                tts_endpoint="http://speech.local/tts",
                tts_token="replace-with-tts-token",
                fish_api_key="replace-with-fish-api-key",
                fish_tts_model="replace-with-fish-tts-model",
                tts_voice="replace-with-tts-voice",
                oled_port="replace-with-oled-port",
            )
        )

        self.assertFalse(summary["ok"])
        self.assertFalse(summary["ready_for_real"])
        self.assertEqual(summary["agent"]["mode"], "http")
        self.assertEqual(summary["speech"]["mode"], "http")
        self.assertEqual(summary["oled"]["mode"], "disabled")
        self.assertIn("JKS_AGENT_TOKEN", summary["missing"])
        self.assertIn("JKS_STT_TOKEN", summary["missing"])
        self.assertIn("JKS_TTS_TOKEN", summary["missing"])
        self.assertIn("JKS_TTS_VOICE", summary["missing"])
        self.assertIn("JKS_OLED_PORT", summary["missing"])
        self.assertIn("placeholder values must be replaced before real integration", summary["warnings"])

    def test_fish_placeholder_runtime_fields_are_not_ready(self):
        summary = analyze_config(
            config(
                agent_endpoint="http://agent.local/chat",
                stt_provider="fish",
                tts_provider="fish",
                fish_api_key="replace-with-fish-api-key",
                fish_tts_model="replace-with-fish-tts-model",
            )
        )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["speech"]["mode"], "partial")
        self.assertIn("JKS_FISH_API_KEY", summary["missing"])
        self.assertIn("JKS_FISH_TTS_MODEL", summary["missing"])
        self.assertIn("placeholder values must be replaced before real integration", summary["warnings"])

    def test_partial_speech_config_reports_missing_pair(self):
        cases = [
            ({"stt_endpoint": "http://stt.local"}, "JKS_TTS_ENDPOINT"),
            ({"tts_endpoint": "http://tts.local"}, "JKS_STT_ENDPOINT"),
        ]

        for overrides, missing_name in cases:
            with self.subTest(missing_name=missing_name):
                summary = analyze_config(
                    config(agent_endpoint="http://agent.local/chat", **overrides)
                )

                self.assertFalse(summary["ok"])
                self.assertEqual(summary["speech"]["mode"], "partial")
                self.assertIn(missing_name, summary["missing"])
                self.assertIn(
                    "JKS_STT_ENDPOINT and JKS_TTS_ENDPOINT must be configured together",
                    summary["warnings"],
                )

    def test_analyze_config_returns_json_safe_dict(self):
        summary = analyze_config(config(agent_endpoint="http://agent.local/chat"))

        self.assertIsInstance(summary, dict)
        json.dumps(summary)

    def test_redact_secret_never_returns_secret_value(self):
        self.assertEqual(redact_secret(""), "")
        self.assertEqual(redact_secret("abc"), "<redacted:3>")
        self.assertEqual(redact_secret("very-secret-token"), "<redacted:17>")

    def test_redact_url_removes_userinfo_and_query_values(self):
        self.assertEqual(redact_url(""), "")
        self.assertEqual(
            redact_url("https://user:pass@example.com/chat?api_key=secret&mode=test"),
            "https://example.com/chat?api_key=<redacted>&mode=<redacted>",
        )
        self.assertEqual(redact_url("http://127.0.0.1:8787/chat"), "http://127.0.0.1:8787/chat")


if __name__ == "__main__":
    unittest.main()
