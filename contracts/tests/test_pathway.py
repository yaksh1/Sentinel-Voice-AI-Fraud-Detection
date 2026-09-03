"""The pathway schema and transition table (PLAN 2.7).

The validator itself is 3.1. These tests pin the *table* it will read, so a
later edit that quietly widens what is reachable fails here first.
"""

import pytest
from pydantic import ValidationError

from sentinel_contracts.pathway import (
    LEGAL_TRANSITIONS,
    MAX_VERIFY_ATTEMPTS,
    REQUIRES_VERIFIED,
    TOOLS_BY_STATE,
    PathwayState,
    ProposedTurn,
    ToolCall,
    TurnVerdict,
)

TOOL_NAMES = {
    "verify_challenge",
    "lookup_transaction",
    "release_hold",
    "block_card_and_reissue",
    "escalate_to_analyst",
}


def test_every_state_has_a_transition_entry():
    assert set(LEGAL_TRANSITIONS) == set(PathwayState)


def test_close_is_terminal():
    assert LEGAL_TRANSITIONS[PathwayState.CLOSE] == frozenset()


def test_every_state_is_reachable_from_consent():
    seen, queue = {PathwayState.CONSENT}, [PathwayState.CONSENT]
    while queue:
        for nxt in LEGAL_TRANSITIONS[queue.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    assert seen == set(PathwayState)


def test_every_path_can_reach_close():
    """No state should be able to strand a call."""
    for start in PathwayState:
        seen, queue = {start}, [start]
        while queue:
            for nxt in LEGAL_TRANSITIONS[queue.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        assert PathwayState.CLOSE in seen, f"{start} cannot reach close"


@pytest.mark.parametrize("action", sorted(REQUIRES_VERIFIED))
def test_irreversible_actions_are_unreachable_from_consent_and_verify(action):
    """The BRIEF §5 rule: no action_* without a passed verify_identity."""
    for state in (PathwayState.CONSENT, PathwayState.VERIFY_IDENTITY):
        assert action not in LEGAL_TRANSITIONS[state]


def test_requires_verified_is_exactly_the_two_irreversible_actions():
    assert {PathwayState.ACTION_RELEASE, PathwayState.ACTION_BLOCK} == REQUIRES_VERIFIED


def test_tools_are_bound_to_states_that_exist():
    assert set(TOOLS_BY_STATE) <= set(PathwayState)
    for tools in TOOLS_BY_STATE.values():
        assert tools <= TOOL_NAMES


@pytest.mark.parametrize(
    ("tool", "state"),
    [
        ("release_hold", PathwayState.ACTION_RELEASE),
        ("block_card_and_reissue", PathwayState.ACTION_BLOCK),
        ("verify_challenge", PathwayState.VERIFY_IDENTITY),
    ],
)
def test_each_irreversible_tool_lives_in_exactly_one_state(tool, state):
    holders = {s for s, tools in TOOLS_BY_STATE.items() if tool in tools}
    assert holders == {state}


def test_consent_permits_no_tools():
    assert TOOLS_BY_STATE.get(PathwayState.CONSENT, frozenset()) == frozenset()


def test_proposed_turn_round_trips():
    turn = ProposedTurn(
        reply_text="Could you confirm the last four digits?",
        proposed_state=PathwayState.VERIFY_IDENTITY,
        tool_call=ToolCall(name="verify_challenge", arguments={"last4": "4242"}),
    )
    assert ProposedTurn.model_validate_json(turn.model_dump_json()) == turn


def test_proposed_turn_tool_call_is_optional():
    turn = ProposedTurn(reply_text="One moment.", proposed_state=PathwayState.DECISION)
    assert turn.tool_call is None


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        ProposedTurn(
            reply_text="hi",
            proposed_state=PathwayState.CONSENT,
            confidence=0.9,  # not in the schema
        )


def test_unknown_state_is_rejected():
    with pytest.raises(ValidationError):
        ProposedTurn(reply_text="hi", proposed_state="action_refund")


def test_turn_verdict_round_trips():
    verdict = TurnVerdict(accepted=False, state=PathwayState.VERIFY_IDENTITY, reason="illegal edge")
    assert TurnVerdict.model_validate_json(verdict.model_dump_json()) == verdict


def test_verify_attempts_cap_matches_the_brief():
    assert MAX_VERIFY_ATTEMPTS == 2
