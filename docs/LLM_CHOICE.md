# Model calibration

PLAN 2.4. Measurements, not estimates. Re-run with
`scratchpad/calibrate.py` (see PROGRESS for the harness).

## Turn loop — Cerebras `gpt-oss-120b`

Each stage of a happy path replayed straight at the model with the real system
prompt and the real tool schemas, six trials each, temperature 0.3. STT and TTS
are deliberately out of the loop, so this is `llm_ms` and nothing else.

| Stage | Correct tool | Correct | p50 | p95 |
|---|---|---|---|---|
| `after_consent` | *(no tool — just talk)* | 6/6 | 222 ms | 376 ms |
| `caller_gave_factors` | `verify_challenge` | 6/6 | 262 ms | 302 ms |
| `just_verified` | `lookup_transaction` | 5/6 | 294 ms | 392 ms |
| `caller_denied` | `block_card_and_reissue` | 6/6 | 243 ms | 403 ms |
| **overall** | | **23/24** | **257 ms** | **392 ms** |

**Latency is not the problem.** [ARCHITECTURE](ARCHITECTURE.md) budgets ~400 ms
p50 for `llm`; the measured p50 is 257 ms and even p95 lands at 392 ms, inside
the p50 allowance. The 0.94 s figure recorded during 2.2 was a first-call
measurement dominated by connection setup, not inference — corrected here.

**Tool discipline is the problem, and it is narrow.** The single failure in 24
is at `just_verified`: the model talks about the transaction instead of calling
`lookup_transaction` first. That is the same failure 2.5 caught in a live call,
where it invented a $39 charge at a merchant that does not exist. Roughly 1 in 6
at the one step where being wrong means reading fabricated financial details to
a cardholder.

**One scary number that was not real.** An earlier run scored `caller_denied`
**0/6** and looked like the model refusing to act on a denial. It was the
fixture: the conversation had been assembled without a verification step, and
the model was correctly declining to block a card for an unverified caller.
Fixing the fixture took it to 6/6. Worth recording because the wrong reading of
that number — "the model will not use the block tool" — would have sent 3.1 off
in entirely the wrong direction.

### What this means for 3.1

The validator is not there to make the model faster or more truthful. It is
there for that 1-in-6: a `present_transaction` reply proposed while the pathway
is still in `verify_identity` is rejected before the TTS ever sees it. See
[STATE_MACHINE.md](STATE_MACHINE.md).

## Judge — Claude Sonnet 5

Authorised 2026-09-03. Eight escalations per config, structured output against
the shared `ProposedTurn` schema, on the real 2.5 failure: a
`present_transaction` reply proposed from `verify_identity` with fabricated
transaction details.

| Judge config | Legal verdict | p50 | p95 |
|---|---|---|---|
| thinking off, effort low | 8/8 | 1791 ms | 2961 ms |
| **adaptive thinking, effort low** | **8/8** | **1811 ms** | **4869 ms** |

**It corrects the right thing.** Against the rejected turn —

> It was a purchase of thirty-nine dollars at a merchant called Green Grove
> Grocery on March twenty-second at two-four p.m. in Springfield.

— the judge returns `proposed_state: verify_identity`, `tool_call:
verify_challenge`, and *"Thank you, let me verify that information now."* It
stays where the pathway actually is, reaches for the tool that was skipped, and
invents nothing. Every one of 16 verdicts was a legal transition.

**Config: adaptive thinking, effort low.** The thinking-off tail is better
(2.96 s vs 4.87 s p95) and both scored 8/8, but eight samples on one scenario is
not enough to trade a verifier's reasoning for 1.9 s of tail. Correctness is the
judge's only job; the tail is covered below.

**`JUDGE_TIMEOUT_S` raised 4.0 → 6.0.** The 4 s ceiling was a guess made before
measuring, and p95 is 4.87 s — it would have failed closed on roughly one
escalation in twenty out of nothing but impatience, and failing closed hands a
live caller to a human.

### Holding line: required

| | p50 |
|---|---|
| Normal turn (`stt` + `llm` + `tts` + network) | ~990 ms |
| Escalated turn (+ judge) | ~2.8 s |

[ARCHITECTURE](ARCHITECTURE.md) budgets < 1200 ms p50 voice-to-voice. An
escalation is **2.3× over**, and at p95 approaches six seconds. Silence that long
mid-call reads as a dropped line, and the caller starts saying "hello?" — which
VAD then treats as a new turn, on top of an escalation already in flight.

`JUDGE_HOLDING_LINE` — *"One moment while I confirm that."* — is committed to
config and spoken when an escalation starts. It is deliberately not generated:
the model that just produced a rejected turn is not the thing to ask for a
stalling phrase, and 2.2 already settled that lines which must always appear are
constants.

## Escalation policy (committed)

In [`sentinel_contracts.pathway`](../contracts/sentinel_contracts/pathway.py),
as data:

| Setting | Value | Why |
|---|---|---|
| Trigger: validator rejection | on | Re-prompting the model that just broke a rule is asking the same question twice |
| Trigger: proposed `action_release` / `action_block` | on | The two irreversible outcomes |
| `MAX_ESCALATIONS_PER_TURN` | 1 | A second rejection goes to `escalate_to_analyst`, not a third opinion |
| `JUDGE_TIMEOUT_S` | 4.0 | Fail **closed**: a timeout or 429 cannot produce an `action_*` |
| `MAX_VERIFY_ATTEMPTS` | 2 | BRIEF §5 |

## Open

- **Escalation rate in a real call is unmeasured.** Everything above prices one
  escalation; what it costs a *call* depends on how often the validator rejects,
  which cannot be known until 3.1 exists to do the rejecting. If it is common,
  the 1-in-6 tool-discipline failure becomes a latency problem as well as a
  correctness one, and the answer is a better fast-model prompt rather than a
  faster judge.
- Both judge configs scored 8/8 on **one** scenario. Before 3.11 ships, run the
  same harness over a rejected `action_*` proposal and a second-rejection case.
