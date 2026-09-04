"""The five tools the agent can call (PLAN 2.3).

Each one makes its database change and writes its `audit_log` row in the same
transaction, so there is no way to have acted without a record of having acted.
That is the property PLAN 5.1 tests: it reads `audit_log` to prove no
irreversible action ever happened without a prior verification.

**Guards are not here yet.** BRIEF §5 binds each tool to a call state —
`release_hold` only in `action_release`, and only once verified. That is PLAN
3.2, and it lands on top of these. Until it does, these endpoints do what they
are asked; the agent is trusted, which is exactly the thing 3.1 and 3.2 stop
being true.
"""

import json
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sentinel_core_api import db

router = APIRouter(prefix="/tools", tags=["tools"])


async def _audit(
    conn: asyncpg.Connection,
    call_id: UUID | None,
    tool: str,
    args: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Record one tool call. Always in the caller's transaction, never after it."""
    await conn.execute(
        """
        INSERT INTO audit_log (call_id, tool, args_redacted, result)
        VALUES ($1, $2, $3::jsonb, $4::jsonb)
        """,
        call_id,
        tool,
        json.dumps(args),
        json.dumps(result, default=str),
    )


class LookupTransaction(BaseModel):
    alert_id: UUID
    call_id: UUID | None = None


@router.post("/lookup_transaction")
async def lookup_transaction(req: LookupTransaction) -> dict[str, Any]:
    """What was flagged: merchant, amount, city, time.

    Returns `card_id` as well as `txn_id` because the agent needs both to act:
    a confirmed charge releases the transaction, a denied one blocks the card.
    """
    async with db.pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            SELECT t.id AS txn_id, t.card_id, t.amount_cents, t.currency, t.merchant_name,
                   t.merchant_city, t.merchant_country, t.occurred_at, t.status
            FROM fraud_alerts a
            JOIN transactions t ON t.id = a.txn_id
            WHERE a.alert_id = $1
            """,
            req.alert_id,
        )
        if row is None:
            raise HTTPException(404, "no such alert")

        result = dict(row)
        # Hand the model the amount already formatted. Asked to turn 94000 cents
        # into dollars it said "ninety-four dollars and ninety cents", which is
        # the wrong number said confidently to a customer about their own money.
        # Unit conversion is not a thing to leave to a language model.
        result["amount_display"] = f"{result['amount_cents'] / 100:,.2f} {result['currency']}"
        await _audit(
            conn, req.call_id, "lookup_transaction", {"alert_id": str(req.alert_id)}, result
        )
    return result


class VerifyChallenge(BaseModel):
    last4: str
    answer: str
    call_id: UUID | None = None
    customer_id: UUID | None = None


@router.post("/verify_challenge")
async def verify_challenge(req: VerifyChallenge) -> dict[str, Any]:
    """Two factors: the card's last four, and the customer's city of birth."""
    async with db.pool().acquire() as conn, conn.transaction():
        customer_id = req.customer_id
        if customer_id is None:
            if req.call_id is None:
                raise HTTPException(422, "one of call_id or customer_id is required")
            customer_id = await conn.fetchval(
                "SELECT customer_id FROM calls WHERE call_id = $1", req.call_id
            )
            if customer_id is None:
                raise HTTPException(404, "no such call")

        row = await conn.fetchrow(
            "SELECT city_of_birth, display_name FROM customers WHERE id = $1", customer_id
        )
        if row is None:
            raise HTTPException(404, "no such customer")

        last4_ok = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM cards WHERE customer_id = $1 AND last4 = $2)",
            customer_id,
            req.last4.strip(),
        )
        answer_ok = req.answer.strip().casefold() == row["city_of_birth"].strip().casefold()
        passed = bool(last4_ok) and answer_ok

        # Attempts are counted from audit_log rather than a column: every call
        # is already recorded there, so a second source of truth would only be
        # a second thing to keep correct. The retry cap (max 2, BRIEF §5) is
        # the state machine's to enforce in 3.1 — this only reports the count.
        prior = 0
        if req.call_id is not None:
            prior = await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE call_id = $1 AND tool = 'verify_challenge'",
                req.call_id,
            )
        result = {"passed": passed, "attempt": prior + 1}
        if passed:
            # The agent has no other way to learn who it is talking to, and a
            # fraud call that never uses the cardholder's name sounds like a
            # form. Only on a pass — an unverified caller is not owed the name
            # on the account.
            result["first_name"] = row["display_name"].split()[0]

        if passed and req.call_id is not None:
            await conn.execute(
                "UPDATE calls SET verified = true, updated_at = now() WHERE call_id = $1",
                req.call_id,
            )

        # The answer itself is never stored — only whether it matched. last4 is
        # not sensitive on its own and is what makes the row auditable.
        await _audit(
            conn,
            req.call_id,
            "verify_challenge",
            {"last4": req.last4, "last4_ok": bool(last4_ok), "answer_ok": answer_ok},
            result,
        )
    return result


class ReleaseHold(BaseModel):
    txn_id: UUID
    call_id: UUID | None = None


@router.post("/release_hold")
async def release_hold(req: ReleaseHold) -> dict[str, Any]:
    """The caller confirmed the charge: let it through."""
    async with db.pool().acquire() as conn, conn.transaction():
        status = await conn.fetchval(
            """
            UPDATE transactions SET status = 'released', updated_at = now()
            WHERE id = $1 AND status = 'held'
            RETURNING status
            """,
            req.txn_id,
        )
        if status is None:
            current = await conn.fetchval(
                "SELECT status FROM transactions WHERE id = $1", req.txn_id
            )
            if current is None:
                raise HTTPException(404, "no such transaction")
            raise HTTPException(409, f"transaction is {current}, not held")

        result = {"txn_id": str(req.txn_id), "status": status}
        await _audit(conn, req.call_id, "release_hold", {"txn_id": str(req.txn_id)}, result)
    return result


class BlockCard(BaseModel):
    card_id: UUID
    call_id: UUID | None = None


@router.post("/block_card_and_reissue")
async def block_card_and_reissue(req: BlockCard) -> dict[str, Any]:
    """The caller denied the charge: kill the card and order a replacement.

    Also blocks any transaction still held on that card. BRIEF §4 ends with the
    dashboard showing the transaction blocked *and* the card reissued, and the
    agent has one tool call to get there — so the held transaction moves with
    the card rather than needing a second, ungated call to `release_hold`'s twin.
    """
    async with db.pool().acquire() as conn, conn.transaction():
        card = await conn.fetchrow(
            """
            UPDATE cards SET status = 'blocked', reissued_at = now()
            WHERE id = $1
            RETURNING status, reissued_at
            """,
            req.card_id,
        )
        if card is None:
            raise HTTPException(404, "no such card")

        blocked = await conn.fetch(
            """
            UPDATE transactions SET status = 'blocked', updated_at = now()
            WHERE card_id = $1 AND status = 'held'
            RETURNING id
            """,
            req.card_id,
        )

        result = {
            "card_id": str(req.card_id),
            "card_status": card["status"],
            "reissued_at": card["reissued_at"],
            "transactions_blocked": [str(r["id"]) for r in blocked],
        }
        await _audit(
            conn, req.call_id, "block_card_and_reissue", {"card_id": str(req.card_id)}, result
        )
    return result


class Escalate(BaseModel):
    call_id: UUID
    reason: str


@router.post("/escalate_to_analyst")
async def escalate_to_analyst(req: Escalate) -> dict[str, Any]:
    """Hand off to a human and stop.

    There is no tickets table in the schema, and this does not add one: the
    `audit_log` row *is* the ticket, carrying the call it came from and the
    reason. If analysts ever get a queue of their own, it reads from here.
    """
    async with db.pool().acquire() as conn, conn.transaction():
        exists = await conn.fetchval("SELECT 1 FROM calls WHERE call_id = $1", req.call_id)
        if exists:
            await conn.execute(
                "UPDATE calls SET outcome = 'escalated', updated_at = now() WHERE call_id = $1",
                req.call_id,
            )

        result = {"escalated": True, "call_id": str(req.call_id), "call_row_updated": bool(exists)}
        await _audit(
            conn,
            req.call_id if exists else None,
            "escalate_to_analyst",
            {"call_id": str(req.call_id), "reason": req.reason},
            result,
        )
    return result
