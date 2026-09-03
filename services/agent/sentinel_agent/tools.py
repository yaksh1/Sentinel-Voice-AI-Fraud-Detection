"""The tools the model may call, as thin clients over `core-api` (PLAN 2.5).

Nothing here touches the database. Every effect goes through `core-api`, which
is what makes `audit_log` complete: one writer, one place a row can be missed.

**These are not guards.** A schema tells the model a tool exists; it does not
stop the model calling it at the wrong moment. `release_hold` here will release
a hold whenever the model asks. Binding each tool to a call state — and making
`action_*` unreachable without a passed `verify_identity` — is PLAN 3.2, and it
belongs on the `core-api` side where it cannot be prompted away.

The seeded identifiers below are scaffolding. From 3.6 the orchestrator mints a
`call_id` and hands the agent a real alert, and these constants go.
"""

import os
from typing import Any

import httpx
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

CORE_API_URL = os.getenv("CORE_API_URL", "http://127.0.0.1:8000")

# db/seed.sql — Alex Rivera, $940 at Lisboa Eletrónica, held, alert open.
SEED_ALERT_ID = "00000000-0000-0000-0000-000000000004"
SEED_CUSTOMER_ID = "00000000-0000-0000-0000-000000000001"

_TIMEOUT = httpx.Timeout(10.0)


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Call core-api and return either its JSON or a shape the model can act on.

    A failed tool call must not read as a successful one, and must not end the
    call: the model is told plainly that the step did not happen so it can say
    so out loud rather than inventing an outcome.
    """
    try:
        async with httpx.AsyncClient(base_url=CORE_API_URL, timeout=_TIMEOUT) as client:
            response = await client.post(path, json=payload)
        if response.status_code >= 400:
            logger.warning("tool {} failed: {} {}", path, response.status_code, response.text)
            return {"ok": False, "error": response.json().get("detail", response.text)}
        return {"ok": True, **response.json()}
    except httpx.HTTPError as exc:
        logger.error("tool {} unreachable: {}", path, exc)
        return {"ok": False, "error": "the banking system did not respond"}


async def _verify_challenge(params: FunctionCallParams) -> None:
    result = await _post(
        "/tools/verify_challenge",
        {
            "customer_id": SEED_CUSTOMER_ID,
            "last4": str(params.arguments.get("last4", "")),
            "answer": str(params.arguments.get("city_of_birth", "")),
        },
    )
    logger.info("tool verify_challenge -> {}", result)
    await params.result_callback(result)


async def _lookup_transaction(params: FunctionCallParams) -> None:
    result = await _post("/tools/lookup_transaction", {"alert_id": SEED_ALERT_ID})
    logger.info("tool lookup_transaction -> {}", result)
    await params.result_callback(result)


async def _release_hold(params: FunctionCallParams) -> None:
    result = await _post("/tools/release_hold", {"txn_id": params.arguments["txn_id"]})
    logger.info("tool release_hold -> {}", result)
    await params.result_callback(result)


async def _block_card_and_reissue(params: FunctionCallParams) -> None:
    result = await _post("/tools/block_card_and_reissue", {"card_id": params.arguments["card_id"]})
    logger.info("tool block_card_and_reissue -> {}", result)
    await params.result_callback(result)


async def _escalate_to_analyst(params: FunctionCallParams) -> None:
    result = await _post(
        "/tools/escalate_to_analyst",
        {
            "call_id": params.arguments.get("call_id", SEED_ALERT_ID),
            "reason": str(params.arguments.get("reason", "unspecified")),
        },
    )
    logger.info("tool escalate_to_analyst -> {}", result)
    await params.result_callback(result)


TOOLS = [
    FunctionSchema(
        name="verify_challenge",
        description=(
            "Check the caller's identity against the bank's records. Call this once "
            "the caller has given both the last four digits of their card and their "
            "city of birth. Returns whether they passed."
        ),
        properties={
            "last4": {"type": "string", "description": "The last four digits of the card."},
            "city_of_birth": {"type": "string", "description": "The city the caller was born in."},
        },
        required=["last4", "city_of_birth"],
        handler=_verify_challenge,
    ),
    FunctionSchema(
        name="lookup_transaction",
        description=(
            "Fetch the flagged transaction: merchant, amount, city and time, plus the "
            "txn_id and card_id needed to act on it. Call this only after the caller "
            "has passed verification. Read amount_display back to the caller exactly "
            "as given; never convert it yourself."
        ),
        properties={},
        required=[],
        handler=_lookup_transaction,
    ),
    FunctionSchema(
        name="release_hold",
        description=(
            "The caller confirmed they made the charge. Releases the hold so the "
            "payment goes through. Use the txn_id from lookup_transaction."
        ),
        properties={"txn_id": {"type": "string", "description": "From lookup_transaction."}},
        required=["txn_id"],
        handler=_release_hold,
    ),
    FunctionSchema(
        name="block_card_and_reissue",
        description=(
            "The caller denied making the charge. Blocks the card, orders a "
            "replacement, and blocks the held transaction. Use the card_id from "
            "lookup_transaction."
        ),
        properties={"card_id": {"type": "string", "description": "From lookup_transaction."}},
        required=["card_id"],
        handler=_block_card_and_reissue,
    ),
    FunctionSchema(
        name="escalate_to_analyst",
        description=(
            "Hand the call to a human analyst. Use this when verification has failed "
            "twice, or the caller asks for a person, or you cannot safely continue."
        ),
        properties={"reason": {"type": "string", "description": "Why you are escalating."}},
        required=["reason"],
        handler=_escalate_to_analyst,
    ),
]
