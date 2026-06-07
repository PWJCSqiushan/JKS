import io
import json
import unittest
from unittest import mock

from tools.jks_smoke import main, run_smoke


class SmokeTests(unittest.TestCase):
    def test_run_smoke_returns_success_summary(self):
        summary = run_smoke()

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["user_text"], "hello agent")
        self.assertTrue(summary["agent_text"].startswith("Fake reply"))
        self.assertIn("listening", summary["display_emotions"])
        self.assertIn("speaking", summary["display_emotions"])
        self.assertIn("DONE", summary["display_texts"])
        self.assertEqual(summary["server_events"], ["stt", "chat", "tts"])
        self.assertEqual(summary["server_chat_formats"], ["openai"])
        self.assertEqual(summary["display_emotions"][-1], "happy")
        self.assertEqual(summary["display_texts"][-1], "DONE")
        self.assertEqual(summary["played_count"], 1)
        self.assertEqual(summary["recordings"], 1)

    def test_main_prints_compact_json_summary(self):
        output = io.StringIO()

        exit_code = main([], stdout=output)

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["played_count"], 1)
        self.assertEqual(payload["server_chat_formats"], ["openai"])
        self.assertNotIn('": ', output.getvalue())

    def test_main_prints_json_failure_summary(self):
        output = io.StringIO()

        with mock.patch("tools.jks_smoke.run_smoke", side_effect=RuntimeError("boom")):
            exit_code = main([], stdout=output)

        self.assertEqual(exit_code, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["error"], "smoke")
        self.assertIn("boom", payload["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
