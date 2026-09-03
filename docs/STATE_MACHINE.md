# State machine placement and the structured turn

PLAN 2.7. Closes the BRIEF §10 question *"where the state machine object lives
inside the Pipecat pipeline, and the exact structured-output schema"*. The
schema itself is [`sentinel_contracts.pathway`](../contracts/sentinel_contracts/pathway.py).

## Why this exists, concretely

2.5 drove both happy paths. On the deny path, after verification passed and
**before calling any tool**, the agent told the cardholder:

> It was a purchase of thirty-nine dollars at a merchant called Green Grove
> Grocery on March twenty-second at two-four p.m. in Springfield.

The real transaction is $940 at Lisboa Eletrónica in Lisbon. The system prompt
already forbade inventing transactions in as many words; the tool description
already said to call `lookup_transaction` before presenting anything. Both were
ignored, and the caller denied a charge that had been described to them wrongly.

The prompt was not weak. It was explicit, and explicit was not enough. That is
the whole argument for what follows.

## Where it sits

```
transport.input() → timing → stt → user_aggregator
                                        ↓
                                       llm            ← emits ProposedTurn (JSON)
                                        ↓
                                  PathwayValidator    ← accepts or rejects
                                        ↓
                                       tts            ← only ever sees accepted text
                                        ↓
                              transport.output() → assistant_aggregator
```

**Between the LLM and the TTS.** That position is the design, not an
implementation detail: it is the last point at which nothing has reached the
caller's ears and no tool has run. A validator anywhere downstream of the TTS
audits a sentence that has already been spoken, which for the Green Grove
failure would have been no help at all.

The validator holds the current `PathwayState` and the call's `verified` flag
for the life of one call. It is an ordinary `FrameProcessor`, so it has no
special access and needs none.

## What the model returns

Every turn, as structured output — one schema shared by the fast model and the
judge, so the validator cannot tell them apart:

```python
ProposedTurn(reply_text=..., proposed_state=..., tool_call=None)
```

Everything in it is a *proposal*. `reply_text` is not spoken and `tool_call` is
not run until `proposed_state` has been accepted.

## What the validator checks

In order, cheapest first. Any failure rejects the whole turn.

1. **Is the edge legal?** `proposed_state` must be in
   `LEGAL_TRANSITIONS[current]`. Self-edges are legal — a clarifying question
   leaves the conversation where it was.
2. **Does it need verification it does not have?** `ACTION_RELEASE` and
   `ACTION_BLOCK` are in `REQUIRES_VERIFIED`, checked separately from the
   transition table so a legal-looking edge cannot smuggle an irreversible
   action past an unverified caller. This is the property PLAN 5.1 tests.
3. **Is the tool allowed here?** `tool_call.name` must be in
   `TOOLS_BY_STATE[proposed_state]`. `release_hold` exists only in
   `action_release`; `lookup_transaction` only from `present_transaction`
   onward — which is what stops a transaction being described before it has been
   read.
4. **Has verification run out of attempts?** More than `MAX_VERIFY_ATTEMPTS`
   failures forces `escalate`, regardless of what was proposed.

On rejection the turn escalates to the judge **once** (3.11), and the judge's
verdict is re-validated by these same four checks. A second rejection lands in
`escalate_to_analyst`. The judge can propose; it can never authorise.

## What this does *not* do

It does not make the model truthful. It makes an untruthful model unable to act
on, or say, the thing it was untruthful about — the Green Grove sentence is a
`present_transaction` reply proposed from `verify_identity`, so it never reaches
the TTS. Reducing hallucination is a model and prompt question; containing it is
this.

It also does not police prose. A reply that is accurate but rambling is the
persona's problem, not the validator's.

## Consequences accepted

- **A rejected turn costs latency.** The caller waits through a validator
  rejection plus a judge round-trip. 2.4 measures it and decides whether a
  holding line is needed.
- **The state machine can deadlock a confused model.** If the model keeps
  proposing illegal edges, the call ends in `escalate` rather than going in
  circles. That is the intended failure: a human gets it.
- **Every legal path must actually be listed.** A transition the script needs
  but the table omits reads as a model failure and escalates. The unit tests in
  3.1 walk every edge in both directions for exactly this reason.

## Where it lands

`PathwayValidator` and its tests are PLAN 3.1; binding tools to state on the
`core-api` side, where it cannot be prompted away, is 3.2; the judge is 3.11.
