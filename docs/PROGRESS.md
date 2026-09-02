# PROGRESS — Sentinel

Running log of what is actually done, verified how, and what got in the way.

**Convention.** A task moves to ✅ only when its *done when* from [PLAN.md](PLAN.md) has been checked — the Evidence column records the check, not the intent. Blockers get an entry the moment they cost time, with the resolution appended when they clear. All times are `America/New_York`.

---

## At a glance

| Phase | Scope | Status |
|---|---|---|
| 0 · Bootstrap | 6 tasks (5 P0, 1 P1) | **✅ Complete** — every done-when verified, including the Redis half of 0.3 (B1 resolved) |
| 1 · Transport skeleton | 5 tasks | Not started — **entry gate satisfied** |
| 2 · First conversation | 7 tasks | Not started |
| 3 · State machine + pipeline | 11 tasks | Not started |
| 4 · Demo + observability | 7 tasks | Not started |
| 5 · Hardening tests | 5 tasks | Not started |

**Phase 1 entry gate — "Phase 0 P0 done": met** (2026-09-02). Nothing outstanding; 1.1 can start.

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

## Blockers

### B1 · No container runtime — Redis cannot run locally · **RESOLVED**

- **Hit:** 2026-09-01 22:42, during 0.3. **Cleared:** %s.
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
- **Resolution:** built the layout by hand at the user's direction. Two consequences: the done-when "`git log` shows one commit" was already false (the repo had two commits of design docs), and nothing a template would normally supply — CI workflow, lint/format config, packaging — came along. The uv workspace and `pyproject.toml` files added in 0.5/0.6 cover packaging; **CI and lint config remain unwritten** and are needed by Phase 5, whose tasks are all "test in CI, green".

### B5 · Python 3.14 dependency risk · **RESOLVED (no action needed)**

- **Hit:** 2026-09-01 22:47, during 0.5.
- **Symptom:** the only interpreter on the machine is 3.14.2, new enough that missing wheels were plausible for `pydantic-core` and anything in `uvicorn[standard]`.
- **Resolution:** dropped the `[standard]` extra (it pulls `httptools`/`uvloop`, neither useful on Windows) and let uv resolve. `pydantic 2.13.5` and `pydantic-core 2.46.5` have 3.14 wheels; `uv sync` completed with no build step.

### B6 · `docker compose` could not pull images — credential helper not found · **RESOLVED**

- **Hit:** 2026-09-02 12:53, immediately after the engine came up.
- **Symptom:** `docker compose up -d` failed with `error getting credentials - err: exec: "docker-credential-desktop": executable file not found in %PATH%`. Docker's config sets `credsStore: desktop`, and that helper ships in Docker Desktop's own `resourcesin`.
- **Resolution:** prepended that directory to `PATH` for the shell rather than editing `~/.docker/config.json` — the config is right, the shell's environment was stale. The installer *does* add the directory to the persistent user PATH, so this only affects shells that were already running when Docker was installed.

---

## Notes for the next session

- **Owed to Phase 5:** a CI workflow and a lint/format config (B4). Every Phase 5 task ends in "test in CI, green", so this is on the critical path for the success metrics, not a nicety.
- **Decisions live in [BRIEF §10](BRIEF.md), not here.** Open architectural questions with the task that closes each are in [ARCHITECTURE §14](ARCHITECTURE.md).
- **Ports:** core-api 8000, risk-engine 8001, call-orchestrator 8002, agent 8003 (`.env.example`).
- **Docker in an old shell:** if `docker` is not found, the shell predates the install — open a new terminal, or `export PATH="$PATH:/c/Users/yaksh/AppData/Local/Programs/DockerDesktop/resources/bin"` (B6).
- The seeded verification factors are last4 `4242` and city of birth `Porto`, on customer `00000000-…-0001`.
