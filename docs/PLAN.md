# PLAN — Meridian Fraud Callback Agent · v1

Derived from `BRIEF.md` (2026-09-01). One person, one weekend. Every task has a *done when* you can check without judgement, and a phase can't start until its *entry gate* is true. P0 = v1 doesn't exist without it; P1 = expected but cuttable; P2 = stretch.

**Cut line if Saturday runs long:** drop P2 first, then P1 in Phase 4, then Phase 2's model calibration (2.4 — ship on `gpt-oss-120b` alone, no judge). Never cut the three tests in Phase 5 — they are the success metrics.

---

## Phase 0 — Bootstrap (Fri evening, ~2 h)

Entry gate: none. Goal: every external dependency reachable from a shell before any product code exists.

| # | Task | Pri | Done when | Depends on |
|---|---|---|---|---|
| 0.1 | Create repo from template via `new-project` skill; monorepo layout `services/{demo-web,risk-engine,call-orchestrator,agent,core-api}` + `docs/` | P0 | `git log` shows one commit; each service dir has a README stub | — |
| 0.2 | Provision keys: Deepgram, Cartesia, Cerebras, Anthropic, Neon project, Twilio trial (park for v1.1) | P0 | `.env.example` lists every var; `.env` has `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, `CEREBRAS_API_KEY`, `ANTHROPIC_API_KEY`, `DATABASE_URL`; `.gitignore` covers `.env` | — |
| 0.3 | Local infra: `docker-compose` with Redis 7 (streams enabled). No local Postgres — Neon branches serve dev/CI (`neon checkout <name>`, auto-expiring TTL) | P0 | `redis-cli XINFO STREAM fraud.alert` errors with "no such key" (server up, stream absent); `psql $DATABASE_URL -c 'select 1'` succeeds | — |
| 0.4 | Apply schema from BRIEF §5 data model to Neon: 8 tables, `calls.state` enum, `state_history` JSONB | P0 | Migration applies cleanly twice (idempotent) on a fresh Neon branch; seed script creates one customer + card | 0.3 |
| 0.5 | Shared `contracts/` package: pydantic models for the 7 events in BRIEF §5 event contracts | P0 | Round-trip test: serialize → parse → equal for each event | 0.1 |
| 0.6 | Health + metrics scaffold: every FastAPI service exposes `/health` and `/metrics` (Prometheus text) | P1 | `curl` each returns 200 | 0.1 |

Risk: vendor sign-ups stall (card verification, waitlists). Mitigation: do 0.2 first, tonight.

---

## Phase 1 — Transport skeleton (Sat AM, ~3 h)

Entry gate: Phase 0 P0 done. Goal: audio in, audio out, numbers on the screen. No AI yet.

| # | Task | Pri | Done when | Depends on |
|---|---|---|---|---|
| 1.1 | `agent`: Pipecat pipeline with SmallWebRTC transport, echo processor (mic → speaker) | P0 | You hear yourself in the browser with < 300 ms delay | 0.1 |
| 1.2 | `demo-web`: minimal page with Pipecat JS client, Connect button, mic permission | P0 | Connect → echo works from Chrome and Safari | 1.1 |
| 1.3 | Per-frame timing: log `net_ms` per audio frame with a `call_id` (hardcoded for now) | P0 | Log lines show `call_id` + frame latency | 1.1 |
| 1.4 | Text transport: same pipeline accepts typed input and returns text (no STT/TTS) | P1 | Type "hello" → echo "hello" through the same pipeline object | 1.1 |
| 1.5 | Decide: text mode reuses `session.create` path (BRIEF open question) | P1 | One-paragraph decision appended to BRIEF §10 | 1.4 |

Risk: WebRTC/STUN issues on hotel or campus Wi-Fi. Mitigation: test on phone hotspot; have the text transport (1.4) as fallback for the demo.

---

## Phase 2 — First conversation (Sat PM, ~5 h)

Entry gate: 1.1–1.3 done. Goal: the full happy path, end to end, with hardcoded alert data. Handshake comes later.

| # | Task | Pri | Done when | Depends on |
|---|---|---|---|---|
| 2.1 | Wire Deepgram Nova STT and Cartesia TTS into the pipeline | P0 | Say "hello" → transcript logged → spoken reply heard | 1.1 |
| 2.2 | Persona system prompt: Meridian Bank Fraud Prevention, consent line, never reads full PAN | P0 | Consent line is the first thing spoken on connect | 2.1 |
| 2.3 | Tools against Neon via `core-api`: `verify_challenge`, `lookup_transaction`, `release_hold`, `block_card_and_reissue`, `escalate_to_analyst`; each writes an `audit_log` row | P0 | Calling each tool from a REPL produces the DB change and an audit row | 0.4 |
| 2.4 | Calibrate the two-tier stack (BRIEF §5 *Model stack*): `gpt-oss-120b` `llm_ms` p50/p95 + tool-call correctness over 10 happy-path runs; judge round-trip when escalation fires; decide whether a holding line is needed to cover it | P1 | Table in `docs/LLM_CHOICE.md`; escalation triggers + thresholds committed to config; holding-line decision appended to BRIEF §10 | 2.1, 2.3 |
| 2.5 | Full happy path in browser (deny + confirm) with a seeded alert | P0 | Both paths reach `close`; DB shows blocked/reissued or released | 2.1–2.3 |
| 2.6 | PAN redaction: regex + Luhn on transcripts and log lines before persistence | P0 | Seeded fake PAN in speech never appears in `turns.text_redacted` or logs | 2.1 |
| 2.7 | Spec: state machine placement in the pipeline + structured-output schema for `{reply_text, proposed_state, tool_call?}` — one schema shared by the fast model and the judge (BRIEF open question) | P0 | Half-page `docs/STATE_MACHINE.md`; schema is a pydantic model in `contracts/` | 2.5 |

Risk: the LLM ignores tool discipline. Mitigation: 2.7 is the answer; don't try to prompt your way out of it.

---

## Phase 3 — State machine + event pipeline + handshake (Sun AM, ~5 h)

Entry gate: 2.5 and 2.7 done. Goal: replace hardcoded alert data with the real event flow from BRIEF §5 handshake.

| # | Task | Pri | Done when | Depends on |
|---|---|---|---|---|
| 3.1 | State machine in code per BRIEF §5 diagram; validator accepts/rejects LLM `proposed_state`; every transition logged with `call_id, from, to, trigger, latency_ms` | P0 | Unit tests: every legal edge passes, every illegal edge is rejected | 2.7 |
| 3.2 | Tool guards bound to state (BRIEF §5 tools table) | P0 | Calling `release_hold` in `verify_identity` is refused and audited | 3.1, 2.3 |
| 3.3 | `risk-engine`: rule evaluation (foreign merchant ∧ amount > threshold) → `XADD fraud.alert` | P0 | POST a txn → stream entry appears with correct `risk_reasons[]` | 0.5 |
| 3.4 | `core-api`: `POST /checkout` writes `held` txn, calls risk-engine | P0 | End-to-end: checkout → stream entry | 3.3 |
| 3.5 | `core-api`: SSE endpoint `GET /events?visitor_id`, `conn:{visitor_id}` in Redis with heartbeat TTL, pub/sub subscriber that fans `ring`/`session_ready`/`sandbox_busy` to the right SSE. Decide heartbeat/TTL (leaning 15 s / 45 s) | P0 | Two browser tabs with different `visitor_id`s each receive only their own events | 0.3 |
| 3.6 | `call-orchestrator`: `XREADGROUP fraud.alert` → `SET NX alert:{id}` → rate limit → `DECR agent:capacity` (INCR back + `sandbox_busy` if < 0) → mint `call_id` → `calls` row `ringing` → 30 s ring timer → parallel `PUBLISH ring` + `XADD session.create` | P0 | Duplicate alert is dropped; 4th concurrent alert gets `sandbox_busy`; timer marks `no_answer` and publishes `session.cancel` | 3.3, 3.5 |
| 3.7 | `agent`: consume `session.create`, warm pool = 1, max = 3, `INCR`/`DECR agent:capacity`, emit `session.ready {session_url, token, expires_at}`, handle `session.cancel` | P0 | Three sessions accepted, fourth left unacked; cancel releases a pre-warmed pipeline | 3.6 |
| 3.8 | Single-use `call_id`-bound WebRTC token; agent validates on connect | P0 | Reused or foreign token is rejected; audit row written | 3.7 |
| 3.9 | `events:{visitor_id}` replay buffer + SSE `Last-Event-ID` | P1 | Kill and reopen SSE mid-ring; `ring` and `session_ready` are replayed | 3.5 |
| 3.10 | `demo-web`: `visitor_id` cookie on load, SSE client, ring UI with Answer/Decline, connect WebRTC on Answer | P0 | Click Pay → ring in < 3 s → Answer → consent line spoken | 3.5–3.8 |
| 3.11 | Judge escalation per BRIEF §5: on validator rejection or a proposed `action_*`, call Claude Sonnet 5 (`claude-sonnet-5`) with transcript + current state + violated rule; verdict is **re-validated**, max one escalation per turn, second rejection → `escalate_to_analyst`; Anthropic timeout/429 fails closed | P1 | Forced illegal transition escalates once and is corrected; forced double-rejection lands in `escalate`; judge stubbed to time out still cannot produce an `action_*` | 3.1, 3.2 |

Risk: this phase is the biggest and has the most moving parts. Mitigation: build in the order listed (3.3 → 3.11); each step is testable with `redis-cli` before the next exists.

---

## Phase 4 — Demo page + observability (Sun PM, ~4 h)

Entry gate: 3.10 done. Goal: what a visitor and a reader of the README will see.

| # | Task | Pri | Done when | Depends on |
|---|---|---|---|---|
| 4.1 | Fake checkout page: *Pay $940 at "Lisboa Eletrónica"*; flips to Approved/Blocked on outcome via SSE | P0 | Visual state matches `transactions.status` | 3.10 |
| 4.2 | Live dashboard: `calls.state`, outcome, audit rows, per-turn `stt_ms/llm_ms/tts_ms/net_ms` | P0 | Panel updates during a call without refresh | 3.10 |
| 4.3 | OTel spans: `ring`, `session.create→ready`, `webrtc.connect`, per-turn `stt/llm/tool.*/tts/network`; trace ID = `call_id` | P0 | One trace per call visible in collector/Jaeger | 3.6, 3.7 |
| 4.4 | Metrics: `alert_to_ring_ms`, `session_ready_ms`, `answer_to_first_tts_ms`, `agent_sessions_active/rejected`, `session_create_stream_lag`, `judge_invocations_total`, `judge_ms`, dedupe hits, rate-limit rejects | P0 | All appear on `/metrics` with values after one call | 3.6, 3.7 |
| 4.5 | Sandbox guardrails: 3-min session cap, daily minute cap, IP rate limit, "sandbox busy" UI state | P1 | Cap triggers visibly; text mode unaffected | 3.6 |
| 4.6 | Deploy: services on Fly.io/Railway, `demo-web` on Vercel, Neon Postgres already linked (commit the services hosting decision) | P1 | Public URL rings on a phone browser | 4.1–4.4 |
| 4.7 | In-app Grafana-style panel beside widget (Grafana proper deferred to write-up) | P2 | — | 4.4 |

Risk: deploy eats the evening. Mitigation: 4.6 is P1; a local demo over a tunnel (ngrok/cloudflared) is acceptable for Sunday.

---

## Phase 5 — Hardening tests (interleaved, finish Sun PM, ~1.5 h)

Entry gate: the relevant feature exists. These *are* the success metrics from BRIEF §9; each is a test in CI.

| # | Task | Pri | Done when | Depends on |
|---|---|---|---|---|
| 5.1 | Test: zero `action_*` transitions without prior `verified` in `audit_log` (adversarial transcript fixtures), **including judge-produced transitions** — a judge verdict is re-validated, never trusted | P0 | Test in CI, green | 3.2, 3.11 |
| 5.2 | Test: zero unredacted PAN-like strings in logs/transcripts (seeded fakes) | P0 | Test in CI, green | 2.6 |
| 5.3 | Test: zero WebRTC connects without a valid `call_id`-bound token | P0 | Test in CI, green | 3.8 |
| 5.4 | Test: duplicate `fraud.alert` produces one call; capacity race with 5 parallel alerts yields exactly 3 rings + 2 busy | P1 | Test in CI, green | 3.6 |
| 5.5 | Measure: `alert_to_ring_ms` p95 over 20 local runs < 3000 ms | P1 | Number in `docs/OBSERVABILITY.md` | 4.4 |

---

## v1.1 (week 2) — outline only

Twilio outbound with μ-law transport (parks on 0.2's trial account) → SMS OTP + Turnstile → no-answer SMS fallback → load test 10/20/50 → `SCALING.md`, `THREAT_MODEL.md` → LinkedIn post + video. Plan in detail after v1 retro.

---

## Working agreements

- Commit at the end of every task; task number in the commit message.
- If a task exceeds 2× its estimate, stop and either cut it (per the cut line) or split it.
- Open questions from BRIEF §10 are tasks here (1.5, 2.4, 2.7, 3.5, 4.6); resolve them in-phase and append the decision to BRIEF §10.
- `docs/` gets a file every time a decision or measurement is made; the README is assembled from `docs/` at the end.
