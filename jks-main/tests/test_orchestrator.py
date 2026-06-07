from __future__ import annotations

from pathlib import Path
import unittest

from jks.agent import AgentReply, AgentTraceEvent, parse_agent_reply
from jks.display import DisplayIntent
from jks.expression import DisplayCommand, ExpressionEngine, TurnState
from jks.orchestrator import ConversationOrchestrator, TurnFailure


class FakeRecorder:
    def __init__(self, fail=False):
        self.fail = fail
        self.recordings = 0

    def record_fixed_seconds(self, seconds=4.0):
        self.recordings += 1
        if self.fail:
            raise RuntimeError("recorder failed")
        return Path("/tmp/jks-test-input.wav")


class ToggleRecorder:
    def __init__(self, fail_start=False, fail_stop=False):
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.starts = 0
        self.stops = 0

    def start_recording(self):
        self.starts += 1
        if self.fail_start:
            raise RuntimeError("start failed")

    def stop_recording(self):
        self.stops += 1
        if self.fail_stop:
            raise RuntimeError("stop failed")
        return Path("/tmp/jks-toggle-input.wav")


class FakeSpeech:
    def __init__(self, user_text="hello", fail_transcribe=False, fail_synthesize=False):
        self.user_text = user_text
        self.fail_transcribe = fail_transcribe
        self.fail_synthesize = fail_synthesize
        self.transcribed = []
        self.synthesized = []

    def transcribe(self, audio_path):
        self.transcribed.append(audio_path)
        if self.fail_transcribe:
            raise RuntimeError("stt failed")
        return self.user_text

    def synthesize(self, text, voice):
        self.synthesized.append((text, voice))
        if self.fail_synthesize:
            raise RuntimeError("tts failed")
        return Path("/tmp/jks-test-reply.wav")


class FakeStreamingSpeech(FakeSpeech):
    def __init__(self, user_text="hello", fail_stream=False):
        super().__init__(user_text=user_text)
        self.fail_stream = fail_stream
        self.streamed = []

    def synthesize_and_play(self, text, voice, player):
        self.streamed.append((text, voice, player))
        if self.fail_stream:
            raise RuntimeError("stream tts failed")


class FakeAgent:
    def __init__(self, reply=None, fail=False):
        self.reply = reply or AgentReply(text="reply", emotion="happy")
        self.fail = fail
        self.messages = []
        self.conversation_ids = []

    def send_message(self, text, conversation_id, trace_callback=None):
        self.messages.append(text)
        self.conversation_ids.append(conversation_id)
        if trace_callback is not None:
            trace_callback(AgentTraceEvent(source="assistant", message="tool call: terminal"))
        if self.fail:
            raise RuntimeError("agent failed")
        return self.reply


class FakeDisplay:
    def __init__(self):
        self.intents = []
        self.clears = 0

    def show(self, intent):
        self.intents.append(intent)

    def clear(self):
        self.clears += 1


class FailingDisplay:
    def show(self, intent):
        raise OSError("oled disconnected")

    def clear(self):
        raise OSError("oled disconnected")


class ErrorOnlyFailingDisplay(FakeDisplay):
    def show(self, intent):
        if intent.emotion == "error":
            raise OSError("error display failed")
        super().show(intent)


class FakePlayer:
    def __init__(self, fail=False):
        self.fail = fail
        self.played = []

    def play(self, audio_path):
        self.played.append(audio_path)
        if self.fail:
            raise RuntimeError("player failed")


ERROR_INTENT = DisplayIntent(emotion="error", text="OOPS", duration_ms=900, intensity="high")


class RecordingExpressionEngine:
    def __init__(self):
        self.real = ExpressionEngine()
        self.agent_payloads = []

    def intent_for_state(self, state):
        return self.real.intent_for_state(state)

    def intent_from_agent(self, payload):
        self.agent_payloads.append(dict(payload))
        return self.real.intent_from_agent(payload)

    def display_actions_from_agent(self, payload):
        self.agent_payloads.append(dict(payload))
        return [DisplayCommand("show", intent) for intent in self.real.intents_from_agent(payload)]


class OrchestratorTests(unittest.TestCase):
    def test_successful_voice_turn_updates_oled_in_order_and_returns_turn_result(self):
        display = FakeDisplay()
        player = FakePlayer()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(user_text="hello"),
            agent=FakeAgent(reply=AgentReply(text="reply", emotion="happy")),
            display=display,
            player=player,
            voice="warm",
        )

        result = orchestrator.run_voice_turn()

        self.assertEqual(result.user_text, "hello")
        self.assertEqual(result.agent_text, "reply")
        self.assertEqual(result.emotion, "happy")
        self.assertEqual(
            [(intent.emotion, intent.text) for intent in display.intents],
            [
                ("listening", "HEAR"),
                ("thinking", "TEXT"),
                ("thinking", "WAIT"),
                ("speaking", "TALK"),
                ("happy", "DONE"),
            ],
        )
        self.assertEqual(player.played, [Path("/tmp/jks-test-reply.wav")])
        self.assertEqual(orchestrator.agent.messages, ["hello"])
        self.assertEqual(orchestrator.speech.synthesized, [("reply", "warm")])
        self.assertEqual(orchestrator.state, TurnState.IDLE)

    def test_voice_turn_prefers_streaming_speech_playback_when_available(self):
        speech = FakeStreamingSpeech(user_text="hello")
        player = FakePlayer()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=speech,
            agent=FakeAgent(reply=AgentReply(text="reply", emotion="happy")),
            display=FakeDisplay(),
            player=player,
            voice="warm",
        )

        result = orchestrator.run_voice_turn()

        self.assertEqual(result.audio_error, "")
        self.assertEqual(speech.streamed, [("reply", "warm", player)])
        self.assertEqual(speech.synthesized, [])
        self.assertEqual(player.played, [])

    def test_status_callback_reports_turn_state_progress(self):
        states = []
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(user_text="hello"),
            agent=FakeAgent(reply=AgentReply(text="reply", emotion="happy")),
            display=FakeDisplay(),
            player=FakePlayer(),
            voice="warm",
            status_callback=states.append,
        )

        orchestrator.run_voice_turn()

        self.assertEqual(
            states,
            [
                TurnState.LISTENING,
                TurnState.TRANSCRIBING,
                TurnState.THINKING,
                TurnState.SPEAKING,
            ],
        )

    def test_agent_trace_callback_is_forwarded_to_agent(self):
        events = []
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(user_text="hello"),
            agent=FakeAgent(reply=AgentReply(text="reply", emotion="happy")),
            display=FakeDisplay(),
            player=FakePlayer(),
            voice="warm",
            agent_trace_callback=events.append,
        )

        orchestrator.run_voice_turn()

        self.assertEqual(
            events,
            [AgentTraceEvent(source="assistant", message="tool call: terminal")],
        )

    def test_start_and_finish_voice_turn_support_button_toggle_recording(self):
        display = FakeDisplay()
        recorder = ToggleRecorder()
        orchestrator = ConversationOrchestrator(
            recorder=recorder,
            speech=FakeSpeech(user_text="hello"),
            agent=FakeAgent(reply=AgentReply(text="reply", emotion="happy")),
            display=display,
            player=FakePlayer(),
            voice="warm",
        )

        orchestrator.start_recording()
        result = orchestrator.finish_voice_turn()

        self.assertEqual(recorder.starts, 1)
        self.assertEqual(recorder.stops, 1)
        self.assertEqual(result.user_text, "hello")
        self.assertEqual(result.agent_text, "reply")
        self.assertEqual(
            [(intent.emotion, intent.text) for intent in display.intents],
            [
                ("listening", "HEAR"),
                ("thinking", "TEXT"),
                ("thinking", "WAIT"),
                ("speaking", "TALK"),
                ("happy", "DONE"),
            ],
        )
        self.assertEqual(orchestrator.state, TurnState.IDLE)

    def test_recording_toggle_rejects_invalid_or_overlapping_turns(self):
        orchestrator = ConversationOrchestrator(
            recorder=ToggleRecorder(),
            speech=FakeSpeech(),
            agent=FakeAgent(),
            display=FakeDisplay(),
            player=FakePlayer(),
            voice="warm",
        )

        with self.assertRaises(RuntimeError):
            orchestrator.finish_voice_turn()

        orchestrator.start_recording()
        with self.assertRaises(RuntimeError):
            orchestrator.start_recording()

    def test_recording_toggle_failure_shows_error_and_allows_retry(self):
        display = FakeDisplay()
        recorder = ToggleRecorder(fail_stop=True)
        orchestrator = ConversationOrchestrator(
            recorder=recorder,
            speech=FakeSpeech(),
            agent=FakeAgent(),
            display=display,
            player=FakePlayer(),
            voice="warm",
        )

        orchestrator.start_recording()
        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            orchestrator.finish_voice_turn()

        self.assertEqual(display.intents[-1], ERROR_INTENT)
        self.assertEqual(orchestrator.state, TurnState.IDLE)

    def test_agent_display_intent_fields_are_passed_to_expression_and_clamped(self):
        display = FakeDisplay()
        expression = RecordingExpressionEngine()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(),
            agent=FakeAgent(
                reply=AgentReply(
                    text="reply",
                    emotion="surprised",
                    display_text="AGENT SAYS TOO MUCH",
                    duration_ms=999999,
                    intensity="overdrive",
                )
            ),
            display=display,
            player=FakePlayer(),
            voice="warm",
        )
        orchestrator.expression = expression

        orchestrator.run_voice_turn()

        self.assertEqual(
            expression.agent_payloads,
            [
                {
                    "emotion": "surprised",
                    "display_text": "AGENT SAYS TOO MUCH",
                    "duration_ms": 999999,
                    "intensity": "overdrive",
                    "display_sequence": None,
                    "display_commands": None,
                }
            ],
        )
        self.assertEqual(
            display.intents[-1],
            DisplayIntent(
                emotion="surprised",
                text="AGENT SAYS TOO",
                duration_ms=5000,
                intensity="normal",
            ),
        )

    def test_parsed_nested_display_intent_is_still_clamped_by_expression(self):
        display = FakeDisplay()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(),
            agent=FakeAgent(
                reply=parse_agent_reply(
                    {
                        "result": {
                            "text": "reply",
                            "display_intent": {
                                "emotion": "made-up",
                                "display_text": "THIS TEXT IS FAR TOO LONG FOR OLED",
                                "duration_ms": 999999,
                                "intensity": "unsafe",
                            },
                        }
                    }
                )
            ),
            display=display,
            player=FakePlayer(),
            voice="warm",
        )

        result = orchestrator.run_voice_turn()

        self.assertEqual(result.agent_text, "reply")
        self.assertEqual(result.emotion, "neutral")
        self.assertEqual(
            display.intents[-1],
            DisplayIntent(
                emotion="neutral",
                text="THIS TEXT IS F",
                duration_ms=5000,
                intensity="normal",
            ),
        )

    def test_agent_display_sequence_controls_screen_steps_after_speaking(self):
        display = FakeDisplay()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(),
            agent=FakeAgent(
                reply=AgentReply(
                    text="reply",
                    display_sequence=[
                        {
                            "emotion": "thinking",
                            "display_text": "PLAN",
                            "duration_ms": 400,
                            "intensity": "soft",
                        },
                        {
                            "emotion": "happy",
                            "display_text": "DONE",
                            "duration_ms": 900,
                            "intensity": "high",
                        },
                    ],
                )
            ),
            display=display,
            player=FakePlayer(),
            voice="warm",
        )

        result = orchestrator.run_voice_turn()

        self.assertEqual(result.emotion, "happy")
        self.assertEqual(result.display_text, "DONE")
        self.assertEqual(
            display.intents[-2:],
            [
                DisplayIntent("thinking", "PLAN", duration_ms=400, intensity="soft"),
                DisplayIntent("happy", "DONE", duration_ms=900, intensity="high"),
            ],
        )

    def test_agent_display_commands_support_clear_and_text_without_raw_serial_access(self):
        display = FakeDisplay()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(),
            agent=FakeAgent(
                reply=AgentReply(
                    text="reply",
                    display_commands=[
                        {"cmd": "probe"},
                        {"cmd": "text", "text": "SCREEN"},
                        {"cmd": "clear"},
                        {"cmd": "emotion", "emotion": "surprised", "text": "WOW"},
                    ],
                )
            ),
            display=display,
            player=FakePlayer(),
            voice="warm",
        )

        result = orchestrator.run_voice_turn()

        self.assertEqual(display.clears, 1)
        self.assertEqual(result.emotion, "surprised")
        self.assertEqual(
            display.intents[-2:],
            [
                DisplayIntent("neutral", "SCREEN", duration_ms=500, intensity="soft"),
                DisplayIntent("surprised", "WOW", duration_ms=1000, intensity="high"),
            ],
        )

    def test_missing_agent_emotion_defaults_to_happy_and_done_label(self):
        display = FakeDisplay()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(),
            agent=FakeAgent(reply=AgentReply(text="reply")),
            display=display,
            player=FakePlayer(),
            voice="warm",
        )

        result = orchestrator.run_voice_turn()

        self.assertEqual(result.emotion, "happy")
        self.assertEqual(display.intents[-1], DisplayIntent("happy", "DONE", duration_ms=1200, intensity="high"))
        self.assertEqual(result.display_text, "DONE")

    def test_recorder_stt_and_agent_failures_show_error_and_reraise(self):
        cases = [
            {"name": "recorder", "recorder": FakeRecorder(fail=True), "speech": FakeSpeech(), "agent": FakeAgent(), "player": FakePlayer()},
            {"name": "stt", "speech": FakeSpeech(fail_transcribe=True), "agent": FakeAgent(), "player": FakePlayer()},
            {"name": "agent", "speech": FakeSpeech(), "agent": FakeAgent(fail=True), "player": FakePlayer()},
        ]

        for case in cases:
            with self.subTest(case=case["name"]):
                display = FakeDisplay()
                orchestrator = ConversationOrchestrator(
                    recorder=case.get("recorder", FakeRecorder()),
                    speech=case["speech"],
                    agent=case["agent"],
                    display=display,
                    player=case["player"],
                    voice="warm",
                )

                with self.assertRaises(RuntimeError):
                    orchestrator.run_voice_turn()

                self.assertEqual(display.intents[-1], ERROR_INTENT)

    def test_stt_failure_preserves_recorded_audio_path_for_debugging(self):
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(fail_transcribe=True),
            agent=FakeAgent(),
            display=FakeDisplay(),
            player=FakePlayer(),
            voice="warm",
        )

        with self.assertRaisesRegex(TurnFailure, "stt failed") as caught:
            orchestrator.run_voice_turn()

        self.assertEqual(caught.exception.audio_path, Path("/tmp/jks-test-input.wav"))
        self.assertEqual(caught.exception.user_text, "")
        self.assertEqual(orchestrator.state, TurnState.IDLE)

    def test_agent_failure_preserves_transcribed_user_text_for_resend(self):
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(user_text="hello"),
            agent=FakeAgent(fail=True),
            display=FakeDisplay(),
            player=FakePlayer(),
            voice="warm",
        )

        with self.assertRaisesRegex(TurnFailure, "agent failed") as caught:
            orchestrator.run_voice_turn()

        self.assertEqual(caught.exception.audio_path, Path("/tmp/jks-test-input.wav"))
        self.assertEqual(caught.exception.user_text, "hello")
        self.assertEqual(orchestrator.state, TurnState.IDLE)

    def test_empty_transcript_fails_before_agent_and_tts(self):
        agent = FakeAgent()
        speech = FakeSpeech(user_text="  ")
        player = FakePlayer()
        display = FakeDisplay()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=speech,
            agent=agent,
            display=display,
            player=player,
            voice="warm",
        )

        with self.assertRaisesRegex(TurnFailure, "empty transcript") as caught:
            orchestrator.run_voice_turn()

        self.assertEqual(caught.exception.audio_path, Path("/tmp/jks-test-input.wav"))
        self.assertEqual(agent.messages, [])
        self.assertEqual(speech.synthesized, [])
        self.assertEqual(player.played, [])
        self.assertEqual(display.intents[-1], ERROR_INTENT)
        self.assertEqual(orchestrator.state, TurnState.IDLE)

    def test_tts_and_player_failures_preserve_agent_text_as_silent_fallback(self):
        cases = [
            {
                "name": "tts",
                "speech": FakeSpeech(fail_synthesize=True),
                "player": FakePlayer(),
                "expected_error": "tts failed",
                "expected_played": [],
            },
            {
                "name": "player",
                "speech": FakeSpeech(),
                "player": FakePlayer(fail=True),
                "expected_error": "player failed",
                "expected_played": [Path("/tmp/jks-test-reply.wav")],
            },
        ]

        for case in cases:
            with self.subTest(case=case["name"]):
                display = FakeDisplay()
                orchestrator = ConversationOrchestrator(
                    recorder=FakeRecorder(),
                    speech=case["speech"],
                    agent=FakeAgent(reply=AgentReply(text="reply", emotion="happy")),
                    display=display,
                    player=case["player"],
                    voice="warm",
                )

                result = orchestrator.run_voice_turn()

                self.assertEqual(result.agent_text, "reply")
                self.assertEqual(result.audio_error, case["expected_error"])
                self.assertEqual(result.emotion, "error")
                self.assertEqual(case["player"].played, case["expected_played"])
                self.assertEqual(display.intents[-1], ERROR_INTENT)
                self.assertEqual(orchestrator.state, TurnState.IDLE)

    def test_display_failures_do_not_interrupt_successful_voice_turn(self):
        player = FakePlayer()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(user_text="hello"),
            agent=FakeAgent(reply=AgentReply(text="reply", emotion="happy")),
            display=FailingDisplay(),
            player=player,
            voice="warm",
        )

        result = orchestrator.run_voice_turn()

        self.assertEqual(result.user_text, "hello")
        self.assertEqual(result.agent_text, "reply")
        self.assertEqual(player.played, [Path("/tmp/jks-test-reply.wav")])

    def test_runtime_display_failure_reports_degraded_status_once(self):
        display_errors = []
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(user_text="hello"),
            agent=FakeAgent(reply=AgentReply(text="reply", emotion="happy")),
            display=FailingDisplay(),
            player=FakePlayer(),
            voice="warm",
            display_error_callback=display_errors.append,
        )

        result = orchestrator.run_voice_turn()

        self.assertEqual(result.agent_text, "reply")
        self.assertEqual(display_errors, ["OLED update failed: oled disconnected"])

    def test_error_display_failure_preserves_original_exception(self):
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(),
            agent=FakeAgent(fail=True),
            display=ErrorOnlyFailingDisplay(),
            player=FakePlayer(),
            voice="warm",
        )

        with self.assertRaisesRegex(RuntimeError, "agent failed"):
            orchestrator.run_voice_turn()

    def test_conversation_id_is_stable_across_turns(self):
        agent = FakeAgent()
        orchestrator = ConversationOrchestrator(
            recorder=FakeRecorder(),
            speech=FakeSpeech(),
            agent=agent,
            display=FakeDisplay(),
            player=FakePlayer(),
            voice="warm",
        )

        orchestrator.run_voice_turn()
        orchestrator.run_voice_turn()

        self.assertEqual(len(agent.conversation_ids), 2)
        self.assertTrue(agent.conversation_ids[0])
        self.assertEqual(agent.conversation_ids[0], agent.conversation_ids[1])


if __name__ == "__main__":
    unittest.main()
