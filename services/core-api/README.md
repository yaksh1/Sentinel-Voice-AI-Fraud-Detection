# `core-api`

System of record and the browser's only server-sent-events endpoint. Every database write in the product goes through here.

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

**SSE.** `GET /events?visitor_id` is where every browser stream terminates. Maintains `conn:{visitor_id}` in Redis with a heartbeat-refreshed TTL, subscribes to pub/sub, and fans `ring` / `session_ready` / `sandbox_busy` to the right connection. Buffers `events:{visitor_id}` (TTL 60 s) so a reconnect can replay via `Last-Event-ID`.

## Interfaces

| Direction | Channel |
|---|---|
| in | HTTP from `demo-web` (checkout, SSE) and `agent` (tools); Redis pub/sub `ring`, `session_ready`, `sandbox_busy` |
| out | SSE to `demo-web`; SQL to Neon; calls `risk-engine` |
| keys | `conn:{visitor_id}` (registry, TTL), `events:{visitor_id}` (replay buffer) |

## Status

Scaffold only. Built in [PLAN](../../docs/PLAN.md) 0.4 (schema), 2.3 (tools), 3.4 (checkout), 3.5 (SSE + registry), 3.9 (replay buffer).
