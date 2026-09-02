# `agent`

The voice pipeline and the only service that talks to the caller. Also the only service with irreversible powers — which is why its authority lives in a state machine, not a prompt.

**Tech:** Pipecat · SmallWebRTC (Twilio μ-law in v1.1) · Deepgram Nova (STT) · Cerebras `gpt-oss-120b` (turn loop) · Claude Sonnet 5 (judge) · Cartesia (TTS)

## Responsibilities

- Consume `session.create`; hand out a pre-warmed pipeline (warm pool 1, max 3 concurrent), keep it silent, `XADD session.ready {call_id, session_url, token, expires_at}`.
- Validate the single-use, `call_id`-bound token on WebRTC connect; reject reused or foreign tokens and write an audit row.
- Run the turn loop: STT → LLM → tools → TTS, emitting `{reply_text, proposed_state, tool_call?}` as structured output.
- Enforce the pathway state machine in code: the LLM *proposes* a transition, the validator accepts or rejects it. `action_release` / `action_block` / `escalate` are unreachable without a passed `verify_identity`.
- Escalate to the judge on validator rejection or a proposed irreversible action — at most once per turn. **The verdict is re-validated, never trusted**; a second rejection lands in `escalate_to_analyst`, and an Anthropic timeout or 429 fails closed.
- Redact PAN (regex + Luhn) on every transcript and log line before persistence.
- Own `calls.state` from WebRTC connect to teardown; `INCR agent:capacity` and refill the warm pool on end.
- Emit OTel spans per turn (`stt`, `llm`, `tool.*`, `tts`, `network`) with `trace_id = call_id`.

**Not here:** dedupe, rate limiting, and the ring timer belong to `call-orchestrator`; database writes go through `core-api` tools.

## Interfaces

| Direction | Channel |
|---|---|
| in | stream `session.create`, stream `session.cancel`; WebRTC media from `demo-web` |
| out | stream `session.ready`; key `agent:capacity`; tool calls to `core-api` |

## Run

```
uv run uvicorn sentinel_agent.main:app --port 8003
```

| Route | What it does |
|---|---|
| `GET /health` | Liveness probe |
| `GET /metrics` | Prometheus text |
| `POST /api/offer` | WebRTC signalling — answers a browser's SDP offer and starts a pipeline behind it |
| `PATCH /api/offer` | Trickled ICE candidates for an offer already answered |

Run `demo-web` alongside it to talk to the agent from a browser. For a number
rather than an impression:

```
uv run python services/agent/tools/echo_probe.py
```

Set `ICE_SERVERS` (comma-separated) to override the default STUN server; only
host candidates are needed when the browser is on the same machine.
`DEMO_WEB_ORIGIN` lists the origins allowed to post an offer.

Every inbound audio frame logs its arrival timing at DEBUG:

```
call_id=fd357ca9-… net_ms=-5.4
```

Fifty lines a second, which is what PLAN 1.3 asks for; 4.4 turns them into
metrics. See `sentinel_agent/timing.py` for what `net_ms` measures and what it
deliberately does not.

## Status

The echo pipeline is live ([PLAN](../../docs/PLAN.md) 1.1) — audio in, the same
audio back out, nothing between. Still to come: 2.1–2.7 (conversation, persona,
redaction), 3.1–3.2 / 3.7–3.8 / 3.11 (state machine, session lifecycle, token,
judge). Each replaces the middle of the same pipeline; the transport stays.
