# PROGRESS — Sentinel

Running log of what is actually done, verified how, and what got in the way.

**Convention.** A task moves to ✅ only when its *done when* from [PLAN.md](PLAN.md) has been checked — the Evidence column records the check, not the intent. Blockers get an entry the moment they cost time, with the resolution appended when they clear. All times are `America/New_York`.

---

## At a glance

| Phase | Scope | Status |
|---|---|---|
| 0 · Bootstrap | 6 tasks (5 P0, 1 P1) | **✅ Complete** — every done-when verified, including the Redis half of 0.3 (B1 resolved) |
| 1 · Transport skeleton | 5 tasks | **In progress** — 1.1 ✅ · 1.2 built, browser check outstanding (B8, B9) |
| 2 · First conversation | 7 tasks | Not started |
| 3 · State machine + pipeline | 11 tasks | Not started |
| 4 · Demo + observability | 7 tasks | Not started |
| 5 · Hardening tests | 5 tasks | Not started |

**Phase 1 entry gate — "Phase 0 P0 done": met** (2026-09-02). Nothing outstanding.

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
| 1.1 | `agent`: Pipecat pipeline with SmallWebRTC transport, echo processor | P0 | ✅ | 2026-09-02 13:50 | Audio round trip measured, not guessed: `tools/echo_probe.py` sends eight 440 Hz bursts as a real WebRTC peer and times the return. 8/8 echoed, **median 281 ms** (278–283) across two consecutive runs. Connect and disconnect both log; the runner cancels on disconnect with no leak | *(this commit)* |
| 1.2 | `demo-web`: Pipecat JS client, Connect button, mic permission | P0 | ⚠️ Partial | 2026-09-02 14:20 | Next.js 16 app; `npm run build`, `tsc --noEmit` and `eslint` all clean. Server side verified without a browser: CORS preflight returns the right `access-control-allow-*` for `http://localhost:3000`, and an aiortc probe speaking RTVI gets `bot-ready` back from `client-ready` — the exact exchange `PipecatClient.connect()` waits on. **The Chrome/Safari listening test is not done** — see B8 and B9 | *(this commit)* |
| 1.3 | Per-frame timing: `net_ms` per audio frame with a `call_id` | P0 | Not started | — | — | — |
| 1.4 | Text transport through the same pipeline | P1 | Not started | — | — | — |
| 1.5 | Decide: text mode reuses `session.create` | P1 | Not started | — | — | — |

### Reading the 281 ms

The done-when is "you hear yourself with < 300 ms delay", which no one can
check with a stopwatch, so 1.1 shipped with a probe instead. Three things about
that number:

- **It is a round trip and an upper bound.** Roughly **160 ms of it is the
  probe's own aiortc stack** — jitter buffer and opus at both ends of the loop,
  measured against a bare aiortc relay with no pipeline in it as a control. The
  pipeline's own contribution is therefore ~120 ms. A browser's WebRTC
  implementation is better tuned than aiortc's, so what you hear at `/dev`
  should sit below what the probe prints.
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
services/agent/sentinel_agent/main.py          /api/offer signalling, /dev page, lifespan cleanup
services/agent/sentinel_agent/dev_client.html  ~90 lines of vanilla WebRTC, no build step
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

### B9 · No Safari, and none reachable · **OPEN**

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
- **Status:** needs a decision. Neither browser has been listened to yet — Chrome is a
  five-minute check for whoever has the machine, Safari needs hardware this box does not have.

---

## Notes for the next session

- **CI is live** (B4): every push to `main` and every PR runs `lint` + `test`. Phase 5 tests need only be written — `testpaths` already covers `services/`, and the `test` job hands them `DATABASE_URL`, `DATABASE_URL_UNPOOLED` and `REDIS_URL` pointing at real containers. GitHub-hosted runners are free with no minute cap on public repos.
- **Decisions live in [BRIEF §10](BRIEF.md), not here.** Open architectural questions with the task that closes each are in [ARCHITECTURE §14](ARCHITECTURE.md).
- **Ports:** core-api 8000, risk-engine 8001, call-orchestrator 8002, agent 8003 (`.env.example`).
- **Docker in an old shell:** if `docker` is not found, the shell predates the install — open a new terminal, or `export PATH="$PATH:/c/Users/yaksh/AppData/Local/Programs/DockerDesktop/resources/bin"` (B6).
- The seeded verification factors are last4 `4242` and city of birth `Porto`, on customer `00000000-…-0001`.
- **Restarting the agent:** free port 8003 first and check the log for `10048` before believing any
  measurement taken against it (B7). The probe's `pc_id` should end in `#0` on a fresh process.
- **`/dev` is a stopgap.** It exists so 1.1 could be checked without 1.2; `demo-web` replaces it.
- **Running the demo:** agent on 8003 and `npm run dev` in `services/demo-web` for 3000. Both are
  needed; Connect fails with a CORS or connection error if the agent is down.
- **demo-web is not in CI.** The `test` job is Python only, so a TypeScript or build break in
  `services/demo-web` would not be caught. Worth a third job before Phase 4 adds real UI.
