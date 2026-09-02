"""PLAN 0.5 — serialize, parse, compare equal, for each of the seven events.

The round trip is the point: these models are written by one service and read
by another, always through JSON on a Redis stream or channel. A field that does
not survive the trip is a bug that would otherwise surface as a dropped call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from sentinel_contracts import (
    CHANNEL_RING,
    EVENTS_BY_NAME,
    RING_TIMEOUT_S,
    STREAM_FRAUD_ALERT,
    Event,
    FraudAlert,
    Ring,
    SandboxBusy,
    SessionCancel,
    SessionCreate,
    SessionReady,
    SessionReadyNotice,
)

CALL_ID = UUID("11111111-1111-1111-1111-111111111111")
ALERT_ID = UUID("22222222-2222-2222-2222-222222222222")
TXN_ID = UUID("33333333-3333-3333-3333-333333333333")
CUSTOMER_ID = UUID("44444444-4444-4444-4444-444444444444")
WHEN = datetime(2026, 9, 1, 22, 30, 0, tzinfo=UTC)

SAMPLES: list[Event] = [
    FraudAlert(
        alert_id=ALERT_ID,
        txn_id=TXN_ID,
        customer_id=CUSTOMER_ID,
        risk_reasons=("foreign_merchant", "amount_over_threshold"),
        emitted_at=WHEN,
    ),
    SessionCreate(
        call_id=CALL_ID,
        alert_id=ALERT_ID,
        customer_id=CUSTOMER_ID,
        channel="browser",
        created_at=WHEN,
    ),
    SessionReady(
        call_id=CALL_ID,
        session_url="https://agent.local/rtc/abc",
        token="single-use-token",
        expires_at=WHEN,
    ),
    SessionCancel(call_id=CALL_ID, reason="ring_timeout"),
    Ring(call_id=CALL_ID, alert_id=ALERT_ID),
    SessionReadyNotice(
        call_id=CALL_ID,
        session_url="https://agent.local/rtc/abc",
        token="single-use-token",
    ),
    SandboxBusy(alert_id=ALERT_ID, retry_after_s=60),
]


@pytest.mark.parametrize("event", SAMPLES, ids=lambda e: type(e).__name__)
def test_json_round_trip(event: Event) -> None:
    parsed = type(event).model_validate_json(event.model_dump_json())
    assert parsed == event


@pytest.mark.parametrize("event", SAMPLES, ids=lambda e: type(e).__name__)
def test_dict_round_trip(event: Event) -> None:
    parsed = type(event).model_validate(event.model_dump())
    assert parsed == event


def test_every_contract_is_covered() -> None:
    """All seven, and no accidental eighth."""
    assert {type(e) for e in SAMPLES} == set(EVENTS_BY_NAME.values())
    assert len(EVENTS_BY_NAME) == 7


@pytest.mark.parametrize("event", SAMPLES, ids=lambda e: type(e).__name__)
def test_unknown_fields_are_rejected(event: Event) -> None:
    payload = event.model_dump()
    payload["surprise"] = "value"
    with pytest.raises(ValidationError):
        type(event).model_validate(payload)


def test_events_are_frozen() -> None:
    ring = Ring(call_id=CALL_ID, alert_id=ALERT_ID)
    with pytest.raises(ValidationError):
        ring.call_id = ALERT_ID


def test_ring_defaults_to_the_ring_timeout() -> None:
    assert Ring(call_id=CALL_ID, alert_id=ALERT_ID).ring_timeout_s == RING_TIMEOUT_S == 30


def test_names_map_to_contracts() -> None:
    assert EVENTS_BY_NAME[STREAM_FRAUD_ALERT] is FraudAlert
    assert EVENTS_BY_NAME[CHANNEL_RING] is Ring
