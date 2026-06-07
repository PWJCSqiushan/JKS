# JKS Agent Contract Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local agent adapter accept common Hermes / Gran-style response envelopes without connecting to a real remote service or committing credentials.

**Architecture:** Keep the existing `HttpAgentClient` request contract stable for now. Expand the pure `parse_agent_reply()` path so it can normalize plain text, current JKS JSON, OpenAI-like choices, nested `data/result/output` envelopes, message lists, content parts, and nested display intent into the existing `AgentReply`. This gives us a safe fixture-driven contract layer before live endpoint probing.

**Tech Stack:** Python 3.9+, standard-library `unittest`, existing `requests` HTTP client, pure parser tests in `tests/test_agent_client.py`.

---

## File Structure

- Modify: `src/jks/agent.py` - add response normalization helpers while keeping `AgentReply` and `HttpAgentClient` public API stable.
- Modify: `tests/test_agent_client.py` - add fixture tests for Hermes / Gran-style envelopes and nested display intent.

## Task 1: Agent Response Envelope Parsing

**Files:**
- Modify: `tests/test_agent_client.py`
- Modify: `src/jks/agent.py`

- [ ] **Step 1: Write failing parser tests**

Add tests to `tests/test_agent_client.py`:

```python
    def test_parse_openai_like_choice_message_content(self):
        reply = parse_agent_reply(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "choice answer",
                        }
                    }
                ]
            }
        )

        self.assertEqual(reply, AgentReply(text="choice answer"))

    def test_parse_nested_result_output_envelope(self):
        reply = parse_agent_reply(
            {
                "result": {
                    "output": {
                        "message": "nested answer",
                        "display": {
                            "emotion": "thinking",
                            "text": "WAIT",
                            "duration_ms": 1400,
                            "intensity": "normal",
                        },
                    }
                }
            }
        )

        self.assertEqual(
            reply,
            AgentReply(
                text="nested answer",
                emotion="thinking",
                display_text="WAIT",
                duration_ms=1400,
                intensity="normal",
            ),
        )

    def test_parse_messages_list_uses_last_assistant_message(self):
        reply = parse_agent_reply(
            {
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": [{"type": "text", "text": "first"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "second"}]},
                ]
            }
        )

        self.assertEqual(reply, AgentReply(text="second"))

    def test_parse_response_content_parts(self):
        reply = parse_agent_reply(
            {
                "response": {
                    "content": [
                        {"type": "text", "text": "hello"},
                        {"type": "text", "text": " world"},
                    ]
                }
            }
        )

        self.assertEqual(reply, AgentReply(text="hello world"))
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run python -m unittest tests.test_agent_client -v
```

Expected: new tests fail because the existing parser stringifies nested dictionaries or returns empty text.

- [ ] **Step 3: Implement normalization helpers**

Update `src/jks/agent.py`:

- Keep `AgentReply` unchanged.
- Add private helpers:
  - `_first_present(mapping, keys)`
  - `_content_to_text(content)`
  - `_extract_display_fields(payload)`
  - `_unwrap_envelope(payload)`
  - `_extract_text(payload)`
- `parse_agent_reply()` should:
  - Return plain strings as before.
  - For dicts, unwrap `result`, `data`, `output`, and `response` envelopes when they are the only useful layer.
  - Parse OpenAI-like `choices[0].message.content` or `choices[0].text`.
  - Parse `messages` by selecting the last assistant message, falling back to the last message.
  - Parse content parts by concatenating `{"type":"text","text":...}` parts.
  - Preserve direct `text` and `reply` behavior.
  - Preserve direct display fields and nested display fields from `display`, `display_intent`, or `expression`.

- [ ] **Step 4: Run test to verify GREEN**

Run:

```bash
uv run python -m unittest tests.test_agent_client -v
```

Expected: all agent client tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/jks/agent.py tests/test_agent_client.py
git commit -m "feat: support agent response envelopes"
```

## Task 2: Verification

**Files:**
- No required source changes.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run python -m unittest tests.test_agent_client tests.test_orchestrator tests.test_smoke -v
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full tests**

Run:

```bash
uv run python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Run no-secret smoke**

Run:

```bash
uv run python -m tools.jks_smoke
```

Expected: compact JSON with `"ok":true`.

- [ ] **Step 4: Run OLED smoke if connected**

Run:

```bash
uv run python -m tools.oled_smoke --port /dev/cu.usbmodem5B900048301
```

Expected: compact JSON with `"ok":true` and details `probe`, `happy`, `text`, `clear`. If OLED is disconnected, record the failure instead of claiming hardware verification.

- [ ] **Step 5: Clean tree**

Run:

```bash
git status --short
```

Expected: no uncommitted changes after commit.
