-- Sentinel — initial schema (BRIEF §5 data model, ARCHITECTURE §7).
--
-- Idempotent by construction: safe to apply repeatedly against the same branch.
-- Every object is guarded, so a re-run is a no-op rather than an error.
--
--   psql "$DATABASE_URL_UNPOOLED" -f db/migrations/001_init.sql
--
-- Redaction note: the only columns holding caller-derived text are named
-- text_redacted and args_redacted. There is deliberately no unredacted
-- counterpart to write to.

-- calls.state — the one enum in the schema. Values match the state machine in
-- docs/ARCHITECTURE.md §5; the conversation pathway (consent, verify_identity,
-- …) lives in state_history, not here.
DO $$
BEGIN
    CREATE TYPE call_state AS ENUM (
        'ringing',    -- orchestrator published ring, waiting on the visitor
        'ready',      -- session.ready received, WebRTC endpoint handed over
        'connected',  -- token validated, transport up
        'in_call',    -- conversation in progress, agent owns the row
        'completed',  -- ran to close
        'no_answer',  -- declined, or ring timer expired
        'dropped',    -- agent crashed or transport failed mid-call
        'busy'        -- rejected at the capacity check, never rang
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

-- One row per sandbox visitor. city_of_birth is the knowledge factor in
-- verify_challenge; last4 comes from cards.
CREATE TABLE IF NOT EXISTS customers (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    visitor_id     text        NOT NULL UNIQUE,
    display_name   text        NOT NULL,
    city_of_birth  text        NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cards (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  uuid        NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    last4        char(4)     NOT NULL,
    brand        text        NOT NULL DEFAULT 'visa',
    status       text        NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active', 'blocked', 'reissued')),
    reissued_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cards_customer_idx ON cards (customer_id);

CREATE TABLE IF NOT EXISTS transactions (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id       uuid        NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    card_id           uuid        NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
    amount_cents      bigint      NOT NULL CHECK (amount_cents > 0),
    currency          char(3)     NOT NULL DEFAULT 'USD',
    merchant_name     text        NOT NULL,
    merchant_city     text,
    merchant_country  char(2),
    status            text        NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'held', 'released', 'blocked')),
    occurred_at       timestamptz NOT NULL DEFAULT now(),
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS transactions_customer_idx ON transactions (customer_id, occurred_at DESC);

-- alert_id is the dedupe key: it is what the orchestrator SET NX's on before
-- dialing, so a redelivered stream entry can never produce a second call.
CREATE TABLE IF NOT EXISTS fraud_alerts (
    alert_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    txn_id        uuid        NOT NULL REFERENCES transactions (id) ON DELETE CASCADE,
    customer_id   uuid        NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    risk_reasons  jsonb       NOT NULL DEFAULT '[]'::jsonb,
    status        text        NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open', 'calling', 'resolved', 'no_answer', 'busy', 'rate_limited')),
    attempts      integer     NOT NULL DEFAULT 0,
    emitted_at    timestamptz NOT NULL DEFAULT now(),
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fraud_alerts_txn_idx ON fraud_alerts (txn_id);

-- call_id is minted by the orchestrator before anything is published, and is
-- the join key across both streams, pub/sub, the WebRTC token, and the OTel
-- trace. Written only through core-api (ARCHITECTURE §7).
--
-- state_history entries: {from, to, trigger, latency_ms, at}
CREATE TABLE IF NOT EXISTS calls (
    call_id        uuid PRIMARY KEY,
    alert_id       uuid        NOT NULL REFERENCES fraud_alerts (alert_id) ON DELETE CASCADE,
    customer_id    uuid        NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    channel        text        NOT NULL DEFAULT 'browser'
                   CHECK (channel IN ('browser', 'phone', 'text')),
    state          call_state  NOT NULL DEFAULT 'ringing',
    state_history  jsonb       NOT NULL DEFAULT '[]'::jsonb,
    outcome        text        CHECK (outcome IN ('released', 'blocked', 'escalated', 'no_answer', 'dropped')),
    verified       boolean     NOT NULL DEFAULT false,
    ring_at        timestamptz,
    ready_at       timestamptz,
    connected_at   timestamptz,
    ended_at       timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS calls_alert_idx ON calls (alert_id);
CREATE INDEX IF NOT EXISTS calls_state_idx ON calls (state);

-- Per-turn transcript and the per-stage latency that the SLOs are measured
-- from. text_redacted is post-Luhn; nothing writes the raw utterance.
CREATE TABLE IF NOT EXISTS turns (
    id             bigserial PRIMARY KEY,
    call_id        uuid        NOT NULL REFERENCES calls (call_id) ON DELETE CASCADE,
    idx            integer     NOT NULL,
    role           text        NOT NULL CHECK (role IN ('agent', 'caller')),
    text_redacted  text        NOT NULL,
    stt_ms         integer,
    llm_ms         integer,
    tts_ms         integer,
    net_ms         integer,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (call_id, idx)
);

-- One row per tool call, written by core-api. This is the table the
-- "no action_* without prior verification" test reads (PLAN 5.1).
CREATE TABLE IF NOT EXISTS audit_log (
    id             bigserial PRIMARY KEY,
    call_id        uuid        REFERENCES calls (call_id) ON DELETE CASCADE,
    tool           text        NOT NULL,
    args_redacted  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    result         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    state_at_call  text,
    ts             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_call_idx ON audit_log (call_id, ts);

-- Sandbox spend guardrails: one row per visitor per day.
CREATE TABLE IF NOT EXISTS sandbox_sessions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    visitor_id    text        NOT NULL,
    ip_hash       text,
    minutes_used  numeric(6, 2) NOT NULL DEFAULT 0,
    day           date        NOT NULL DEFAULT current_date,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (visitor_id, day)
);
