# `demo-web`

Public sandbox front end: the fake checkout, the voice widget (mic or text), and the live dashboard.

**Tech:** Next.js · Pipecat JS client · SSE consumer

## Responsibilities

- Mint an anonymous `visitor_id` on page load (cookie) and open `GET core-api/events?visitor_id=…` (SSE) for the lifetime of the page.
- Render the fake checkout — *Pay $940 at "Lisboa Eletrónica"* — and `POST core-api/checkout`.
- Ring on the `ring` event, offer Answer / Decline, and connect WebRTC media to `agent` with the single-use token from `session_ready`.
- Fall back to a "sandbox busy" state on `sandbox_busy`, and offer **Type instead** (text mode) when the visitor declines mic access.
- Show the live dashboard: `calls.state`, outcome, audit rows, per-turn `stt_ms / llm_ms / tts_ms / net_ms`.

**Not here:** no long-lived connection terminates in this service. SSE terminates in `core-api`; WebRTC media terminates in `agent`.

## Interfaces

| Direction | Channel |
|---|---|
| out | `POST core-api/checkout {visitor_id, amount, merchant}` |
| in | SSE `core-api/events?visitor_id` → `ring`, `session_ready`, `sandbox_busy` (replayed via `Last-Event-ID`) |
| both | WebRTC media ↔ `agent`, authorised by the `call_id`-bound token |

## Run

```
npm install
npm run dev          # http://localhost:3000
```

The agent must be running too, or Connect has nothing to negotiate with:

```
uv run uvicorn sentinel_agent.main:app --port 8003
```

| Variable | Default | Notes |
|---|---|---|
| `NEXT_PUBLIC_AGENT_OFFER_URL` | `http://localhost:8003/api/offer` | Put overrides in `.env.local`. `NEXT_PUBLIC_` is required — the browser reads it |

The agent must allow this origin (`DEMO_WEB_ORIGIN`, default `http://localhost:3000`):
the offer POST is cross-origin and the browser preflights it. The media that
follows is not subject to CORS.

## Status

Connect works and the agent echoes you back ([PLAN](../../docs/PLAN.md) 1.2).
`app/voice-widget.tsx` is the whole of it — a Connect button, mic permission,
and an `<audio>` element for the returning track. Still to come: 3.10 (SSE
client + ring UI), 4.1 (checkout page), 4.2 (dashboard).
