"""The conversation pathway and the structured turn (PLAN 2.7).

One schema, shared by the fast model and the judge, so the validator is
indifferent to which produced a turn (BRIEF §5 *Model stack*). The judge can
propose a transition; it can never authorise one.

See docs/STATE_MACHINE.md for where this sits in the pipeline and why.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PathwayState(StrEnum):
    """The conversation pathway from BRIEF §5. Not `calls.state`, which tracks
    the *call* (ringing, connected, completed); this tracks the conversation
    inside a connected call."""

    CONSENT = "consent"
    VERIFY_IDENTITY = "verify_identity"
    PRESENT_TRANSACTION = "present_transaction"
    DECISION = "decision"
    ACTION_RELEASE = "action_release"
    ACTION_BLOCK = "action_block"
    ESCALATE = "escalate"
    CLOSE = "close"


#: Legal transitions. Anything not listed is rejected by the validator — the
#: table is the authority, not the prompt. Self-edges are the "stay put and keep
#: talking" case: a clarifying question does not move the conversation.
LEGAL_TRANSITIONS: dict[PathwayState, frozenset[PathwayState]] = {
    PathwayState.CONSENT: frozenset({PathwayState.CONSENT, PathwayState.VERIFY_IDENTITY}),
    PathwayState.VERIFY_IDENTITY: frozenset(
        {PathwayState.VERIFY_IDENTITY, PathwayState.PRESENT_TRANSACTION, PathwayState.ESCALATE}
    ),
    PathwayState.PRESENT_TRANSACTION: frozenset(
        {PathwayState.PRESENT_TRANSACTION, PathwayState.DECISION, PathwayState.ESCALATE}
    ),
    PathwayState.DECISION: frozenset(
        {
            PathwayState.DECISION,
            PathwayState.PRESENT_TRANSACTION,  # clarifying question, back a step
            PathwayState.ACTION_RELEASE,
            PathwayState.ACTION_BLOCK,
            PathwayState.ESCALATE,
        }
    ),
    PathwayState.ACTION_RELEASE: frozenset({PathwayState.CLOSE}),
    PathwayState.ACTION_BLOCK: frozenset({PathwayState.CLOSE}),
    PathwayState.ESCALATE: frozenset({PathwayState.CLOSE}),
    PathwayState.CLOSE: frozenset(),
}

#: States that may not be entered unless the call is already verified. This is
#: the property PLAN 5.1 tests, and it is enforced separately from
#: LEGAL_TRANSITIONS so that a legal-looking edge cannot smuggle an irreversible
#: action past an unverified caller.
REQUIRES_VERIFIED: frozenset[PathwayState] = frozenset(
    {PathwayState.ACTION_RELEASE, PathwayState.ACTION_BLOCK}
)

#: Which tool may be called in which state. A tool absent from this map is
#: callable nowhere; a state absent from it permits no tools at all.
TOOLS_BY_STATE: dict[PathwayState, frozenset[str]] = {
    PathwayState.VERIFY_IDENTITY: frozenset({"verify_challenge", "escalate_to_analyst"}),
    PathwayState.PRESENT_TRANSACTION: frozenset({"lookup_transaction", "escalate_to_analyst"}),
    PathwayState.DECISION: frozenset({"lookup_transaction", "escalate_to_analyst"}),
    PathwayState.ACTION_RELEASE: frozenset({"release_hold"}),
    PathwayState.ACTION_BLOCK: frozenset({"block_card_and_reissue"}),
    PathwayState.ESCALATE: frozenset({"escalate_to_analyst"}),
}

#: Retry cap for identity verification (BRIEF §5). A third failure escalates.
MAX_VERIFY_ATTEMPTS = 2


class ToolCall(BaseModel):
    """A tool the model wants run, before it is known to be allowed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    arguments: dict[str, str] = Field(default_factory=dict)


class ProposedTurn(BaseModel):
    """What the model returns each turn: what to say, where to go, what to run.

    Every field is a *proposal*. `reply_text` is not spoken and `tool_call` is
    not run until the validator has accepted `proposed_state` — which is the
    whole point, and the reason this is a schema rather than a prompt
    instruction. See docs/STATE_MACHINE.md.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reply_text: str = Field(description="What to say to the caller. Spoken aloud, so no markup.")
    proposed_state: PathwayState = Field(description="The state this turn should move to.")
    tool_call: ToolCall | None = Field(default=None, description="A tool to run, if any.")


class TurnVerdict(BaseModel):
    """The validator's answer. `accepted` is the only thing the pipeline trusts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    state: PathwayState = Field(description="Where the call actually is after this turn.")
    reason: str | None = Field(default=None, description="Why a proposal was rejected.")
