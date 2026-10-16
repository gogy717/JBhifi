-- Business rules that a column or table constraint can't express, because they read other rows or
-- other tables. Every trigger raises SQLSTATE 23514 (check_violation) with CONSTRAINT = 'brNN_…',
-- so to the API a trigger rule looks exactly like a CHECK violation (e.diag.constraint_name).
-- Where two concurrent transactions could both pass a check, the trigger first locks a row they both
-- need (SELECT … FOR UPDATE, or FOR SHARE when only a change to that row has to wait, as in BR06), so
-- the checks run one after the other.

-- ---------------------------------------------------------------- BR06
-- Click & Collect orders are collected at a retail store. store_type lives in another table, so the rule
-- has a guard on each side, as BR15 does: an order checks its store, and a store that has Click & Collect
-- orders can't stop being retail. Both raise br06_collect_at_retail_store.

CREATE FUNCTION br06_check_collect_store() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    collect_store_type TEXT;
BEGIN
    IF NEW.fulfilment_method = 'click_collect' THEN
        -- FOR SHARE: a shared lock on the store row until this transaction ends. A change to the store
        -- waits for this order to commit, and an order that arrives while a change is uncommitted waits
        -- for it, then reads the new type. Orders at the same store don't wait for each other: shared
        -- locks are compatible.
        SELECT store_type INTO collect_store_type
        FROM store
        WHERE store_id = NEW.fulfilling_store_id
        FOR SHARE;
        IF collect_store_type <> 'retail' THEN        -- no such store (NULL): customer_order_store_fk says so
            RAISE EXCEPTION 'Click & Collect orders must be collected from a retail store'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br06_collect_at_retail_store';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br06_collect_at_retail_store
    BEFORE INSERT OR UPDATE OF fulfilment_method, fulfilling_store_id ON customer_order
    FOR EACH ROW EXECUTE FUNCTION br06_check_collect_store();

-- The store side needs no lock of its own: its UPDATE locks the store row, so it first waits for any order
-- holding FOR SHARE on it; then this query, which takes a fresh snapshot under READ COMMITTED, sees that
-- order.
CREATE FUNCTION br06_check_store_type() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.store_type <> 'retail'
       AND EXISTS (SELECT 1
                   FROM customer_order
                   WHERE fulfilling_store_id = NEW.store_id
                     AND fulfilment_method = 'click_collect') THEN
        RAISE EXCEPTION 'Store % has Click & Collect orders, so it must stay a retail store', NEW.store_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br06_collect_at_retail_store';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br06_store_stays_retail
    BEFORE UPDATE OF store_type ON store
    FOR EACH ROW EXECUTE FUNCTION br06_check_store_type();

-- ---------------------------------------------------------------- BR07
-- An order is for products that are still on sale, and has at least one line. (A positive quantity and
-- each product once per order: CHECK and UNIQUE in 01_tables.sql.)

-- No lock on the product: a product retired while a checkout is running can still be sold by that
-- checkout, which read it while it was on sale. The rule holds at the moment of sale.
CREATE FUNCTION br07_check_product_on_sale() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- A product that doesn't exist matches nothing here: order_line_product_fk says so.
    IF EXISTS (SELECT 1 FROM product WHERE product_id = NEW.product_id AND NOT is_active) THEN
        RAISE EXCEPTION 'Product % is no longer sold', NEW.product_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br07_product_on_sale';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br07_product_on_sale
    BEFORE INSERT ON order_line
    FOR EACH ROW EXECUTE FUNCTION br07_check_product_on_sale();

-- An order's lines are inserted after the order (they refer to it), so "has a line" can't be checked when
-- the order row goes in. A constraint trigger declared DEFERRABLE INITIALLY DEFERRED runs at COMMIT, once
-- the whole order is in; lines are never deleted (BR08), so it stays true. Beyond Week 10 (optional, plan
-- T-8): without it, BR20 still refuses to mark an order without lines paid.
CREATE FUNCTION br07_check_order_has_lines() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM order_line WHERE order_id = NEW.order_id) THEN
        RAISE EXCEPTION 'Order % has no lines: an order is for at least one product', NEW.order_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br07_order_has_lines';
    END IF;
    RETURN NULL;                                      -- an AFTER trigger's result is ignored
END $$;

CREATE CONSTRAINT TRIGGER br07_order_has_lines
    AFTER INSERT ON customer_order
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION br07_check_order_has_lines();

-- ---------------------------------------------------------------- BR08
-- An order line is a purchase record. Lines are added only while their order is placed (once it is paid,
-- BR20 has checked the charge against exactly these lines), and a line is never changed or deleted, not
-- even while its order is placed. One function raises both BR08 codes, so a unit-price change is always
-- reported as br08_unit_price_immutable, whatever else the UPDATE does. TRUNCATE skips row triggers: see
-- the append-only section at the end of this file.

CREATE FUNCTION br08_guard_order_line() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_status order_status;
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Locking the order serialises this INSERT with placed → paid, which locks the same row: either
        -- the move waits and BR20 counts this line, or this INSERT waits and then sees the order paid.
        SELECT status INTO parent_status FROM customer_order WHERE order_id = NEW.order_id
        FOR UPDATE;
        IF parent_status <> 'placed' THEN             -- no such order (NULL): order_line_order_fk says so
            RAISE EXCEPTION 'Order % is %: lines can only be added while it is placed', NEW.order_id, parent_status
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br08_order_line_immutable';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF NEW.unit_price IS DISTINCT FROM OLD.unit_price THEN
            RAISE EXCEPTION 'An order line keeps the price it was sold at'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br08_unit_price_immutable';
        END IF;
        IF (NEW.order_id, NEW.line_no, NEW.product_id, NEW.quantity)
           IS NOT DISTINCT FROM (OLD.order_id, OLD.line_no, OLD.product_id, OLD.quantity) THEN
            RETURN NEW;                               -- nothing changes
        END IF;
    END IF;

    RAISE EXCEPTION 'An order line is a purchase record: it can''t be changed or deleted'
        USING ERRCODE = 'check_violation', CONSTRAINT = 'br08_order_line_immutable';
END $$;

CREATE TRIGGER br08_order_line_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON order_line
    FOR EACH ROW EXECUTE FUNCTION br08_guard_order_line();

-- ---------------------------------------------------------------- BR09
-- Order status follows the transitions allowed for its fulfilment method, and every change is logged.

INSERT INTO order_status_transition (fulfilment_method, from_status, to_status) VALUES
    ('delivery',      'placed',  'paid'),
    ('delivery',      'placed',  'cancelled'),
    ('delivery',      'paid',    'picking'),
    ('delivery',      'paid',    'cancelled'),
    ('delivery',      'picking', 'shipped'),
    ('delivery',      'shipped', 'delivered'),
    ('click_collect', 'placed',  'paid'),
    ('click_collect', 'placed',  'cancelled'),
    ('click_collect', 'paid',    'picking'),
    ('click_collect', 'paid',    'cancelled'),
    ('click_collect', 'picking', 'ready'),
    ('click_collect', 'ready',   'collected'),
    ('click_collect', 'ready',   'cancelled');      -- not collected in time

CREATE FUNCTION br09_check_status_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'placed' THEN
            RAISE EXCEPTION 'A new order starts as placed, not %', NEW.status
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br09_order_status_transition';
        END IF;
    ELSIF NEW.status IS DISTINCT FROM OLD.status
          AND NOT EXISTS (SELECT 1
                          FROM order_status_transition t
                          WHERE t.fulfilment_method = NEW.fulfilment_method
                            AND t.from_status = OLD.status
                            AND t.to_status = NEW.status) THEN
        RAISE EXCEPTION 'A % order cannot move from % to %', NEW.fulfilment_method, OLD.status, NEW.status
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br09_order_status_transition';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br09_order_status_transition
    BEFORE INSERT OR UPDATE OF status ON customer_order
    FOR EACH ROW EXECUTE FUNCTION br09_check_status_transition();

-- R11: the staff member making the change is read from the transaction-local setting app.staff_id,
-- which a service sets with set_config('app.staff_id', '<id>', true) before its UPDATE.
-- Unset means the customer or the system made the change.
CREATE FUNCTION br09_log_status_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    previous order_status;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
            RETURN NULL;                              -- status was SET to the same value
        END IF;
        previous := OLD.status;
    END IF;

    INSERT INTO order_status_history (order_id, seq, from_status, to_status, changed_by_staff_id)
    SELECT NEW.order_id, COALESCE(max(h.seq), 0) + 1, previous, NEW.status,
           NULLIF(current_setting('app.staff_id', true), '')::int
    FROM order_status_history h
    WHERE h.order_id = NEW.order_id;
    RETURN NULL;
END $$;

CREATE TRIGGER br09_log_status_change
    AFTER INSERT OR UPDATE OF status ON customer_order
    FOR EACH ROW EXECUTE FUNCTION br09_log_status_change();

-- Only an order's status moves. Who ordered, how and where it is fulfilled, the delivery address, the
-- retry key and when it was placed are fixed, so an UPDATE can't re-point an order at another customer,
-- store or address. BEFORE UPDATE triggers fire in name order, so this one runs before
-- br09_order_status_transition and br20_paid_in_full.
CREATE FUNCTION br09_block_order_header_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.order_id, NEW.customer_id, NEW.idempotency_key, NEW.fulfilment_method,
        NEW.fulfilling_store_id, NEW.delivery_address_no, NEW.placed_at)
       IS DISTINCT FROM
       (OLD.order_id, OLD.customer_id, OLD.idempotency_key, OLD.fulfilment_method,
        OLD.fulfilling_store_id, OLD.delivery_address_no, OLD.placed_at) THEN
        RAISE EXCEPTION 'Only an order''s status can change: who, how, where and when it was placed are fixed'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br09_order_header_immutable';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br09_order_header_immutable
    BEFORE UPDATE ON customer_order
    FOR EACH ROW EXECUTE FUNCTION br09_block_order_header_change();

-- Only br09_log_status_change writes the history. Inside this trigger pg_trigger_depth() is 1 when someone
-- INSERTs directly, and 2 or more when the INSERT comes from the log trigger (a trigger firing a trigger).
-- Beyond Week 10 (optional, plan T-8): it can tell only that *a* trigger is writing, not which one; the two
-- CHECKs on order_status_history (01_tables.sql) hold whoever writes.
CREATE FUNCTION br09_check_history_writer() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF pg_trigger_depth() < 2 THEN
        RAISE EXCEPTION 'Order status history is written by the status-change trigger, not directly'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br09_history_written_by_trigger';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br09_history_written_by_trigger
    BEFORE INSERT ON order_status_history
    FOR EACH ROW EXECUTE FUNCTION br09_check_history_writer();

-- ---------------------------------------------------------------- BR11
-- Returns only for delivered or collected orders, within 30 days of completion.

CREATE FUNCTION br11_check_return_window() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    completed_at TIMESTAMPTZ;
BEGIN
    SELECT max(h.changed_at) INTO completed_at
    FROM customer_order o
    JOIN order_status_history h ON h.order_id = o.order_id AND h.to_status = o.status
    WHERE o.order_id = NEW.order_id
      AND o.status IN ('delivered', 'collected');

    IF completed_at IS NULL THEN
        RAISE EXCEPTION 'Only delivered or collected orders can be returned'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br11_return_window';
    END IF;
    IF NEW.requested_at > completed_at + interval '30 days' THEN
        RAISE EXCEPTION 'The 30-day return window for order % closed on %',
                        NEW.order_id, (completed_at + interval '30 days')::date
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br11_return_window';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br11_return_window
    BEFORE INSERT OR UPDATE OF order_id, requested_at ON return_request
    FOR EACH ROW EXECUTE FUNCTION br11_check_return_window();

-- ---------------------------------------------------------------- BR12
-- The quantity returned from an order line (over all non-rejected returns) never exceeds the quantity
-- bought. This is an assertion over many rows, which PostgreSQL doesn't support, so a trigger emulates it.

CREATE FUNCTION br12_check_return_quantity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    purchased INT;
    returned  INT;
BEGIN
    SELECT quantity INTO purchased
    FROM order_line
    WHERE order_id = NEW.order_id AND line_no = NEW.line_no
    FOR UPDATE;                                       -- serialise concurrent returns of this line

    SELECT COALESCE(sum(rl.quantity), 0) INTO returned
    FROM return_line rl
    JOIN return_request rr ON rr.return_id = rl.return_id
    WHERE rl.order_id = NEW.order_id
      AND rl.line_no = NEW.line_no
      AND rr.status <> 'rejected'
      AND rl.return_id <> NEW.return_id;              -- on UPDATE, don't count this row's old quantity

    IF returned + NEW.quantity > purchased THEN
        RAISE EXCEPTION 'Order % line %: % bought, % already returned, % more requested',
                        NEW.order_id, NEW.line_no, purchased, returned, NEW.quantity
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br12_return_qty_within_purchased';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br12_return_qty_within_purchased
    BEFORE INSERT OR UPDATE OF quantity, order_id, line_no ON return_line
    FOR EACH ROW EXECUTE FUNCTION br12_check_return_quantity();

-- Return status flow: requested → received → refunded or rejected. A return is rejected only once it has
-- been received, so a rejection always names the store that saw the item. Refunded and rejected are final;
-- re-opening a rejected return would slip past BR12.
CREATE FUNCTION check_return_status_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'requested' THEN
            RAISE EXCEPTION 'A new return starts as requested, not %', NEW.status
                USING ERRCODE = 'check_violation', CONSTRAINT = 'return_status_transition';
        END IF;
    ELSIF NEW.status IS DISTINCT FROM OLD.status
          AND NOT ((OLD.status = 'requested' AND NEW.status = 'received')
                OR (OLD.status = 'received'  AND NEW.status IN ('refunded', 'rejected'))) THEN
        RAISE EXCEPTION 'A return cannot move from % to %', OLD.status, NEW.status
            USING ERRCODE = 'check_violation', CONSTRAINT = 'return_status_transition';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER return_status_transition
    BEFORE INSERT OR UPDATE OF status ON return_request
    FOR EACH ROW EXECUTE FUNCTION check_return_status_transition();

-- ---------------------------------------------------------------- BR14
-- Refunds for an order never exceed what was charged. (Once per return: UNIQUE in 01_tables.sql.)

CREATE FUNCTION br14_check_refund_total() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    charged  NUMERIC(10,2);
    refunded NUMERIC(10,2);
BEGIN
    IF NEW.kind = 'refund' THEN
        PERFORM 1 FROM customer_order WHERE order_id = NEW.order_id
        FOR UPDATE;                                   -- serialise concurrent refunds of this order

        SELECT COALESCE(sum(CASE WHEN kind = 'charge' THEN amount END), 0),
               COALESCE(sum(CASE WHEN kind = 'refund' THEN amount END), 0)
        INTO charged, refunded
        FROM payment
        WHERE order_id = NEW.order_id
          AND payment_id <> NEW.payment_id;

        IF refunded + NEW.amount > charged THEN
            RAISE EXCEPTION 'Refunds for order % would total % but only % was charged',
                            NEW.order_id, refunded + NEW.amount, charged
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_refunds_within_charged';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br14_refunds_within_charged
    BEFORE INSERT OR UPDATE OF kind, amount, order_id ON payment
    FOR EACH ROW EXECUTE FUNCTION br14_check_refund_total();

-- ---------------------------------------------------------------- BR15
-- A promotion's sale price is below the product's base price, and one product's promotions never
-- overlap. An exclusion constraint could do the overlap part declaratively, but needs the btree_gist
-- extension (beyond the unit), so a trigger does it.

CREATE FUNCTION br15_check_promotion() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    base NUMERIC(10,2);
BEGIN
    -- Locking the product serialises concurrent promotions for it, and stops its base price
    -- changing under this check (see br15_check_base_price below).
    SELECT base_price INTO base FROM product WHERE product_id = NEW.product_id
    FOR UPDATE;

    IF NEW.sale_price >= base THEN
        RAISE EXCEPTION 'Sale price % must be below the base price %', NEW.sale_price, base
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br15_promotion_below_base_price';
    END IF;

    IF EXISTS (SELECT 1
               FROM promotion p
               WHERE p.product_id = NEW.product_id
                 AND p.promotion_id <> NEW.promotion_id
                 AND p.starts_at < NEW.ends_at
                 AND NEW.starts_at < p.ends_at) THEN
        RAISE EXCEPTION 'This product already has a promotion in that period'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br15_promotion_no_overlap';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br15_promotion_rules
    BEFORE INSERT OR UPDATE ON promotion
    FOR EACH ROW EXECUTE FUNCTION br15_check_promotion();

-- The same rule seen from the product side: a rule that spans two tables needs a guard on both.
-- Lowering a base price must not leave a current or upcoming promotion at or above it.
CREATE FUNCTION br15_check_base_price() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1
               FROM promotion
               WHERE product_id = NEW.product_id
                 AND ends_at > now()
                 AND sale_price >= NEW.base_price) THEN
        RAISE EXCEPTION 'Base price % is not above the sale price of a current or upcoming promotion',
                        NEW.base_price
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br15_promotion_below_base_price';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br15_base_price_above_promotions
    BEFORE UPDATE OF base_price ON product
    FOR EACH ROW EXECUTE FUNCTION br15_check_base_price();

-- ---------------------------------------------------------------- BR16
-- Addresses are immutable (orders point at them); only is_active may change.

CREATE FUNCTION br16_block_address_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.customer_id, NEW.address_no, NEW.line1, NEW.suburb, NEW.state, NEW.postcode)
       IS DISTINCT FROM (OLD.customer_id, OLD.address_no, OLD.line1, OLD.suburb, OLD.state, OLD.postcode) THEN
        RAISE EXCEPTION 'Addresses cannot be edited: deactivate this one and add a new address'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br16_address_immutable';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br16_address_immutable
    BEFORE UPDATE ON customer_address
    FOR EACH ROW EXECUTE FUNCTION br16_block_address_change();

-- ---------------------------------------------------------------- BR17
-- A delivery goes to one of the customer's current addresses. Whose address it is: the composite FK
-- br17_order_address_is_customers (01_tables.sql). A retired address stays for the orders that used it
-- (BR16), but no new order may use it. No lock, as for BR07's products: the rule holds when the order is
-- placed.

CREATE FUNCTION br17_check_address_active() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- A missing address, or another customer's, matches nothing here: the composite FK says so. A Click &
    -- Collect order with an address is left to the CHECK br06_order_address_matches_method.
    IF NEW.fulfilment_method = 'delivery'
       AND EXISTS (SELECT 1
                   FROM customer_address
                   WHERE customer_id = NEW.customer_id
                     AND address_no = NEW.delivery_address_no
                     AND NOT is_active) THEN
        RAISE EXCEPTION 'Address % has been retired: choose a current address', NEW.delivery_address_no
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br17_order_address_active';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br17_order_address_active
    BEFORE INSERT ON customer_order
    FOR EACH ROW EXECUTE FUNCTION br17_check_address_active();

-- ---------------------------------------------------------------- BR18
-- The stock adjustment log is append-only: mistakes are fixed by a correcting adjustment.

CREATE FUNCTION br18_block_adjustment_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Stock adjustments are an audit log: record a correcting adjustment instead'
        USING ERRCODE = 'check_violation', CONSTRAINT = 'br18_adjustment_append_only';
END $$;

CREATE TRIGGER br18_adjustment_append_only
    BEFORE UPDATE OR DELETE ON stock_adjustment
    FOR EACH ROW EXECUTE FUNCTION br18_block_adjustment_change();

-- ---------------------------------------------------------------- BR20
-- An order is paid only when it has lines and its charge is exactly its total. That is an assertion over
-- three tables (customer_order, order_line, payment), which PostgreSQL doesn't support, so triggers
-- emulate it (as for BR12). It is checked on the one change where it starts to matter, placed → paid, and
-- stays true afterwards because nothing it reads can change once the order is paid: lines are added only
-- while it is placed (BR08), it is charged only while placed and at most once (below, and the partial
-- unique index br20_one_charge_per_order in 01_tables.sql), and payments are never updated or deleted
-- (the append-only section at the end of this file).
-- The order-row locks rely on READ COMMITTED, the project's isolation level: once a statement has waited
-- for the lock, the trigger's next query takes a fresh snapshot and sees what the other transaction
-- committed. (At REPEATABLE READ it would read its older snapshot and could miss a new line.)

-- A charge is taken only while the order is placed. Locking the order serialises this INSERT with
-- placed → paid, which locks the same row, so the two can't both act on a stale status.
CREATE FUNCTION br20_check_charge() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_status order_status;
BEGIN
    IF NEW.kind = 'charge' THEN
        SELECT status INTO parent_status FROM customer_order WHERE order_id = NEW.order_id
        FOR UPDATE;
        IF parent_status <> 'placed' THEN             -- no such order (NULL): payment_order_fk says so
            RAISE EXCEPTION 'Order % is %: it can only be charged while it is placed', NEW.order_id, parent_status
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br20_charge_while_placed';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br20_charge_while_placed
    BEFORE INSERT ON payment
    FOR EACH ROW EXECUTE FUNCTION br20_check_charge();

-- v_order_total is created in 03_views.sql. PL/pgSQL looks names up when the function first runs, not
-- when it is created, so the file order doesn't matter.
CREATE FUNCTION br20_check_paid_in_full() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    lines   BIGINT;
    due     NUMERIC(10,2);
    charged NUMERIC(10,2);
BEGIN
    IF OLD.status = 'placed' AND NEW.status = 'paid' THEN
        SELECT line_count, total INTO lines, due
        FROM v_order_total
        WHERE order_id = NEW.order_id;

        SELECT COALESCE(sum(amount), 0) INTO charged
        FROM payment
        WHERE order_id = NEW.order_id AND kind = 'charge';

        IF lines = 0 OR charged <> due THEN
            RAISE EXCEPTION 'Order % can''t be paid: % line(s), % due, % charged', NEW.order_id, lines, due, charged
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br20_paid_in_full';
        END IF;
    END IF;
    RETURN NEW;
END $$;

-- Named br20_…, so it fires after br09_order_header_immutable and br09_order_status_transition: an
-- illegal move is reported as BR09 before BR20 looks at the money.
CREATE TRIGGER br20_paid_in_full
    BEFORE UPDATE OF status ON customer_order
    FOR EACH ROW EXECUTE FUNCTION br20_check_paid_in_full();

-- ---------------------------------------------------------------- append-only records
-- The payment ledger (BR14), the status history (BR09), the stock adjustment log (BR18) and order lines
-- (BR08) are records: a mistake is corrected by a new row, never by editing or deleting one. One function
-- serves every trigger below; the rule it reports is the trigger's argument (TG_ARGV[0]).
-- Row triggers don't fire on TRUNCATE, so each of the four tables also gets a statement-level BEFORE
-- TRUNCATE trigger; TRUNCATE … CASCADE fires those of every table it reaches, so emptying customer_order
-- that way is refused too. (BR08's and BR18's row triggers are in their own sections above.)

CREATE FUNCTION block_append_only_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are a permanent record: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'check_violation', CONSTRAINT = TG_ARGV[0];
END $$;

CREATE TRIGGER br14_payment_append_only
    BEFORE UPDATE OR DELETE ON payment
    FOR EACH ROW EXECUTE FUNCTION block_append_only_change('br14_payment_append_only');

CREATE TRIGGER br09_history_append_only
    BEFORE UPDATE OR DELETE ON order_status_history
    FOR EACH ROW EXECUTE FUNCTION block_append_only_change('br09_history_append_only');

CREATE TRIGGER br14_payment_append_only_truncate
    BEFORE TRUNCATE ON payment
    FOR EACH STATEMENT EXECUTE FUNCTION block_append_only_change('br14_payment_append_only');

CREATE TRIGGER br09_history_append_only_truncate
    BEFORE TRUNCATE ON order_status_history
    FOR EACH STATEMENT EXECUTE FUNCTION block_append_only_change('br09_history_append_only');

CREATE TRIGGER br18_adjustment_append_only_truncate
    BEFORE TRUNCATE ON stock_adjustment
    FOR EACH STATEMENT EXECUTE FUNCTION block_append_only_change('br18_adjustment_append_only');

CREATE TRIGGER br08_order_line_immutable_truncate
    BEFORE TRUNCATE ON order_line
    FOR EACH STATEMENT EXECUTE FUNCTION block_append_only_change('br08_order_line_immutable');

-- ===== SP2: fulfilment & cancellation =====

-- ---------------------------------------------------------------- BR14: cancellation refunds
-- A refund without a return is the order's cancellation refund (T4, app/services/fulfilment.py). It is taken
-- only while BR09's transition table still lets the order move to cancelled, so a completed or already
-- cancelled order can't take one, and a second one can't follow the cancellation. The order row is locked
-- first, as br14_refunds_within_charged does, so the status it reads can't change before COMMIT.
CREATE FUNCTION br14_check_cancellation_refund() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent customer_order%ROWTYPE;
BEGIN
    IF NEW.kind = 'refund' AND NEW.return_id IS NULL THEN
        SELECT * INTO parent FROM customer_order WHERE order_id = NEW.order_id
        FOR UPDATE;
        IF NOT FOUND THEN
            RETURN NEW;                               -- no such order: payment_order_fk says so
        END IF;
        IF NOT EXISTS (SELECT 1
                       FROM order_status_transition t
                       WHERE t.fulfilment_method = parent.fulfilment_method
                         AND t.from_status = parent.status
                         AND t.to_status = 'cancelled') THEN
            RAISE EXCEPTION 'Order % is %: a refund without a return is only for an order being cancelled',
                            NEW.order_id, parent.status
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_refund_without_return_is_cancellation';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br14_refund_without_return_is_cancellation
    BEFORE INSERT ON payment
    FOR EACH ROW EXECUTE FUNCTION br14_check_cancellation_refund();

-- ---------------------------------------------------------------- BR21
-- A cancelled order keeps none of the customer's money: it moves to cancelled only when its refunds equal its
-- charges — the mirror of BR20 (paid only when charged exactly the total). Named br21_…, so it fires after the
-- br09_ triggers: an illegal move is reported as BR09 first. The UPDATE holds the order row, and every payment
-- INSERT locks that row first (the BR14 and BR20 triggers), so no payment can slip in before COMMIT.
CREATE FUNCTION br21_check_cancelled_refunded() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    held NUMERIC(10,2);
BEGIN
    IF NEW.status = 'cancelled' AND OLD.status IS DISTINCT FROM 'cancelled' THEN
        SELECT balance INTO held FROM v_order_payment WHERE order_id = NEW.order_id;
        IF held <> 0 THEN
            RAISE EXCEPTION 'Order % can''t be cancelled while % of what was charged is still held',
                            NEW.order_id, held
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br21_cancelled_order_refunded';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br21_cancelled_order_refunded
    BEFORE UPDATE OF status ON customer_order
    FOR EACH ROW EXECUTE FUNCTION br21_check_cancelled_refunded();

-- ===== SP3: returns =====

-- ---------------------------------------------------------------- BR14 (widened)
-- A refund for a return is exactly what that return is worth: the prices its items were bought at
-- (v_return_value, 03_views.sql). Refunds without a return_id (a cancelled order's refund) are not this
-- rule's business; a return that doesn't exist is reported by payment_return_same_order.

CREATE FUNCTION br14_check_refund_matches_return() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    worth NUMERIC(10,2);
BEGIN
    IF NEW.kind = 'refund' AND NEW.return_id IS NOT NULL THEN
        SELECT value INTO worth FROM v_return_value WHERE return_id = NEW.return_id;
        IF FOUND AND NEW.amount <> worth THEN
            RAISE EXCEPTION 'Return % is worth %, so its refund can''t be %', NEW.return_id, worth, NEW.amount
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_refund_matches_return';
        END IF;
    END IF;
    RETURN NEW;
END $$;

-- payment is append-only (br14_payment_append_only), so checking each INSERT is enough. Named br14_refund_…,
-- so it runs before br14_refunds_within_charged: a wrong amount is reported as this rule, not as the cap.
CREATE TRIGGER br14_refund_matches_return
    BEFORE INSERT ON payment
    FOR EACH ROW EXECUTE FUNCTION br14_check_refund_matches_return();

-- ---------------------------------------------------------------- BR22
-- When a return is received, the store receiving it is a retail store. Unlike BR06 this is a fact about one
-- moment, not a standing state, so there is no store-side guard: a store that later changes type doesn't undo
-- the receipts it made. FOR SHARE, as in BR06: a concurrent change of this store's type waits for the receipt.

CREATE FUNCTION br22_check_receiving_store() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    receiving_store_type TEXT;
BEGIN
    IF NEW.received_store_id IS NOT NULL THEN
        SELECT store_type INTO receiving_store_type
        FROM store
        WHERE store_id = NEW.received_store_id
        FOR SHARE;
        IF receiving_store_type <> 'retail' THEN      -- no such store (NULL): return_request_store_fk says so
            RAISE EXCEPTION 'Returns are received at a retail store'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br22_return_received_at_retail_store';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br22_return_received_at_retail_store
    BEFORE INSERT OR UPDATE OF received_store_id ON return_request
    FOR EACH ROW EXECUTE FUNCTION br22_check_receiving_store();

-- ---------------------------------------------------------------- BR14 (widened): a return's lines are fixed
-- A refund is checked against its return's value when it is paid (br14_refund_matches_return); the lines that
-- value comes from never change after the request, so the two can't part afterwards. As for order lines
-- (BR08), lines are only ever inserted. Consequence: a return with lines can't be deleted either (the
-- ON DELETE CASCADE from return_request can't fire).
CREATE TRIGGER br14_return_line_immutable
    BEFORE UPDATE OR DELETE ON return_line
    FOR EACH ROW EXECUTE FUNCTION block_append_only_change('br14_return_line_immutable');

CREATE TRIGGER br14_return_line_immutable_truncate
    BEFORE TRUNCATE ON return_line
    FOR EACH STATEMENT EXECUTE FUNCTION block_append_only_change('br14_return_line_immutable');
