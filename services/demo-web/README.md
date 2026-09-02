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

## Status

Scaffold only. Built in [PLAN](../../docs/PLAN.md) 1.2 (Connect + echo), 3.10 (SSE client + ring UI), 4.1 (checkout page), 4.2 (dashboard).
