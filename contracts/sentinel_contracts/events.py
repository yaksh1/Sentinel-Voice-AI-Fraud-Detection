"""The seven events that cross a service boundary in Sentinel.

Source of truth: BRIEF §5 event contracts, ARCHITECTURE §4. One package,
imported by every service, so a contract change breaks a build instead of a
call.

Four travel on Redis streams (durable, consumer groups, redelivered after a
crash); three on pub/sub (fire-and-forget fan-out to whichever core-api
instance holds the visitor's SSE). The stream/channel constants live here too,
so no service spells a name itself.

Every model is frozen and rejects unknown fields: an event that gained a key in
one service and not another should fail at the boundary, loudly, rather than be
silently dropped on parse.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# --- Streams: durable work queues ------------------------------------------
STREAM_FRAUD_ALERT = "fraud.alert"
STREAM_SESSION_CREATE = "session.create"
STREAM_SESSION_READY = "session.ready"
STREAM_SESSION_CANCEL = "session.cancel"

# --- Pub/sub: fan-out to the visitor's SSE ---------------------------------
CHANNEL_RING = "ring"
CHANNEL_SESSION_READY = "session_ready"
CHANNEL_SANDBOX_BUSY = "sandbox_busy"

#: Ring timer, in seconds. The WebRTC token expires with it.
RING_TIMEOUT_S = 30

Channel = Literal["browser", "phone", "text"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Event(BaseModel):
    """Base for every contract: strict on input, immutable once parsed."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FraudAlert(Event):
    """`fraud.alert` — risk-engine to call-orchestrator.

    `alert_id` is the idempotency key: the orchestrator `SET NX`s on it before
    dialing, so a redelivered entry cannot produce a second call.
    """

    alert_id: UUID
    txn_id: UUID
    customer_id: UUID
    risk_reasons: tuple[str, ...] = ()
    emitted_at: datetime = Field(default_factory=_utcnow)


class SessionCreate(Event):
    """`session.create` — orchestrator to agent. Request for a warm pipeline.

    Left unacked while the agent is at capacity; that backlog is the
    backpressure signal (`session_create_stream_lag`).
    """

    call_id: UUID
    alert_id: UUID
    customer_id: UUID
    channel: Channel = "browser"
    created_at: datetime = Field(default_factory=_utcnow)


class SessionReady(Event):
    """`session.ready` — agent to orchestrator.

    `token` is single-use and bound to `call_id`; the agent rejects anything
    else on connect, which closes the join-someone-elses-call path.
    """

    call_id: UUID
    session_url: str
    token: str
    expires_at: datetime


class SessionCancel(Event):
    """`session.cancel` — orchestrator to agent.

    Sent when the visitor declined or the ring timer expired, so the agent
    releases the pre-warmed pipeline instead of holding a slot until timeout.
    """

    call_id: UUID
    reason: str


class Ring(Event):
    """`ring` (pub/sub) — orchestrator, via core-api, to the browser.

    `alert_to_ring_ms` is stamped at publish, which is why this carries no
    pipeline state: the ring does not wait on pre-warm.
    """

    call_id: UUID
    alert_id: UUID
    ring_timeout_s: int = RING_TIMEOUT_S


class SessionReadyNotice(Event):
    """`session_ready` (pub/sub) — the browser-facing subset of `SessionReady`.

    Deliberately narrower than the stream event: the browser needs somewhere to
    connect and a token, not the expiry the orchestrator reasons about.
    """

    call_id: UUID
    session_url: str
    token: str


class SandboxBusy(Event):
    """`sandbox_busy` (pub/sub) — capacity check failed; no call was placed.

    Carries `alert_id` rather than `call_id` because no `call_id` was ever
    minted: the visitor sees "sandbox busy" instead of a ring.
    """

    alert_id: UUID
    retry_after_s: int


#: Every contract, keyed by the stream or channel it travels on.
EVENTS_BY_NAME: dict[str, type[Event]] = {
    STREAM_FRAUD_ALERT: FraudAlert,
    STREAM_SESSION_CREATE: SessionCreate,
    STREAM_SESSION_READY: SessionReady,
    STREAM_SESSION_CANCEL: SessionCancel,
    CHANNEL_RING: Ring,
    CHANNEL_SESSION_READY: SessionReadyNotice,
    CHANNEL_SANDBOX_BUSY: SandboxBusy,
}
