# `core-api`

System of record and the browser's only server-sent-events endpoint. Owns the schema and, apart from
`fraud_alerts`, every write in the product — including the `calls` row, which `call-orchestrator` and
`agent` drive through this service rather than writing themselves.

**Tech:** FastAPI · Neon Postgres · Redis

## Responsibilities

**Data.** `customers`, `cards`, `transactions`, `fraud_alerts`, `calls`, `turns`, `audit_log`, `sandbox_sessions` (schema in [BRIEF §5](../../docs/BRIEF.md)).

**Tools** exposed to `agent`, each writing an `audit_log` row and each guarded by call state:

| Tool | Guard |
|---|---|
| `lookup_transaction(alert_id)` | state ≥ `present_transaction` |
| `verify_challenge(last4, answer)` | state = `verify_identity` |
| `release_hold(txn_id)` | verified ∧ state = `action_release` |
| `block_card_and_reissue(card_id)` | verified ∧ state = `action_block` |
| `escalate_to_analyst(call_id, reason)` | any |

**Checkout.** `POST /checkout {visitor_id, amount, merchant}` writes a `held` transaction and calls `risk-engine`.

**Call rows** (internal, service-token auth). `POST /internal/calls` creates the row at `ringing`; `PATCH /internal/calls/{call_id}/state` applies a single transition — validating it, appending to `state_history`, and stamping `ring_at` / `ready_at` / `connected_at`. The orchestrator drives it through `ready`, the agent from `connected` on. Keeping both behind one endpoint is why transition legality has exactly one implementation ([ARCHITECTURE §7](../../docs/ARCHITECTURE.md)).

**SSE.** `GET /events?visitor_id` is where every browser stream terminates. Maintains `conn:{visitor_id}` in Redis with a heartbeat-refreshed TTL, subscribes to pub/sub, and fans `ring` / `session_ready` / `sandbox_busy` to the right connection. Buffers `events:{visitor_id}` (TTL 60 s) so a reconnect can replay via `Last-Event-ID`.

## Interfaces

| Direction | Channel |
|---|---|
| in | HTTP from `demo-web` (checkout, SSE) and `agent` (tools); Redis pub/sub `ring`, `session_ready`, `sandbox_busy` |
| in | `POST /internal/calls`, `PATCH /internal/calls/{call_id}/state` from `call-orchestrator` and `agent` |
| out | SSE to `demo-web`; SQL to Neon; calls `risk-engine` |
| keys | `conn:{visitor_id}` (registry, TTL), `events:{visitor_id}` (replay buffer) |

## Run

```
uv run uvicorn sentinel_core_api.main:app --port 8000
```

`/health` and `/metrics` (Prometheus text) are live; everything else is scaffold.

## Status

Scaffold only. Built in [PLAN](../../docs/PLAN.md) 0.4 (schema), 2.3 (tools), 3.4 (checkout), 3.5 (SSE + registry), 3.9 (replay buffer).
