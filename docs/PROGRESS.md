# PROGRESS — Sentinel

Running log of what is actually done, verified how, and what got in the way.

**Convention.** A task moves to ✅ only when its *done when* from [PLAN.md](PLAN.md) has been checked — the Evidence column records the check, not the intent. Blockers get an entry the moment they cost time, with the resolution appended when they clear. All times are `America/New_York`.

---

## At a glance

| Phase | Scope | Status |
|---|---|---|
| 0 · Bootstrap | 6 tasks (5 P0, 1 P1) | **5 done, 1 partial** — every P0 verified except the Redis half of 0.3 (see B1) |
| 1 · Transport skeleton | 5 tasks | Not started — entry gate open (see below) |
| 2 · First conversation | 7 tasks | Not started |
| 3 · State machine + pipeline | 11 tasks | Not started |
| 4 · Demo + observability | 7 tasks | Not started |
| 5 · Hardening tests | 5 tasks | Not started |

**Phase 1 entry gate — "Phase 0 P0 done": open.** The one unverified item, local Redis, is not on Phase 1's or Phase 2's path; Redis is first needed at 3.3. Phase 1 can start.

---

## Phase 0 — Bootstrap

| # | Task | Pri | Status | Verified | Evidence | Commit |
|---|---|---|---|---|---|---|
| 0.1 | Monorepo layout + service README stubs | P0 | ✅ | 2026-09-01 22:02 | Five dirs under `services/`, each with a README covering responsibilities, interfaces, and non-responsibilities. Done-when "`git log` shows one commit" was already unachievable — see B4 | `cc2d826` |
| — | `docs/ARCHITECTURE.md` (not a PLAN task) | — | ✅ | 2026-09-01 22:14 | Engineering reference: topology, Redis inventory, contracts, lifecycle, trust boundaries, metrics, capacity, unresolved list | `9156749` |
| — | Decision: `calls` row written via `core-api` | — | ✅ | 2026-09-01 22:38 | Propagated to ARCHITECTURE §7, the handshake diagram, BRIEF §5 + §10, and two service READMEs | `2916140` |
| 0.2 | Provision keys; `.env.example` lists every var | P0 | ✅ | 2026-09-01 22:44 | `.env.example` committed with all 11 vars; `.env` holds Deepgram, Cartesia, Cerebras, Anthropic, `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, `REDIS_URL`; `git check-ignore .env` passes. Twilio parked commented-out for v1.1 | `f133d2a` |
| 0.3 | Local infra: Redis 7 via compose; Neon reachable | P0 | ⚠️ **Partial** | 2026-09-01 22:47 | Postgres half verified: `select 1` returns 1 against the Neon `production` branch. Redis half **not run** — no container runtime on this machine (B1). `docker-compose.yml` is written and reviewed but unexecuted | `f133d2a` |
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

## Blockers

### B1 · No container runtime — Redis cannot run locally · **OPEN**

- **Hit:** 2026-09-01 22:42, during 0.3.
- **Symptom:** `docker: command not found` in both shells; `C:\Program Files\Docker\Docker\Docker Desktop.exe` absent; `wsl -l -v` → "has no installed distributions".
- **Impact:** the `redis-cli XINFO STREAM fraud.alert` half of 0.3's done-when is unverified. `docker-compose.yml` exists but has never been executed, so it is unproven, not proven-good.
- **Not blocking:** Phases 1 and 2 need no Redis. First real dependency is 3.3 (`XADD fraud.alert`), so this must clear before Phase 3.
- **Options** (needs a decision — all three are installs):
  1. **Docker Desktop** — matches the committed compose file and what CI will use. Recommended.
  2. `wsl --install Ubuntu` then `apt install redis-server` — lighter, but diverges from the compose file.
  3. Managed Redis (e.g. Upstash free tier), point `REDIS_URL` at it — no local install, adds network latency to every local `XADD` and would distort Phase 3 latency numbers.
- **Resolution:** _pending._

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
- **Resolution:** built the layout by hand at the user's direction. Two consequences: the done-when "`git log` shows one commit" was already false (the repo had two commits of design docs), and nothing a template would normally supply — CI workflow, lint/format config, packaging — came along. The uv workspace and `pyproject.toml` files added in 0.5/0.6 cover packaging; **CI and lint config remain unwritten** and are needed by Phase 5, whose tasks are all "test in CI, green".

### B5 · Python 3.14 dependency risk · **RESOLVED (no action needed)**

- **Hit:** 2026-09-01 22:47, during 0.5.
- **Symptom:** the only interpreter on the machine is 3.14.2, new enough that missing wheels were plausible for `pydantic-core` and anything in `uvicorn[standard]`.
- **Resolution:** dropped the `[standard]` extra (it pulls `httptools`/`uvloop`, neither useful on Windows) and let uv resolve. `pydantic 2.13.5` and `pydantic-core 2.46.5` have 3.14 wheels; `uv sync` completed with no build step.

---

## Notes for the next session

- **Owed to Phase 5:** a CI workflow and a lint/format config (B4). Every Phase 5 task ends in "test in CI, green", so this is on the critical path for the success metrics, not a nicety.
- **Decisions live in [BRIEF §10](BRIEF.md), not here.** Open architectural questions with the task that closes each are in [ARCHITECTURE §14](ARCHITECTURE.md).
- **Ports:** core-api 8000, risk-engine 8001, call-orchestrator 8002, agent 8003 (`.env.example`).
- The seeded verification factors are last4 `4242` and city of birth `Porto`, on customer `00000000-…-0001`.
