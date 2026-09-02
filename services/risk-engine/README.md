# `risk-engine`

Rule-based transaction scoring. Deliberately fake — the point is the pipeline around it, not the detection.

**Tech:** FastAPI · Redis Streams producer

## Responsibilities

- Evaluate a transaction against rules: foreign merchant ∧ amount > threshold.
- On a hit, `XADD fraud.alert` with the reasons that fired.
- Nothing else — no dedupe, no rate limiting, no dialing. Those belong to `call-orchestrator`.

## Interfaces

| Direction | Channel |
|---|---|
| in | called by `core-api` during `POST /checkout` |
| out | Redis stream `fraud.alert` → `{alert_id, txn_id, customer_id, risk_reasons[], emitted_at}` |

## Status

Scaffold only. Built in [PLAN](../../docs/PLAN.md) 3.3.
