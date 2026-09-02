# `call-orchestrator`

The gatekeeper between an alert and a ringing phone. Everything that makes a callback safe to fire happens here.

**Tech:** FastAPI worker · Redis (streams, pub/sub, keys)

## Responsibilities

Per `fraud.alert`, in order:

1. `XREADGROUP fraud.alert` (consumer group — unacked entries are redelivered after a crash).
2. Dedupe: `SET NX alert:{alert_id}`; a duplicate alert never produces a second call.
3. Rate limit: 1 call per customer per 10 min.
4. Capacity: `DECR agent:capacity`; if negative, `INCR` back and publish `sandbox_busy` instead of ringing.
5. Mint `call_id` — the join key across the `calls` row, both streams, the pub/sub payloads, the WebRTC token, and the OTel trace.
6. Create the `calls` row as `ringing` — via `core-api` (`POST /internal/calls`), never directly against Neon — then start the 30 s ring timer and, **in parallel**, `PUBLISH ring` (stamping `alert_to_ring_ms`) and `XADD session.create`.
7. On `session.ready`, `PUBLISH session_ready`; `calls.state = ready`.

Failure edges it owns: ring timeout / decline → `no_answer` + `XADD session.cancel` so the agent releases its pre-warmed pipeline; `session.ready` never arrives → the same timer closes the call gracefully; transport failure → 3 attempts with exponential backoff.

## Interfaces

| Direction | Channel |
|---|---|
| in | stream `fraud.alert`, stream `session.ready` |
| out | stream `session.create`, stream `session.cancel`; pub/sub `ring`, `session_ready`, `sandbox_busy`; `calls` writes to `core-api` |
| keys | `alert:{id}` (dedupe), `agent:capacity` (counter) |

## Run

```
uv run uvicorn sentinel_call_orchestrator.main:app --port 8002
```

`/health` and `/metrics` (Prometheus text) are live; everything else is scaffold.

## Status

Scaffold only. Built in [PLAN](../../docs/PLAN.md) 3.6.
