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

**Not measured.** Anthropic calls are off by instruction (PROGRESS B10), so the
judge round-trip and the holding-line decision that depends on it are open. The
escalation policy below is committed as config regardless, because it is a
design decision rather than a measurement.

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

- Judge round-trip p50/p95 — needs the Anthropic call (B10).
- Whether a holding line ("one moment while I confirm that") is needed to cover
  it. Undecidable until the round-trip is measured: at 257 ms p50 for the fast
  path, a two-second judge would be plainly audible, and a 400 ms one would not.
