import unittest

from jks.display import ALLOWED_EMOTIONS, DisplayIntent
from jks.expression import DisplayCommand, ExpressionEngine, ExpressionFrame, TurnState


class ExpressionTests(unittest.TestCase):
    def test_turn_state_is_string_enum_with_required_states(self):
        self.assertEqual(TurnState.IDLE.value, "idle")
        self.assertEqual(TurnState.LISTENING.value, "listening")
        self.assertEqual(TurnState.TRANSCRIBING.value, "transcribing")
        self.assertEqual(TurnState.THINKING.value, "thinking")
        self.assertEqual(TurnState.SPEAKING.value, "speaking")
        self.assertEqual(TurnState.ERROR.value, "error")
        self.assertIsInstance(TurnState.LISTENING.value, str)

    def test_state_maps_to_display_intent(self):
        engine = ExpressionEngine()

        listening = engine.intent_for_state(TurnState.LISTENING)
        thinking = engine.intent_for_state(TurnState.THINKING)
        speaking = engine.intent_for_state(TurnState.SPEAKING)

        self.assertIsInstance(listening, DisplayIntent)
        self.assertEqual(listening.emotion, "listening")
        self.assertEqual(thinking.text, "WAIT")
        self.assertEqual(speaking.text, "TALK")

    def test_state_display_intents_include_animation_hints(self):
        engine = ExpressionEngine()

        self.assertEqual(engine.intent_for_state(TurnState.IDLE).intensity, "soft")
        self.assertEqual(engine.intent_for_state(TurnState.LISTENING).intensity, "high")
        self.assertEqual(engine.intent_for_state(TurnState.SPEAKING).duration_ms, 900)
        self.assertEqual(engine.intent_for_state(TurnState.ERROR).intensity, "high")

    def test_all_turn_states_map_to_allowed_display_emotions(self):
        engine = ExpressionEngine()

        for state in TurnState:
            with self.subTest(state=state):
                intent = engine.intent_for_state(state)
                self.assertIn(intent.emotion, ALLOWED_EMOTIONS)
                self.assertLessEqual(len(intent.text), 14)

    def test_agent_payload_is_validated_for_oled(self):
        engine = ExpressionEngine()

        intent = engine.intent_from_agent(
            {
                "emotion": "run_shell",
                "display_text": "A\nB\tCafé TOO LONGER",
                "duration_ms": 99999,
                "intensity": "wild",
            }
        )

        self.assertEqual(intent.emotion, "neutral")
        self.assertEqual(intent.text, "ABCaf TOO LONG")
        self.assertEqual(intent.duration_ms, 5000)
        self.assertEqual(intent.intensity, "normal")

    def test_agent_payload_preserves_allowed_values_and_duration_floor(self):
        engine = ExpressionEngine()

        intent = engine.intent_from_agent(
            {
                "emotion": "happy",
                "display_text": "YAY",
                "duration_ms": 12,
                "intensity": "high",
            }
        )

        self.assertEqual(intent.emotion, "happy")
        self.assertEqual(intent.text, "YAY")
        self.assertEqual(intent.duration_ms, 200)
        self.assertEqual(intent.intensity, "high")

    def test_agent_payload_none_display_text_uses_emotion_label(self):
        engine = ExpressionEngine()

        intent = engine.intent_from_agent({"emotion": "happy", "display_text": None})

        self.assertEqual(intent.emotion, "happy")
        self.assertEqual(intent.text, "HAPPY")
        self.assertEqual(intent.intensity, "high")

    def test_missing_agent_payload_falls_back_to_neutral(self):
        engine = ExpressionEngine()

        intent = engine.intent_from_agent(None)

        self.assertEqual(intent.emotion, "neutral")
        self.assertEqual(intent.text, "NEUTRAL")
        self.assertEqual(intent.intensity, "soft")

    def test_agent_display_sequence_is_clamped_and_limited(self):
        engine = ExpressionEngine()

        intents = engine.intents_from_agent(
            {
                "display_sequence": [
                    {
                        "emotion": "thinking",
                        "display_text": "PLAN-THIS-IS-TOO-LONG",
                        "duration_ms": 100,
                        "intensity": "soft",
                    },
                    {
                        "emotion": "made-up",
                        "display_text": "BAD",
                        "duration_ms": 9000,
                        "intensity": "wild",
                    },
                    "skip me",
                    {"emotion": "happy", "text": "DONE", "duration_ms": 900, "intensity": "high"},
                    {"emotion": "sad", "text": "EXTRA"},
                    {"emotion": "angry", "text": "OVER-LIMIT"},
                ]
            }
        )

        self.assertEqual(
            intents,
            [
                DisplayIntent(
                    emotion="thinking",
                    text="PLAN-THIS-IS-T",
                    duration_ms=200,
                    intensity="soft",
                ),
                DisplayIntent(
                    emotion="neutral",
                    text="BAD",
                    duration_ms=5000,
                    intensity="normal",
                ),
                DisplayIntent(emotion="happy", text="DONE", duration_ms=900, intensity="high"),
                DisplayIntent(emotion="sad", text="EXTRA", duration_ms=1200, intensity="normal"),
            ],
        )

    def test_agent_display_commands_drop_unsafe_commands_and_map_text(self):
        engine = ExpressionEngine()

        actions = engine.display_actions_from_agent(
            {
                "display_commands": [
                    {"cmd": "probe"},
                    {"cmd": "shell", "text": "BAD"},
                    {"cmd": "text", "text": "HELLO WORLD"},
                    {"cmd": "clear"},
                    {
                        "cmd": "emotion",
                        "name": "surprised",
                        "text": "WOW",
                        "duration_ms": 700,
                        "intensity": "high",
                    },
                ]
            }
        )

        self.assertEqual(
            actions,
            [
                DisplayCommand(
                    "show",
                    DisplayIntent("neutral", "HELLO WORLD", duration_ms=500, intensity="soft"),
                ),
                DisplayCommand("clear"),
                DisplayCommand(
                    "show",
                    DisplayIntent("surprised", "WOW", duration_ms=700, intensity="high"),
                ),
            ],
        )

    def test_agent_display_commands_infer_missing_cmd_and_numeric_intensity(self):
        engine = ExpressionEngine()

        actions = engine.display_actions_from_agent(
            {
                "display_commands": [
                    {"text": "HI"},
                    {"emotion": "happy", "text": "DONE", "intensity": 0.8},
                    {"emotion": "sleepy", "text": "LOW", "intensity": 0.2},
                ]
            }
        )

        self.assertEqual(
            actions,
            [
                DisplayCommand(
                    "show",
                    DisplayIntent("neutral", "HI", duration_ms=500, intensity="soft"),
                ),
                DisplayCommand(
                    "show",
                    DisplayIntent("happy", "DONE", duration_ms=1200, intensity="high"),
                ),
                DisplayCommand(
                    "show",
                    DisplayIntent("sleepy", "LOW", duration_ms=1800, intensity="soft"),
                ),
            ],
        )

    def test_agent_display_commands_cap_total_duration(self):
        engine = ExpressionEngine()

        intents = engine.intents_from_agent(
            {
                "display_commands": [
                    {"cmd": "emotion", "emotion": "happy", "duration_ms": 5000},
                    {"cmd": "emotion", "emotion": "thinking", "duration_ms": 5000},
                    {"cmd": "emotion", "emotion": "sad", "duration_ms": 5000},
                ]
            }
        )

        self.assertEqual([intent.duration_ms for intent in intents], [5000, 3000])

    def test_speaking_animation_has_multiple_speaking_frames(self):
        engine = ExpressionEngine()

        frames = engine.frames_for("speaking")

        self.assertGreaterEqual(len(frames), 4)
        self.assertTrue(all(isinstance(frame, ExpressionFrame) for frame in frames))
        self.assertTrue(all(frame.emotion == "speaking" for frame in frames))
        self.assertGreaterEqual(len({frame.text for frame in frames}), 3)

    def test_cute_animation_sets_exist_for_core_moods(self):
        engine = ExpressionEngine()

        for emotion in ("thinking", "happy", "listening", "surprised"):
            with self.subTest(emotion=emotion):
                frames = engine.frames_for(emotion)
                self.assertGreaterEqual(len(frames), 4)
                self.assertTrue(all(frame.emotion == emotion for frame in frames))
                self.assertTrue(all(0 < frame.duration_ms <= 5000 for frame in frames))

    def test_all_base_expressions_have_visible_animation_frames(self):
        engine = ExpressionEngine()

        for emotion in ALLOWED_EMOTIONS:
            with self.subTest(emotion=emotion):
                frames = engine.frames_for(emotion)

                self.assertGreaterEqual(len(frames), 2)
                self.assertTrue(all(frame.text for frame in frames))
                self.assertTrue(all(0 < frame.duration_ms <= 5000 for frame in frames))

    def test_unknown_expression_falls_back_to_visible_neutral_frames(self):
        engine = ExpressionEngine()

        frames = engine.frames_for("run_shell")

        self.assertGreaterEqual(len(frames), 2)
        self.assertTrue(all(frame.emotion == "neutral" for frame in frames))
        self.assertTrue(all(frame.text for frame in frames))

    def test_idle_neutral_animation_has_blink_frames(self):
        engine = ExpressionEngine()

        frames = engine.frames_for("neutral")

        self.assertGreaterEqual(len(frames), 2)
        self.assertTrue(all(frame.emotion == "neutral" for frame in frames))
        self.assertTrue(any(frame.text == "READY" for frame in frames))

    def test_error_animation_shakes_then_returns_neutral(self):
        engine = ExpressionEngine()

        frames = engine.frames_for("error")

        self.assertGreaterEqual(len(frames), 3)
        self.assertEqual(frames[0].emotion, "error")
        self.assertEqual(frames[-1].emotion, "neutral")


if __name__ == "__main__":
    unittest.main()
