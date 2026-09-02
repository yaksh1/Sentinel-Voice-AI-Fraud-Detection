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
