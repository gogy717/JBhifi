-- The application role. The API connects as this role, not as the schema owner, so a bug or an
-- injection cannot rewrite history, delete a payment, or change the schema. The bootstrap (docker
-- entrypoint / the test fixture) still runs as the owner, which is what creates tables and roles.
--
-- The password is a local development default, matching docker-compose.yml's dev-only credentials; a
-- real deployment supplies it out of band (POSTGRES_APP_PASSWORD).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jbhifi_app') THEN
        CREATE ROLE jbhifi_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            PASSWORD 'apppassword';
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO jbhifi_app;

-- Read-only reference data.
GRANT SELECT ON store, staff, order_status_transition TO jbhifi_app;

-- The catalogue and its promotions: the admin screens create, edit and delete these.
GRANT SELECT, INSERT, UPDATE, DELETE ON category, brand, product, product_spec, promotion TO jbhifi_app;

-- Customers and their addresses: an address is retired (UPDATE is_active), never deleted (BR16).
GRANT SELECT, INSERT, UPDATE ON customer, customer_address TO jbhifi_app;

-- Stock: rows are created at zero and changed relatively (BR03). Manual changes are logged (BR18), and
-- the log is append-only, so the role may only append to it.
GRANT SELECT, INSERT, UPDATE ON inventory TO jbhifi_app;
GRANT SELECT, INSERT ON stock_adjustment TO jbhifi_app;

-- Orders: statuses move (BR09) and lines are assembled while the order is placed (BR08); the guard
-- triggers refuse anything else. UPDATE on order_line is also what lets the BR12 trigger take its row
-- lock.
GRANT SELECT, INSERT, UPDATE ON customer_order, return_request TO jbhifi_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON order_line, return_line TO jbhifi_app;

-- Append-only records, written by triggers and services: the role reads them, never edits them.
GRANT SELECT, INSERT ON payment TO jbhifi_app;
GRANT SELECT ON order_status_history TO jbhifi_app;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO jbhifi_app;

-- Derived data. A view has its own privilege, separate from the tables it reads.
GRANT SELECT ON v_product_current_price, v_order_total TO jbhifi_app;
