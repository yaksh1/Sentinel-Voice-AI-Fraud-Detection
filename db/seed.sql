-- Sentinel — seed data. One customer, one card. Idempotent.
--
--   psql "$DATABASE_URL_UNPOOLED" -f db/seed.sql
--
-- Fixed UUIDs so tests and the REPL can reference rows without a lookup.
-- Alex Rivera is the persona the agent addresses in the scripted demo; the
-- verify_challenge factors are last4 = 4242 and city_of_birth = Porto.

INSERT INTO customers (id, visitor_id, display_name, city_of_birth)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'seed-visitor',
    'Alex Rivera',
    'Porto'
)
ON CONFLICT (id) DO UPDATE
    SET display_name  = EXCLUDED.display_name,
        city_of_birth = EXCLUDED.city_of_birth;

INSERT INTO cards (id, customer_id, last4, brand, status)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000001',
    '4242',
    'visa',
    'active'
)
ON CONFLICT (id) DO UPDATE
    SET last4  = EXCLUDED.last4,
        brand  = EXCLUDED.brand,
        status = EXCLUDED.status;

-- The transaction the demo is about: BRIEF §4's "Pay $940 at Lisboa
-- Eletrónica". Held, not pending — the risk engine stops it before it settles.
-- 3.4 creates this through POST /checkout; seeding it is what lets 2.3 and 2.5
-- run before that endpoint exists.
INSERT INTO transactions (
    id, customer_id, card_id, amount_cents, currency,
    merchant_name, merchant_city, merchant_country, status
)
VALUES (
    '00000000-0000-0000-0000-000000000003',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000002',
    94000, 'USD',
    'Lisboa Eletrónica', 'Lisbon', 'PT',
    'held'
)
ON CONFLICT (id) DO UPDATE
    SET amount_cents  = EXCLUDED.amount_cents,
        merchant_name = EXCLUDED.merchant_name,
        merchant_city = EXCLUDED.merchant_city,
        status        = EXCLUDED.status,
        updated_at    = now();

INSERT INTO fraud_alerts (alert_id, txn_id, customer_id, risk_reasons, status)
VALUES (
    '00000000-0000-0000-0000-000000000004',
    '00000000-0000-0000-0000-000000000003',
    '00000000-0000-0000-0000-000000000001',
    '["foreign_merchant", "amount_over_threshold"]'::jsonb,
    'open'
)
ON CONFLICT (alert_id) DO UPDATE
    SET risk_reasons = EXCLUDED.risk_reasons,
        status       = EXCLUDED.status;
