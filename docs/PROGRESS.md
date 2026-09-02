# PROGRESS — Sentinel

Running log of what is actually done, verified how, and what got in the way.

**Convention.** A task moves to ✅ only when its *done when* from [PLAN.md](PLAN.md) has been checked — the Evidence column records the check, not the intent. Blockers get an entry the moment they cost time, with the resolution appended when they clear. All times are `America/New_York`.

---

## At a glance

| Phase | Scope | Status |
|---|---|---|
| 0 · Bootstrap | 6 tasks (5 P0, 1 P1) | **✅ Complete** — every done-when verified, including the Redis half of 0.3 (B1 resolved) |
| 1 · Transport skeleton | 5 tasks | **✅ Complete** — all five done; Safari half of 1.2 deferred to 4.6 (B9). **Phase 2 entry gate met** |
| 2 · First conversation | 7 tasks | **In progress** — 2.1 ✅ · 2.2 ✅ |
| 3 · State machine + pipeline | 11 tasks | Not started |
| 4 · Demo + observability | 7 tasks | Not started |
| 5 · Hardening tests | 5 tasks | Not started |

**Phase 1 entry gate — "Phase 0 P0 done": met** (2026-09-02). Nothing outstanding.

**Phase 2 entry gate — "1.1–1.3 done": met** (2026-09-02). 1.4 and 1.5 are P1 and do not gate it.

---

## Phase 0 — Bootstrap

| # | Task | Pri | Status | Verified | Evidence | Commit |
|---|---|---|---|---|---|---|
| 0.1 | Monorepo layout + service README stubs | P0 | ✅ | 2026-09-01 22:02 | Five dirs under `services/`, each with a README covering responsibilities, interfaces, and non-responsibilities. Done-when "`git log` shows one commit" was already unachievable — see B4 | `cc2d826` |
| — | `docs/ARCHITECTURE.md` (not a PLAN task) | — | ✅ | 2026-09-01 22:14 | Engineering reference: topology, Redis inventory, contracts, lifecycle, trust boundaries, metrics, capacity, unresolved list | `9156749` |
| — | Decision: `calls` row written via `core-api` | — | ✅ | 2026-09-01 22:38 | Propagated to ARCHITECTURE §7, the handshake diagram, BRIEF §5 + §10, and two service READMEs | `2916140` |
| 0.2 | Provision keys; `.env.example` lists every var | P0 | ✅ | 2026-09-01 22:44 | `.env.example` committed with all 11 vars; `.env` holds Deepgram, Cartesia, Cerebras, Anthropic, `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, `REDIS_URL`; `git check-ignore .env` passes. Twilio parked commented-out for v1.1 | `f133d2a` |
| 0.3 | Local infra: Redis 7 via compose; Neon reachable | P0 | ✅ | Postgres 2026-09-01 22:47 · Redis 2026-09-02 12:53 | Postgres: `select 1` returns 1 against the Neon `production` branch. Redis: `docker compose up -d` → `sentinel-redis` healthy on redis 7.4.11, and `redis-cli XINFO STREAM fraud.alert` → `ERR no such key` — server up, stream absent, exactly the specified done-when. Streams exercised end to end (`XADD` → `XLEN` 1 → `DEL` → back to no such key) | `f133d2a` |
| 0.4 | Schema on Neon: 8 tables, `calls.state` enum, `state_history` JSONB | P0 | ✅ | 2026-09-01 22:46 | Migration applied **twice**, second run clean (all objects guarded). `information_schema` reports 8 tables; `call_state` enum has all 8 values; seed applied twice leaves `customers=1, cards=1` | `094569c` |
| 0.5 | Shared `contracts/` package — 7 event models | P0 | ✅ | 2026-09-01 22:47 | `uv run pytest` → **25 passed**. Round-trip (JSON and dict) for all seven events, plus unknown-field rejection, frozen-model, and a test asserting exactly seven contracts exist | `750e376` |
| 0.6 | `/health` + `/metrics` on every FastAPI service | P1 | ✅ | 2026-09-01 22:52 | All four services started under uvicorn; `/health` → `200 {"status":"ok","service":…}` and `/metrics` → `200 text/plain; version=1.0.0` with 10 series each. `demo-web` excluded (Next.js, no runtime until 1.2) | `750e376` |

### What Phase 0 produced

```
.env.example              11 vars, no secrets
docker-compose.yml        Redis 7-alpine, appendonly, healthcheck
db/migrations/001_init.sql   8 tables, call_state enum, idempotent guards throughout
db/seed.sql               Alex Rivera / last4 4242 / Porto — the verify_challenge factors
contracts/                sentinel_contracts: 7 pydantic models + stream and channel names
pyproject.toml            uv workspace: contracts + 4 services, one lockfile
services/*/               4 FastAPI apps with /health and /metrics
```

---

## Phase 1 — Transport skeleton

| # | Task | Pri | Status | Verified | Evidence | Commit |
|---|---|---|---|---|---|---|
| 1.1 | `agent`: Pipecat pipeline with SmallWebRTC transport, echo processor | P0 | ✅ | 2026-09-02 13:50 | Audio round trip measured, not guessed: `tools/echo_probe.py` sends eight 440 Hz bursts as a real WebRTC peer and times the return. 8/8 echoed, **median 281 ms** (278–283) across two consecutive runs. Confirmed by ear in Chrome on 2026-09-02: the delay was not noticeable, which is the done-when as written. Connect and disconnect both log; the runner cancels on disconnect with no leak | `e16f35a` |
| 1.2 | `demo-web`: Pipecat JS client, Connect button, mic permission | P0 | ✅ Chrome | 2026-09-02 14:45 | Next.js 16 app; `npm run build`, `tsc --noEmit` and `eslint` all clean. Server side verified without a browser: CORS preflight returns the right `access-control-allow-*` for `http://localhost:3000`, and an aiortc probe speaking RTVI gets `bot-ready` back from `client-ready` — the exact exchange `PipecatClient.connect()` waits on. Chrome confirmed by ear on 2026-09-02: connected, echo heard. Safari deferred to 4.6 (B9) | `d44e69a` |
| 1.3 | Per-frame timing: `net_ms` per audio frame with a `call_id` | P0 | ✅ | 2026-09-02 14:52 | One probe run produces **1085 per-frame lines at DEBUG**, all carrying the same `call_id` as the connect and disconnect lines, at 50 fps. Re-verified after the simplification below | `e993950`, simplified in *(this commit)* |
| 1.4 | Text transport through the same pipeline | P1 | ✅ | 2026-09-02 14:40 | Typed text echoes through the *running* pipeline, not a parallel one: probe sends RTVI `client-message {t: text-input}` and gets `server-message {type: text-echo, text: hello}` back, with `echo: text in 'hello'` logged from `EchoProcessor` in between. Re-run with **no audio track at all** — the declined-mic case — and it still works | *(this commit)* |
| 1.5 | Decide: text mode reuses `session.create` | P1 | ✅ | 2026-09-02 14:45 | Decision paragraph appended to [BRIEF §10](BRIEF.md) and the row closed in [ARCHITECTURE §14](ARCHITECTURE.md): **reuse**. 1.4 made it near-free, so the argument reduces to not building the authority model twice | *(this commit)* |

### Reading the 281 ms

The done-when is "you hear yourself with < 300 ms delay", which no one can
check with a stopwatch, so 1.1 shipped with a probe instead. Three things about
that number:

- **It is a round trip and an upper bound.** Roughly **160 ms of it is the
  probe's own aiortc stack** — jitter buffer and opus at both ends of the loop,
  measured against a bare aiortc relay with no pipeline in it as a control. The
  pipeline's own contribution is therefore ~120 ms. A browser's WebRTC
  implementation is better tuned than aiortc's, so what you hear in the
  browser should sit below what the probe prints.
- **`audio_out_10ms_chunks=2` is a measured change, not a preference.** Stock
  Pipecat buffers 40 ms of output; halving it moved the median 297 → 281 ms and
  tightened the spread from 295–311 ms to 278–283 ms.
  [ARCHITECTURE](ARCHITECTURE.md) budgets 250 ms to network and jitter for both
  directions combined, so this is worth the two extra flushes per 40 ms.
- **`audio_out_auto_silence=False` was considered and dropped.** It suits an
  echo, where audio flows continuously, but Phase 2's bot is silent between
  utterances and the output track has to keep emitting to hold the stream open.

### What 1.1 produced

```
services/agent/sentinel_agent/echo.py          EchoProcessor + one runner per connection
services/agent/sentinel_agent/main.py          /api/offer signalling, lifespan cleanup
services/agent/tools/echo_probe.py             the measurement above, re-runnable
```

`EchoProcessor` is the only non-obvious part. The input transport emits
`InputAudioRawFrame` (a `SystemFrame`) and the output transport only ever plays
`OutputAudioRawFrame`, so `Pipeline([transport.input(), transport.output()])`
connects and sits there in silence. Re-wrapping the same PCM bytes *is* the echo.

### What 1.2 produced

```
services/demo-web/app/voice-widget.tsx   the client component: Connect, mic, <audio>
services/demo-web/app/page.tsx           renders it
services/demo-web/app/layout.tsx         title + globals.css
services/demo-web/next.config.ts         turbopack.root, agentRules: false
services/agent/.../main.py               CORSMiddleware (the one server change 1.2 needed)
```

Two things were worth finding out before writing the page:

- **The agent needed no RTVI code.** `PipecatClient.connect()` does not resolve
  when the peer connection opens — it sends `client-ready` over a data channel
  and waits for `bot-ready`. Our 1.1 echo pipeline never mentions RTVI, so this
  looked like a required server change. It is not: `PipelineWorker` sets
  `enable_rtvi=True` by default, prepends an `RTVIProcessor`, adds the observer,
  and wires `on_client_ready → set_bot_ready()` itself. Verified, not assumed —
  the probe gets `bot-ready {"version": "2.1.0", "library": "pipecat-ai"}`.
- **CORS was a required server change.** demo-web is served from `:3000` and
  posts the offer to `:8003`, so the browser preflights it. Only signalling
  crosses origins; WebRTC media is not subject to CORS at all, which is why the
  allowed methods are just `POST, PATCH, OPTIONS`.

### What 1.3 measures, and what it found

`net_ms` is how far behind the media clock a frame is when it reaches the
pipeline. The first frame sets the baseline; every frame after it is compared
against where its sample count says it should have arrived. It is **not**
absolute one-way latency — that needs a shared clock between browser and
server, which does not exist. The absolute number stays with the round trip in
`tools/echo_probe.py`, and 4.3 pairs the two with the WebRTC RTT to split them
by direction.

The first measurement is already useful: **`net_ms` does not grow**. Over 16
seconds and 1085 frames the p50 stayed near 1.7 ms and the max never passed
16 ms, so the input side is keeping up with real time and no buffer is
quietly filling. That places essentially none of the ~281 ms round trip on the
inbound path — it is opus, the jitter buffers at both ends, and output pacing.
Worth knowing before Phase 2 starts adding STT to this same path.

### What 1.4 and 1.5 produced

Text mode needed no new transport, no new pipeline and no new endpoint — three
lines in `EchoProcessor` and a text box in the widget:

```
services/agent/.../echo.py            RTVIClientMessageFrame in -> RTVIServerMessageFrame out
services/demo-web/app/voice-widget.tsx  a text box and a transcript list
```

`PipelineWorker` prepends its `RTVIProcessor` *above* the whole pipeline
(`processors = [self._rtvi, pipeline]`), so a typed message is already a frame
travelling the same path the audio takes. Text is not a second mode; it is the
same call with a different input frame. That is what made 1.5 easy to decide —
the reuse it was weighing turned out to cost nothing, so the only question left
was whether to implement the state machine, tool guards and judge escalation
twice. See [BRIEF §10](BRIEF.md).

The check worth keeping: an offer carrying **only a data channel** — no audio
track, the visitor who declined the microphone — still completes the RTVI
handshake and echoes typed text. Pipecat logs `Audio transceiver not found` as
a warning and carries on.

### Simplification pass against CLAUDE.md §2/§3 (2026-09-02)

Phase 1 was audited against the repo's own rules — *minimum code that solves
the problem, nothing speculative* and *touch only what you must* — and six
things failed. Net **-161 lines** of agent code, no behaviour lost.

| What | Why it failed | Fix |
|---|---|---|
| `/dev` page + `dev_client.html` | Orphaned by 1.2. Its own docstring said "Replaced by demo-web in 1.2" and then it wasn't. §3 says remove what your own changes orphan | Deleted, with the route, `DEV_CLIENT`, and two imports |
| `timing.py` summary aggregator | p50/p95/max windows are PLAN 4.4's job. 1.3 asked for per-frame lines | Removed `_flush`, the window, `statistics` |
| `AGENT_LOG_LEVEL` env hook | Only existed because the summary took INFO and pushed frame lines to TRACE. Remove the summary and the knob has no reason to exist. It also called `logger.remove()`, clobbering Pipecat's own sink | Deleted; frame lines log at DEBUG and are visible by default |
| `summary_every` parameter | Configurability no caller asked for | Deleted |
| `run_echo_bot(..., call_id=None)` | An optional parameter for a caller that arrives in 3.6. Writing for a future caller is the definition of speculative | `call_id` is minted inside |
| Comma-split parsing of `ICE_SERVERS` / `DEMO_WEB_ORIGIN` | Parsed N values where exactly one is used. The env var itself is fine — those genuinely differ dev vs prod — the list handling was not | Single value each |

One comment was also rewritten: `EchoProcessor` forwards the original audio
frame, and the docstring justified that as "non-destructive for anything added
downstream later". The real reason is that it is a `SystemFrame` and the
pipeline's bookkeeping rides on those. Behaviour unchanged, honesty improved.

**Kept deliberately, against a literal reading of §2:** `tools/echo_probe.py`.
It is beyond what any task asked for, but it is not a product feature — it is
the evidence for a numeric done-when, and this file's own convention is that
the Evidence column records a check rather than an intent. It also paid for
itself twice, finding the `audio_out_10ms_chunks` win and catching B7.

Re-verified after the pass: audio round trip 282 ms, text echo returns, CORS
preflight unchanged, `/dev` now 404s.

---

## Phase 2 — First conversation

| # | Task | Pri | Status | Verified | Evidence | Commit |
|---|---|---|---|---|---|---|
| 2.1 | Wire Deepgram Nova STT and Cartesia TTS into the pipeline | P0 | ✅ | 2026-09-02 17:00 · browser 2026-09-02 | Real speech through the real pipeline, no browser needed: Cartesia synthesised "Hello. My name is Alex Rivera.", a probe streamed the WAV in over WebRTC, Deepgram returned it as **two** correctly endpointed utterances (`stt: 'Hello.'`, `stt: 'My name is Alex Rivera.'`) and Cartesia spoke both back as audio the probe received. Text mode (1.4) re-checked, no regression. Confirmed by ear in the browser | `311b4a9` |
| 2.2 | Persona system prompt + consent line | P0 | ✅ | 2026-09-02 17:55 | The consent line is the first thing spoken, before the model is asked for anything — confirmed in the TTS log on every run. A full turn now works: caller says "Yes, now is a good time", agent replies *"Great, thank you. To verify your account, could you please tell me the last four digits of the card…"* — persona holding, and asking for last four rather than a full number without being reminded. Typed input reaches the same conversation and gets the same persona | *(this commit)* |
| 2.3 | Five Neon tools via `core-api`, each writing an audit row | P0 | Not started | — | — | — |
| 2.4 | Calibrate the two-tier model stack | P1 | **Blocked by choice** — see B10 | — | — | — |
| 2.5 | Full happy path in browser (deny + confirm) | P0 | Not started | — | — | — |
| 2.6 | PAN redaction (regex + Luhn) | P0 | Not started | — | — | — |
| 2.7 | Spec: state machine placement + structured-output schema | P0 | Not started | — | — | — |

### First real latency numbers

Cartesia, measured by Pipecat's own metrics on two consecutive utterances:

| | |
|---|---|
| TTFB (request to first byte) | 0.130 s, 0.131 s |
| TTFA (request to first audio) | 0.280 s, 0.281 s — of which 0.150 s is leading silence |

[ARCHITECTURE](ARCHITECTURE.md) budgets **~250 ms** for "tts (time to first
audio)". TTFB comes in at half that; TTFA lands just over, and 150 ms of it is
silence Cartesia pads the front of the clip with. Worth revisiting in 2.4 —
trimming leading silence may be free latency.

### What 2.1 changed

The audio no longer short-circuits. `EchoProcessor` used to re-wrap
`InputAudioRawFrame` as `OutputAudioRawFrame`; that is gone, and the path is now
`transport.input() → timing → Deepgram → EchoProcessor → Cartesia → transport.output()`.

The one non-obvious bit: a transcript cannot simply be forwarded to the TTS.
`TranscriptionFrame` subclasses `TextFrame`, which is what TTS consumes, but the
TTS service explicitly excludes both `TranscriptionFrame` and
`InterimTranscriptionFrame` so that a pipeline never speaks its own input. The
reply has to be a `TTSSpeakFrame`, the frame for a standalone utterance.
Interim results need no filtering of our own either —
`InterimTranscriptionFrame` is a *sibling* of `TranscriptionFrame`, not a
subclass, so the `isinstance` check already sees only finals.

`python-dotenv` arrived with this task: the vendor keys have been sitting in
`.env` since 0.2 and uvicorn never read it.

### What 2.2 decided

**The consent line is a constant, spoken deterministically — not generated.**
`CONSENT_LINE` is pushed as a `TTSSpeakFrame` on connect, before the model is
asked for anything. Two reasons, and both matter: 2.2's done-when is that it
comes *first*, which a model asked to be concise cannot be relied on to honour;
and a consent and recording disclosure is the one line on the call whose wording
should not be paraphrased by anything.

**The persona prompt carries style and safety, not authority.** BRIEF §5 is
explicit that the state machine's rules are "enforced in code, not in the
prompt". So `SYSTEM_PROMPT` covers voice (no markdown, one or two sentences,
numbers written as spoken) and the two hard "never"s — never say a full card
number, never ask for a PIN or a one-time code — and says nothing about
`verify_identity` gating `action_*`. That gate is 3.1's validator. The prompt
must not grow into a substitute for it.

**`echo.py` became `pipeline.py`.** It stopped being an echo the moment the LLM
went in, and leaving the old name would have been misleading rather than
surgical.

### B11 · Turn-taking needs VAD, and 2.1 had dropped it · **RESOLVED**

- **Hit:** 2026-09-02 17:45, first full conversation attempt.
- **Symptom:** the consent line played, the caller spoke, Cerebras generated a
  reply — and nothing was ever spoken. The log showed the LLM completing and
  then being cancelled.
- **Cause:** with no VAD analyzer the user aggregator ends a turn on every
  *final transcript*, and Deepgram splits even "Yes, now is a good time." into
  `'Yes.'` and `'Now is a good time.'`. The second transcript starts a new user
  turn, which broadcasts an interruption, which kills the in-flight reply to the
  first. The caller is never answered — and nothing errors, which is what made
  it worth writing down.
- **Resolution:** `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())`,
  so silence rather than punctuation decides when a turn is over.
- **Worth admitting:** 2.1 added the `silero` extra and then removed it again as
  "unused", on the simplicity pass's logic. It was not unused, it was
  not-yet-used. Removing a dependency because nothing imports it *yet* is the
  same speculation as adding one for later, pointed the other way.

### Cerebras latency, first look

`CerebrasLLMService` TTFB on two clean turns: **0.94 s** and **1.00 s**.
[ARCHITECTURE](ARCHITECTURE.md) budgets **~400 ms** for `llm`, so this is
roughly 2.5× over on a single-sentence context. Too early to conclude anything —
these are cold, unbatched, first-of-connection calls and the context is tiny —
but 2.4 exists precisely to measure this, and the number to beat is now on
record rather than assumed.

### 2.2 follow-up: three defects the first real listen found

Dogfooding beat every probe I wrote. A human on a headset broke it in ways
synthesised speech never did:

| Symptom | Cause | Fix |
|---|---|---|
| Agent answered *"Hello, how can I help you today?"* and *"the card you're calling about"* | The prompt said what the agent **is** but never that it **placed the call**. With no direction established, an LLM falls back to inbound support, which is the overwhelmingly more common shape in training data | The prompt now opens by stating Meridian's monitoring flagged a transaction and the agent rang the cardholder, who has no request to handle — and forbids asking what they need |
| Agent offered *"I'll call you tomorrow at twelve noon"* and then *"I've scheduled the call"* | The prompt forbade inventing **facts** (amounts, merchants) but said nothing about inventing **capabilities**. Fabricating an action is worse than fabricating a detail: the caller hangs up expecting a callback that will never come | Explicit rule: everything the agent can do happens on this call, now. No callbacks, transfers, emails or follow-ups, ever offered |
| One reply appeared in the UI eight times | Mine, not the model's. `onBotOutput` fires repeatedly for the *same* segment as its spoken status updates; the handler appended on every event | Replace the line whose `segment_id` matches instead of appending |

Also added: a rule for hostile callers, since the tester swore at it and the
agent had no guidance. It now stays calm and points them at the number on the
back of their card rather than arguing.

Retested against the exact failure — caller says only "Hello? Hello, who is
this?" — and the agent now leads:

```
AGENT   [consent line]
CALLER  'Hello?' 'Who' 'this?'
AGENT   I'm calling about your card.
AGENT   Could you tell me the last four digits of the card and the city where
        you were born?
```

which is BRIEF §4 step 4 almost verbatim. Zero occurrences of the inbound
phrasing or a promised callback in spoken output.

**The lesson worth keeping:** the synthesised-speech probes only ever fed it
cooperative input. Every one of these defects needed a real person being
unhelpful. Probes prove the plumbing; they do not prove the persona.

---

## Blockers

### B1 · No container runtime — Redis cannot run locally · **RESOLVED**

- **Hit:** 2026-09-01 22:42, during 0.3. **Cleared:** 2026-09-02 12:53.
- **Symptom:** `docker: command not found` in both shells; `C:\Program Files\Docker\Docker\Docker Desktop.exe` absent; `wsl -l -v` → "has no installed distributions".
- **Impact while open:** the `redis-cli XINFO STREAM fraud.alert` half of 0.3 was unverified and `docker-compose.yml` was unproven.
- **Resolution:** installed Docker Desktop 4.89.0 with `winget install --id Docker.DockerDesktop`. Three things went sideways on the way, all worth knowing:
  1. **The first winget run reported failure but actually succeeded.** `Installer failed with exit code: 4294967290` (`-6`), yet the install completed after winget stopped waiting. The retry then refused with "Found an existing package already installed".
  2. **It installs per-user, not to `Program Files`.** Everything lives under `%LOCALAPPDATA%\Programs\DockerDesktop` with an HKCU uninstall entry, so the obvious `Test-Path "C:\Program Files\Docker\..."` check reports a missing install that is in fact present. No admin rights were needed.
  3. **Engine came up in ~5 s** once launched with `-Accept-License`; Docker 29.7.2 client and server, WSL2 backend, no reboot and no separate distro install.

### B2 · No `psql` and no `redis-cli` on the machine · **RESOLVED**

- **Hit:** 2026-09-01 22:42, during 0.3 / 0.4.
- **Symptom:** neither client is installed; 0.3 and 0.4 are written against both.
- **Resolution:** applied and verified the schema through the Neon MCP connection instead (`run_sql_transaction` for the migration, `run_sql` for the checks). `db/*.sql` stay the source of truth and remain plain psql-runnable for anyone who has it. The `redis-cli` check inherits B1.

### B3 · `/metrics` answered 307, not 200 · **RESOLVED**

- **Hit:** 2026-09-01 22:50, during 0.6 verification.
- **Symptom:** with `app.mount("/metrics", make_asgi_app())`, Starlette serves the sub-app at `/metrics/` and redirects `/metrics` → 307. 0.6's done-when is a 200, and not every Prometheus scraper follows a redirect.
- **Resolution:** replaced the mount with a plain route returning `generate_latest()` and `CONTENT_TYPE_LATEST`. Re-verified: 200 with `text/plain; version=1.0.0` on all four services.

### B4 · `new-project` skill unavailable · **RESOLVED**

- **Hit:** 2026-09-01 ~21:50, during 0.1.
- **Symptom:** 0.1 specifies creating the repo from a template via the `new-project` skill; the skill is not installed.
- **Resolution:** built the layout by hand at the user's direction. Two consequences: the done-when "`git log` shows one commit" was already false (the repo had two commits of design docs), and nothing a template would normally supply — CI workflow, lint/format config, packaging — came along. The uv workspace and `pyproject.toml` files added in 0.5/0.6 cover packaging; CI and lint config were written separately on 2026-09-02 (see below).
- **CI, added 2026-09-02 13:06:** `.github/workflows/ci.yml` — a `lint` job (`ruff check`, `ruff format --check`, `uv lock --check`) and a `test` job (`pytest` against `redis:7-alpine` and `postgres:17` service containers). Both green on run [33658991794](https://github.com/yaksh1/Sentinel-Voice-AI-Fraud-Detection/actions/runs/33658991794): lint 10 s, test 25 s, `25 passed`. Ruff config lives in the root `pyproject.toml` (line-length 100, `E/F/I/UP/B/SIM`, the five `sentinel_*` packages first-party); it needed no source changes — the tree was already clean under it.
- **Postgres in CI is a service container, not a Neon branch.** A Neon branch needs `NEON_API_KEY` in the environment, and GitHub withholds secrets from workflows triggered by pull requests from forks, so a public repo would have no gate on fork PRs. The schema is portable (guarded throughout, `gen_random_uuid()` is core Postgres 13+), and CI applies `001_init.sql` and `seed.sql` **twice** — which is what actually proves the idempotency claimed in 0.4 — then asserts the 8 tables and 8 `call_state` values.
- **`astral-sh/setup-uv` publishes no moving major tag past v7.** `@v10` does not resolve; the first run failed at `Set up job` in 6 s. Pinned to `@v10.0.1`.

### B5 · Python 3.14 dependency risk · **RESOLVED (no action needed)**

- **Hit:** 2026-09-01 22:47, during 0.5.
- **Symptom:** the only interpreter on the machine is 3.14.2, new enough that missing wheels were plausible for `pydantic-core` and anything in `uvicorn[standard]`.
- **Resolution:** dropped the `[standard]` extra (it pulls `httptools`/`uvloop`, neither useful on Windows) and let uv resolve. `pydantic 2.13.5` and `pydantic-core 2.46.5` have 3.14 wheels; `uv sync` completed with no build step.

### B6 · `docker compose` could not pull images — credential helper not found · **RESOLVED**

- **Hit:** 2026-09-02 12:53, immediately after the engine came up.
- **Symptom:** `docker compose up -d` failed with `error getting credentials - err: exec: "docker-credential-desktop": executable file not found in %PATH%`. Docker's config sets `credsStore: desktop`, and that helper ships in Docker Desktop's own `resources\bin`.
- **Resolution:** prepended that directory to `PATH` for the shell rather than editing `~/.docker/config.json` — the config is right, the shell's environment was stale. The installer *does* add the directory to the persistent user PATH, so this only affects shells that were already running when Docker was installed.

### B7 · A dead uvicorn kept serving, and two measurements were quietly wrong · **RESOLVED**

- **Hit:** 2026-09-02 ~13:35, during 1.1 latency tuning.
- **Symptom:** restarting the agent with `uv run uvicorn ... > log 2>&1 &` after
  changing a transport parameter produced no change in the measured latency —
  twice, for two different parameters. The obvious reading was "neither knob
  does anything", and it was wrong.
- **Cause:** the old process had not actually died, so each new uvicorn failed
  with `[Errno 10048] only one usage of each socket address`, logged it, and
  exited. The port stayed served by the *original* process running the
  *original* code. Because `>` truncates, the log only ever held the newest
  (failed) start, and the failure scrolled past under normal-looking output.
- **Caught by:** the `pc_id` in the probe output. Pipecat numbers connections
  per process — `SmallWebRTCConnection#4` on what should have been a fresh boot
  means four connections had already been served by that process.
- **Resolution:** kill by port before starting (`Get-NetTCPConnection -LocalPort
  8003 -State Listen`), then assert on two things before trusting a number:
  `Uvicorn running` present with no `10048` in the log, and `pc_id` ending in
  `#0`. Re-run under that discipline, `audio_out_10ms_chunks=2` did move the
  median — 297 → 281 ms.
- **Worth keeping:** a negative result from an A/B needs proof the B ever ran.

### B8 · `/browse` cannot run on this machine · **OPEN (worked around)**

- **Hit:** 2026-09-02 14:15, verifying 1.2.
- **Symptom:** `browse.exe` exits with "An Application Control policy has blocked
  this file" under PowerShell, and "Permission denied" under Git Bash. The binary
  is present and executable-flagged; Windows refuses to run it.
- **Impact:** no headless browser QA in this environment — not for 1.2, and not
  for 3.10 or 4.1/4.2 either, which are all browser-facing.
- **Worked around for 1.2** by verifying the server side directly: `curl` for the
  CORS preflight, and an aiortc probe speaking RTVI over a data channel for the
  `client-ready`/`bot-ready` exchange. That covers everything except the browser
  half, which now needs a human.

### B9 · No Safari, and none reachable · **DEFERRED to 4.6**

- **Hit:** 2026-09-02 14:20, at 1.2's done-when.
- **Symptom:** 1.2 requires "echo works from Chrome and Safari". This is Windows;
  Safari has not shipped for Windows since 2012, so the Safari half cannot be
  checked here at all.
- **Why it is not cosmetic:** Safari is the one engine with materially different
  WebRTC behaviour — stricter autoplay policy on `<audio>` elements, and its own
  codec negotiation. It is also every iPhone browser, including Chrome for iOS.
  A demo that rings a phone (PLAN 4.6) is a Safari demo.
- **The obstacle beyond hardware:** `getUserMedia` requires a secure context, so
  a phone on the LAN cannot use the mic against `http://<lan-ip>:3000`. Testing
  on a real iPhone needs HTTPS — a tunnel (cloudflared/ngrok) or a local cert —
  which is most of PLAN 4.6 pulled forward.
- **Decision (2026-09-02):** defer the Safari half to [PLAN](PLAN.md) 4.6. That task already
  has to produce a public URL that "rings on a phone browser", which means HTTPS and a real
  device — exactly what Safari needs. Building a tunnel now would be building 4.6 twice.
  4.6's done-when has been amended to name Safari so it cannot be quietly skipped.
- **Carried risk:** Phase 2 and 3 build on a transport proven only on Chromium. If Safari
  turns out to need transport changes (autoplay, codec negotiation), it surfaces late.
  Accepted knowingly — the alternative spends Saturday on deployment plumbing.

### B10 · 2.4 needs the Anthropic key, which is off limits · **OPEN**

- **Raised:** 2026-09-02, by instruction at the start of Phase 2.
- **Constraint:** do not call the Anthropic API without discussing it first;
  use Cerebras where a model is needed.
- **What it blocks:** 2.4 calibrates the *two-tier* stack, and half of that is
  "judge round-trip when escalation fires" — a Claude Sonnet 5 call. The
  Cerebras half (`gpt-oss-120b` `llm_ms` p50/p95, tool-call correctness over 10
  runs) is unaffected and can be done in full. 3.11 is the judge itself and is
  blocked the same way.
- **Options when it comes up:** split 2.4 and do the Cerebras half now, leaving
  the judge column empty; or agree a budget for a handful of Sonnet calls, which
  is what a p50/p95 over ~10 escalations would actually cost; or cut the judge
  from v1 entirely, which the PLAN's own cut line already contemplates (3.11 and
  2.4 are both P1).
- **Not urgent:** 2.4 is P1 and nothing before 2.5 depends on it.

---

## Notes for the next session

- **CI is live** (B4): every push to `main` and every PR runs `lint` + `test`. Phase 5 tests need only be written — `testpaths` already covers `services/`, and the `test` job hands them `DATABASE_URL`, `DATABASE_URL_UNPOOLED` and `REDIS_URL` pointing at real containers. GitHub-hosted runners are free with no minute cap on public repos.
- **Decisions live in [BRIEF §10](BRIEF.md), not here.** Open architectural questions with the task that closes each are in [ARCHITECTURE §14](ARCHITECTURE.md).
- **Ports:** core-api 8000, risk-engine 8001, call-orchestrator 8002, agent 8003 (`.env.example`).
- **Docker in an old shell:** if `docker` is not found, the shell predates the install — open a new terminal, or `export PATH="$PATH:/c/Users/yaksh/AppData/Local/Programs/DockerDesktop/resources/bin"` (B6).
- The seeded verification factors are last4 `4242` and city of birth `Porto`, on customer `00000000-…-0001`.
- **Restarting the agent:** free port 8003 first and check the log for `10048` before believing any
  measurement taken against it (B7). The probe's `pc_id` should end in `#0` on a fresh process.
- **The agent has no browser page of its own.** `/dev` existed only so 1.1 could be checked
  before `demo-web` did; it was deleted once 1.2 landed. Run `demo-web` to talk to the agent.
- **Running the demo:** agent on 8003 and `npm run dev` in `services/demo-web` for 3000. Both are
  needed; Connect fails with a CORS or connection error if the agent is down.
- **demo-web is not in CI.** The `test` job is Python only, so a TypeScript or build break in
  `services/demo-web` would not be caught. Worth a third job before Phase 4 adds real UI.
