import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from tools.jks_agent_probe import main
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


class AgentProbeTests(unittest.TestCase):
    def test_missing_agent_endpoint_returns_error_without_network_probe(self):
        stdout = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, {}, clear=True):
            with patch("jks.agent.requests.post") as post:
                exit_code = main([], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["checks"], {})
        self.assertEqual(payload["errors"], [{"error": "agent", "message": "JKS_AGENT_ENDPOINT is required"}])
        post.assert_not_called()

    def test_placeholder_agent_endpoint_returns_error_without_network_probe(self):
        stdout = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, {"JKS_AGENT_ENDPOINT": "replace-with-agent-url"}, clear=True):
            with patch("jks.agent.requests.post") as post:
                exit_code = main([], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"], [{"error": "agent", "message": "JKS_AGENT_ENDPOINT is required"}])
        post.assert_not_called()

    def test_malformed_agent_endpoint_returns_error_without_network_probe(self):
        stdout = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, {"JKS_AGENT_ENDPOINT": "not-a-url"}, clear=True):
            with patch("jks.agent.requests.post") as post:
                exit_code = main([], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            payload["errors"],
            [{"error": "agent", "message": "JKS_AGENT_ENDPOINT must be an http(s) URL"}],
        )
        post.assert_not_called()

    def test_agent_probe_calls_configured_agent_without_requiring_speech(self):
        server = start_fake_services()
        stdout = io.StringIO()
        try:
            env = {
                "JKS_AGENT_ENDPOINT": server.base_url + "/v1/chat/completions?token=secret",
                "JKS_AGENT_TOKEN": "secret-token",
                "JKS_AGENT_MODEL": "gran-agent",
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
        self.assertNotIn("token=secret", text)
        self.assertNotIn(": ", text)
        self.assertEqual(payload["agent"]["model"], "gran-agent")
        self.assertEqual(payload["checks"]["agent"]["mode"], "http")
        self.assertGreater(payload["checks"]["agent"]["text_length"], 0)
        self.assertEqual(payload["checks"]["agent"]["emotion"], "happy")
        self.assertTrue(payload["checks"]["agent"]["display_present"])
        self.assertEqual(payload["checks"]["agent"]["display_text_length"], len("DONE"))
        self.assertEqual(payload["checks"]["agent"]["duration_ms"], 1200)
        self.assertEqual(payload["checks"]["agent"]["intensity"], "normal")
        self.assertEqual([event["kind"] for event in server.events], ["chat"])
        self.assertEqual(server.events[0]["format"], "openai")
        self.assertEqual(server.events[0]["model"], "gran-agent")
        self.assertEqual(server.events[0]["session_id"], "contract-probe")
        self.assertIs(server.events[0]["auth_present"], True)

    def test_agent_probe_reports_provider_failure_without_exposing_secrets(self):
        stdout = io.StringIO()
        env = {
            "JKS_AGENT_ENDPOINT": "http://127.0.0.1:9/v1/chat/completions?token=secret",
            "JKS_AGENT_TOKEN": "secret-token",
        }

        with clean_cwd(), patch.dict(os.environ, env, clear=True):
            with patch("jks.agent.requests.post", side_effect=OSError("offline")):
                exit_code = main([], stdout=stdout)

        text = stdout.getvalue()
        payload = json.loads(text)
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["checks"], {})
        self.assertEqual(payload["errors"][0]["error"], "agent")
        self.assertNotIn("secret-token", text)
        self.assertNotIn("token=secret", text)

    def test_agent_probe_reports_config_exception_without_network_call(self):
        stdout = io.StringIO()

        with clean_cwd(), patch.dict(os.environ, {"JKS_OLED_BAUD": "fast"}, clear=True):
            with patch("jks.agent.requests.post") as post:
                exit_code = main([], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["agent"], {})
        self.assertEqual(payload["checks"], {})
        self.assertEqual(payload["errors"][0]["error"], "config")
        post.assert_not_called()

    def test_agent_probe_still_supports_legacy_chat_endpoint(self):
        server = start_fake_services()
        stdout = io.StringIO()
        try:
            env = {"JKS_AGENT_ENDPOINT": server.base_url + "/chat"}

            with clean_cwd(), patch.dict(os.environ, env, clear=True):
                exit_code = main([], stdout=stdout)
        finally:
            server.stop()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual([event["kind"] for event in server.events], ["chat"])
        self.assertEqual(server.events[0]["format"], "legacy")
        self.assertEqual(server.events[0]["conversation_id"], "contract-probe")

    def test_agent_probe_supports_ssh_hermes_without_requiring_http_endpoint(self):
        stdout = io.StringIO()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"text": "ssh ok", "emotion": "happy", "display_text": "OK"}),
            stderr="",
        )
        env = {
            "JKS_AGENT_ENDPOINT": "replace-with-agent-endpoint",
            "JKS_AGENT_TOKEN": "replace-with-agent-token",
            "JKS_AGENT_HOST": "gran.example.com",
            "JKS_AGENT_USER": "jks",
            "JKS_AGENT_AUTH_METHOD": "ssh-password",
            "JKS_AGENT_SSH_PASSWORD": "ssh-secret",
        }

        with clean_cwd(), patch.dict(os.environ, env, clear=True):
            with patch("jks.agent.subprocess.run", return_value=completed) as run:
                exit_code = main([], stdout=stdout)

        text = stdout.getvalue()
        payload = json.loads(text)
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["checks"]["agent"]["mode"], "ssh")
        self.assertEqual(payload["checks"]["agent"]["emotion"], "happy")
        self.assertEqual(payload["checks"]["agent"]["display_text_length"], 2)
        self.assertNotIn("ssh-secret", text)
        self.assertNotIn("gran.example.com", text)
        self.assertNotIn("jks", text)
        self.assertNotIn("replace-with-agent-token", text)
        self.assertEqual(payload["agent"]["mode"], "ssh")
        self.assertTrue(payload["agent"]["host_present"])
        self.assertTrue(payload["agent"]["ssh_password_present"])
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["sshpass", "-e", "ssh"])
        self.assertNotIn("ssh-secret", " ".join(command))
        self.assertEqual(run.call_args.kwargs["timeout"], 60.0)

    def test_agent_probe_supports_local_hermes_without_remote_or_http_endpoint(self):
        stdout = io.StringIO()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"text": "local ok", "emotion": "happy", "display_text": "OK"}),
            stderr="",
        )
        env = {
            "JKS_AGENT_MODE": "local",
            "JKS_AGENT_ENDPOINT": "replace-with-agent-endpoint",
            "JKS_AGENT_TOKEN": "replace-with-agent-token",
            "JKS_AGENT_HOST": "",
            "JKS_AGENT_COMMAND": "/tmp/jksgrantly",
            "JKS_AGENT_WORKDIR": "/tmp/hermes-agent",
        }

        with clean_cwd(), patch.dict(os.environ, env, clear=True):
            with patch("jks.agent.subprocess.run", return_value=completed) as run:
                exit_code = main([], stdout=stdout)

        text = stdout.getvalue()
        payload = json.loads(text)
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["agent"]["mode"], "local")
        self.assertFalse(payload["agent"]["host_present"])
        self.assertEqual(payload["checks"]["agent"]["mode"], "local")
        self.assertEqual(payload["checks"]["agent"]["emotion"], "happy")
        self.assertNotIn("/tmp/jksgrantly", text)
        self.assertEqual(run.call_args.args[0][0], "/tmp/jksgrantly")
        self.assertEqual(run.call_args.kwargs["cwd"], "/tmp/hermes-agent")


if __name__ == "__main__":
    unittest.main()
