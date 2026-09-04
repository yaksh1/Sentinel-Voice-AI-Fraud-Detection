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

# One client for the process, not one per call. Building an AsyncClient inside
# `_post` made every tool pay a fresh TCP and TLS handshake to core-api; the
# measured round trip for verify_challenge was 1.24 s for what is one indexed
# row. Keeping the pool alive is most of that back.
_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    """The shared client, created on first use."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=CORE_API_URL, timeout=_TIMEOUT)
    return _client


async def close_client() -> None:
    """Release the connection pool. Called from the app lifespan."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Call core-api and return either its JSON or a shape the model can act on.

    A failed tool call must not read as a successful one, and must not end the
    call: the model is told plainly that the step did not happen so it can say
    so out loud rather than inventing an outcome.
    """
    try:
        response = await client().post(path, json=payload)
        if response.status_code >= 400:
            logger.warning("tool {} failed: {} {}", path, response.status_code, response.text)
            return {"ok": False, "error": response.json().get("detail", response.text)}
        return {"ok": True, **response.json()}
    except httpx.HTTPError as exc:
        logger.error("tool {} unreachable: {}", path, exc)
        return {"ok": False, "error": "the banking system did not respond"}


# Set by the pipeline for the life of one call, and armed by the terminal tools
# below rather than by the model.
#
# There was an `end_call` tool here. It was removed twice over: the model would
# not call it when told to — it said "you may hang up" and left the line open —
# and when it did reach for it, it emitted the arguments as *speech*, so the
# caller heard `{ "reason": "completed_release" }` read out before the goodbye.
# A tool the model misuses and does not need is pure downside.
_hangup: Any = None


def set_hangup(hangup: Any) -> None:
    """Give the tools the current call's hang-up latch."""
    global _hangup
    _hangup = hangup


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


def _arm_if_final(result: dict[str, Any]) -> None:
    """Hang up after a tool that ends the call, without asking the model to.

    `end_call` exists and the model is told to use it, and in testing it did not:
    it said "you may hang up" and left the line open. Every instruction this
    project has tried to enforce by prompt has eventually been ignored, so the
    terminal tools arm the hang-up themselves. Releasing, blocking and escalating
    are the three ways a call ends; after any of them the agent says its closing
    line and the line drops when it stops speaking.
    """
    if result.get("ok") and _hangup is not None:
        _hangup.arm()


async def _release_hold(params: FunctionCallParams) -> None:
    result = await _post("/tools/release_hold", {"txn_id": params.arguments["txn_id"]})
    logger.info("tool release_hold -> {}", result)
    _arm_if_final(result)
    await params.result_callback(result)


async def _block_card_and_reissue(params: FunctionCallParams) -> None:
    result = await _post("/tools/block_card_and_reissue", {"card_id": params.arguments["card_id"]})
    logger.info("tool block_card_and_reissue -> {}", result)
    _arm_if_final(result)
    await params.result_callback(result)


async def reset_demo() -> None:
    """Put the seeded rows back so the next call starts from the same place."""
    result = await _post("/internal/demo/reset", {})
    logger.info("demo reset -> {}", result)


async def _escalate_to_analyst(params: FunctionCallParams) -> None:
    result = await _post(
        "/tools/escalate_to_analyst",
        {
            "call_id": params.arguments.get("call_id", SEED_ALERT_ID),
            "reason": str(params.arguments.get("reason", "unspecified")),
        },
    )
    logger.info("tool escalate_to_analyst -> {}", result)
    _arm_if_final(result)
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
