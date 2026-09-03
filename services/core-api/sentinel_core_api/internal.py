"""Internal endpoints, called by services rather than by the browser.

`POST /internal/turns` is the only way a turn reaches the database, and it
redacts on the way in (PLAN 2.6). That is deliberate: the schema has a
`text_redacted` column and no unredacted counterpart, so the redactor cannot be
skipped by writing somewhere else. A caller who reads a card number aloud has it
removed here, before it is ever stored.

The call-row endpoints (`POST /internal/calls`, `PATCH .../state`) that
`call-orchestrator` and `agent` drive land in Phase 3.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sentinel_contracts.redact import redact_pan
from sentinel_core_api import db

router = APIRouter(prefix="/internal", tags=["internal"])


class Turn(BaseModel):
    call_id: UUID
    idx: int
    role: str  # 'agent' | 'caller'
    text: str
    stt_ms: int | None = None
    llm_ms: int | None = None
    tts_ms: int | None = None
    net_ms: int | None = None


# db/seed.sql — the demo's own rows.
DEMO_TXN = "00000000-0000-0000-0000-000000000003"
DEMO_CARD = "00000000-0000-0000-0000-000000000002"


@router.post("/demo/reset")
async def reset_demo() -> dict[str, Any]:
    """Put the seeded transaction and card back the way a call finds them.

    A demo is only repeatable if it starts from the same place: after a deny run
    the transaction is blocked and the card is dead, so the next caller who
    confirms the charge gets "transaction is blocked, not held" — a correct
    answer to the wrong question.

    `audit_log` is deliberately left alone. It is a log, PLAN 5.1 reads it, and a
    reset that quietly erases the record of what the agent did would defeat the
    point of having one.
    """
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE transactions SET status = 'held', updated_at = now() WHERE id = $1",
            UUID(DEMO_TXN),
        )
        await conn.execute(
            "UPDATE cards SET status = 'active', reissued_at = NULL WHERE id = $1",
            UUID(DEMO_CARD),
        )
    return {"reset": True, "transaction": "held", "card": "active"}


@router.post("/turns")
async def record_turn(turn: Turn) -> dict[str, Any]:
    """Store one turn of the conversation, redacted."""
    if turn.role not in ("agent", "caller"):
        raise HTTPException(422, "role must be 'agent' or 'caller'")

    redacted = redact_pan(turn.text)
    async with db.pool().acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO turns (call_id, idx, role, text_redacted,
                                   stt_ms, llm_ms, tts_ms, net_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (call_id, idx) DO UPDATE SET text_redacted = EXCLUDED.text_redacted
                RETURNING id, text_redacted
                """,
                turn.call_id,
                turn.idx,
                turn.role,
                redacted,
                turn.stt_ms,
                turn.llm_ms,
                turn.tts_ms,
                turn.net_ms,
            )
        except Exception as exc:  # foreign key: the call must exist first
            raise HTTPException(409, f"could not record turn: {exc}") from exc

    return {"id": row["id"], "text_redacted": row["text_redacted"]}
