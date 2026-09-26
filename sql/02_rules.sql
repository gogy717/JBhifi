-- Business rules that a column or table constraint can't express, because they read other rows or
-- other tables. Every trigger raises SQLSTATE 23514 (check_violation) with CONSTRAINT = 'brNN_…',
-- so to the API a trigger rule looks exactly like a CHECK violation (e.diag.constraint_name).
-- Where two concurrent transactions could both pass a check, the trigger first locks a parent row
-- (SELECT … FOR UPDATE) so the checks run one after the other.

-- ---------------------------------------------------------------- BR06
-- Click & Collect orders are collected at a retail store. store_type lives in another table.

CREATE FUNCTION br06_check_collect_store() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.fulfilment_method = 'click_collect'
       AND (SELECT store_type FROM store WHERE store_id = NEW.fulfilling_store_id) <> 'retail' THEN
        RAISE EXCEPTION 'Click & Collect orders must be collected from a retail store'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br06_collect_at_retail_store';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br06_collect_at_retail_store
    BEFORE INSERT OR UPDATE OF fulfilment_method, fulfilling_store_id ON customer_order
    FOR EACH ROW EXECUTE FUNCTION br06_check_collect_store();

-- ---------------------------------------------------------------- BR08
-- An order line is a purchase record: it keeps the price it was sold at, its quantity and its product,
-- and it can only be assembled while the order is still being placed. One trigger function raises both
-- BR08 codes so a unit-price change is always reported as br08_unit_price_immutable, whatever else is
-- true about the row (the existing tests assert that exact name).

CREATE FUNCTION br08_guard_order_line() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_status order_status;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT status INTO parent_status FROM customer_order WHERE order_id = NEW.order_id FOR UPDATE;
        IF parent_status IS DISTINCT FROM 'placed' THEN
            RAISE EXCEPTION 'Lines can only be added while order % is being placed', NEW.order_id
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br08_order_line_immutable';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' AND NEW.unit_price IS DISTINCT FROM OLD.unit_price THEN
        RAISE EXCEPTION 'An order line keeps the price it was sold at'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br08_unit_price_immutable';
    END IF;

    -- Everything else about a line is fixed too: which order it is in, which line/product it is, and how
    -- many were bought. (The order is looked up through its current row so a stale OLD.status cannot help.)
    SELECT status INTO parent_status FROM customer_order WHERE order_id = OLD.order_id FOR UPDATE;
    IF TG_OP = 'DELETE' OR parent_status IS DISTINCT FROM 'placed'
       OR (NEW.order_id, NEW.line_no, NEW.product_id, NEW.quantity)
          IS DISTINCT FROM (OLD.order_id, OLD.line_no, OLD.product_id, OLD.quantity) THEN
        RAISE EXCEPTION 'An order line is a purchase record: only a placed order may be assembled'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br08_order_line_immutable';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br08_order_line_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON order_line
    FOR EACH ROW EXECUTE FUNCTION br08_guard_order_line();

-- The order header is a purchase record too: once placed, only its status may move (and that move is
-- checked by BR09). customer_id, fulfilment, address, idempotency key and placement time are fixed, so a
-- later UPDATE cannot re-point an order at another customer, store or address.

CREATE FUNCTION order_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.customer_id, NEW.idempotency_key, NEW.fulfilment_method, NEW.fulfilling_store_id,
        NEW.delivery_address_no, NEW.placed_at)
       IS DISTINCT FROM
       (OLD.customer_id, OLD.idempotency_key, OLD.fulfilment_method, OLD.fulfilling_store_id,
        OLD.delivery_address_no, OLD.placed_at) THEN
        RAISE EXCEPTION 'A placed order cannot be rewritten: only its status may change'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'order_immutable';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER order_immutable
    BEFORE UPDATE ON customer_order
    FOR EACH ROW EXECUTE FUNCTION order_immutable();

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
-- SECURITY DEFINER so the application role can let the trigger write the audit row without holding
-- INSERT on order_status_history itself. A fixed search_path stops a caller shadowing the table.
CREATE FUNCTION br09_log_status_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
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

-- ---------------------------------------------------------------- BR11
-- Returns only for delivered or collected orders, within 30 days of completion. The window is a pure
-- SQL predicate so the exact boundary can be tested without a fixture (30 days is inclusive; a
-- microsecond later is not), and `requested_at` is generated by the server so a caller cannot claim an
-- earlier request time.

CREATE FUNCTION return_request_is_in_window(completed_at TIMESTAMPTZ, requested_at TIMESTAMPTZ)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT requested_at >= completed_at AND requested_at <= completed_at + interval '30 days';
$$;

CREATE FUNCTION br11_check_return_window() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    completed_at TIMESTAMPTZ;
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- The time is the database's, never the caller's.
        NEW.requested_at := now();
    ELSIF NEW.requested_at IS DISTINCT FROM OLD.requested_at
          OR NEW.order_id IS DISTINCT FROM OLD.order_id THEN
        RAISE EXCEPTION 'A return keeps the order and request time it was created with'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br11_return_window';
    END IF;

    SELECT max(h.changed_at) INTO completed_at
    FROM customer_order o
    JOIN order_status_history h ON h.order_id = o.order_id AND h.to_status = o.status
    WHERE o.order_id = NEW.order_id
      AND o.status IN ('delivered', 'collected');

    IF completed_at IS NULL THEN
        RAISE EXCEPTION 'Only delivered or collected orders can be returned'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br11_return_window';
    END IF;
    IF NOT return_request_is_in_window(completed_at, NEW.requested_at) THEN
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
    request_status TEXT;
BEGIN
    -- A return line belongs to one request, order and order line for its whole life. Moving it would
    -- let a rejected request's quantity reappear on a live one without re-running the sum below.
    IF TG_OP = 'UPDATE'
       AND (NEW.return_id, NEW.order_id, NEW.line_no)
           IS DISTINCT FROM (OLD.return_id, OLD.order_id, OLD.line_no) THEN
        RAISE EXCEPTION 'A return line cannot move to another request, order or line'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br12_return_line_ownership';
    END IF;

    SELECT quantity INTO purchased
    FROM order_line
    WHERE order_id = NEW.order_id AND line_no = NEW.line_no
    FOR UPDATE;                                       -- serialise concurrent returns of this line

    SELECT status INTO request_status FROM return_request WHERE return_id = NEW.return_id FOR UPDATE;
    IF request_status IS DISTINCT FROM 'requested' THEN
        RAISE EXCEPTION 'Return % has already been received or closed, so its lines cannot change',
                        NEW.return_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br12_return_line_editable';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

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
    BEFORE INSERT OR UPDATE OR DELETE ON return_line
    FOR EACH ROW EXECUTE FUNCTION br12_check_return_quantity();

-- Return status flow: requested → received → refunded, and requested/received → rejected.
-- Refunded and rejected are final; re-opening a rejected return would slip past BR12.
CREATE FUNCTION check_return_status_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'requested' THEN
            RAISE EXCEPTION 'A new return starts as requested, not %', NEW.status
                USING ERRCODE = 'check_violation', CONSTRAINT = 'return_status_transition';
        END IF;
    ELSIF NEW.status IS DISTINCT FROM OLD.status
          AND NOT ((OLD.status = 'requested' AND NEW.status IN ('received', 'rejected'))
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
-- Refunds never exceed what was charged (UNIQUE per source in 01_tables.sql), and a refund's amount is
-- exactly what its source entitles: the returned lines at their purchase prices, or the balance left on
-- a cancelled order. The amount part is checked immediately; that the source really reached a completed
-- state is a deferred check, because the service may write the payment and the status in either order
-- inside one transaction (see the constraint triggers at the end of this file).

CREATE FUNCTION return_expected_refund(p_return_id INT) RETURNS NUMERIC LANGUAGE sql STABLE AS $$
    SELECT COALESCE(sum(rl.quantity * ol.unit_price), 0)
    FROM return_line rl
    JOIN order_line ol ON ol.order_id = rl.order_id AND ol.line_no = rl.line_no
    WHERE rl.return_id = p_return_id;
$$;

-- The money still captured on an order: charges minus every other refund (0 if the order was never charged).
CREATE FUNCTION order_captured_balance(p_order_id INT, p_exclude_payment_id INT) RETURNS NUMERIC
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(sum(CASE WHEN kind = 'charge' THEN amount ELSE -amount END), 0)
    FROM payment
    WHERE order_id = p_order_id AND payment_id IS DISTINCT FROM p_exclude_payment_id;
$$;

CREATE FUNCTION br14_check_refund() RETURNS trigger LANGUAGE plpgsql AS $$
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
          AND payment_id IS DISTINCT FROM NEW.payment_id;

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
    FOR EACH ROW EXECUTE FUNCTION br14_check_refund();

-- The exact amount is checked AFTER the row is in place, so a declarative constraint that also applies
-- (a second refund for the same return, say) is the one reported: AFTER triggers run after CHECKs and
-- UNIQUE indexes have had their say.
CREATE FUNCTION br14_check_refund_matches_source() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    due NUMERIC(10,2);
BEGIN
    IF NEW.kind <> 'refund' OR num_nonnulls(NEW.return_id, NEW.cancellation_id) <> 1 THEN
        RETURN NULL;                                  -- br14_refund_has_source reports this case
    END IF;
    IF NEW.return_id IS NOT NULL THEN
        due := return_expected_refund(NEW.return_id);
    ELSE
        -- A cancellation refunds what is left captured: the charges less any other refund.
        due := order_captured_balance(NEW.order_id, NEW.payment_id);
    END IF;
    IF NEW.amount <> due THEN
        RAISE EXCEPTION 'Refund % does not match its source: % is due', NEW.amount, due
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_refund_matches_source';
    END IF;
    RETURN NULL;
END $$;

CREATE TRIGGER br14_refund_matches_source
    AFTER INSERT OR UPDATE OF kind, amount, order_id, return_id, cancellation_id ON payment
    FOR EACH ROW EXECUTE FUNCTION br14_check_refund_matches_source();

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

-- ---------------------------------------------------------------- append-only records
-- The order timeline and the payment ledger are financial/audit records: once written they are never
-- rewritten or deleted. BR14's ceiling can only be trusted if a charge cannot be quietly reduced after a
-- refund was accepted against it. Both tables are written through triggers/services (the history trigger
-- is SECURITY DEFINER), never by editing rows, so blocking UPDATE and DELETE costs nothing.

CREATE FUNCTION record_is_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is an append-only record: correct it with a new row, not by editing history',
                    TG_TABLE_NAME
        USING ERRCODE = 'check_violation', CONSTRAINT = TG_TABLE_NAME || '_append_only';
END $$;

CREATE TRIGGER payment_append_only
    BEFORE UPDATE OR DELETE ON payment
    FOR EACH ROW EXECUTE FUNCTION record_is_append_only();

CREATE TRIGGER order_status_history_append_only
    BEFORE UPDATE OR DELETE ON order_status_history
    FOR EACH ROW EXECUTE FUNCTION record_is_append_only();

-- ---------------------------------------------------------------- category cycles
-- The category tree is recursive and is walked to arbitrary depth by the catalogue. A parent change that
-- put a category inside its own subtree would make that walk loop forever, so it is refused here.

CREATE FUNCTION category_no_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.parent_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        WITH RECURSIVE ancestors AS (
            SELECT NEW.parent_id AS category_id
            UNION                                            -- UNION (not ALL) also bounds a legacy cycle
            SELECT c.parent_id
            FROM category c
            JOIN ancestors a ON c.category_id = a.category_id
            WHERE c.parent_id IS NOT NULL
        )
        SELECT 1 FROM ancestors WHERE category_id = NEW.category_id
    ) THEN
        RAISE EXCEPTION 'Category % cannot be moved inside its own subtree', NEW.category_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'category_no_cycle';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER category_no_cycle
    BEFORE INSERT OR UPDATE OF parent_id ON category
    FOR EACH ROW EXECUTE FUNCTION category_no_cycle();

-- ---------------------------------------------------------------- R11 for returns
-- The return timeline mirrors the order timeline: written by a trigger, never by the caller, append-only.

CREATE FUNCTION log_return_status_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    previous TEXT;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
            RETURN NULL;                              -- a retry that sets the same status adds no history
        END IF;
        previous := OLD.status;
    END IF;

    INSERT INTO return_status_history (return_id, seq, from_status, to_status, changed_by_staff_id)
    SELECT NEW.return_id, COALESCE(max(h.seq), 0) + 1, previous, NEW.status,
           NULLIF(current_setting('app.staff_id', true), '')::int
    FROM return_status_history h
    WHERE h.return_id = NEW.return_id;
    RETURN NULL;
END $$;

CREATE TRIGGER return_status_history_log
    AFTER INSERT OR UPDATE OF status ON return_request
    FOR EACH ROW EXECUTE FUNCTION log_return_status_change();

CREATE TRIGGER return_status_history_append_only
    BEFORE UPDATE OR DELETE ON return_status_history
    FOR EACH ROW EXECUTE FUNCTION record_is_append_only();

-- A cancellation is a financial source record: append-only, like a payment.
CREATE TRIGGER order_cancellation_append_only
    BEFORE UPDATE OR DELETE ON order_cancellation
    FOR EACH ROW EXECUTE FUNCTION record_is_append_only();

-- ---------------------------------------------------------------- BR14 completion (deferred)
-- These run at COMMIT (or when a service asks for them with SET CONSTRAINTS ALL IMMEDIATE), so a service
-- may write the payment and move the status in whichever order reads best — but a half-finished financial
-- state can never commit.

CREATE FUNCTION br14_check_refund_source_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    source_status TEXT;
BEGIN
    IF NEW.kind <> 'refund' THEN
        RETURN NULL;
    END IF;
    IF NEW.return_id IS NOT NULL THEN
        SELECT status INTO source_status FROM return_request WHERE return_id = NEW.return_id;
        IF source_status IS DISTINCT FROM 'refunded' THEN
            RAISE EXCEPTION 'Refund % points at return %, which is % rather than refunded',
                            NEW.payment_id, NEW.return_id, COALESCE(source_status, 'missing')
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_source_complete';
        END IF;
    ELSIF NOT EXISTS (SELECT 1 FROM customer_order o
                      JOIN order_cancellation c ON c.order_id = o.order_id
                      WHERE c.cancellation_id = NEW.cancellation_id
                        AND o.order_id = NEW.order_id
                        AND o.status = 'cancelled') THEN
        RAISE EXCEPTION 'Refund % points at cancellation %, but order % is not cancelled',
                        NEW.payment_id, NEW.cancellation_id, NEW.order_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_source_complete';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER br14_refund_source_complete
    AFTER INSERT OR UPDATE ON payment
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION br14_check_refund_source_complete();

CREATE FUNCTION br14_check_return_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    expected NUMERIC(10,2);
    refunds  INT;
BEGIN
    IF NEW.status <> 'refunded' THEN
        RETURN NULL;
    END IF;
    expected := return_expected_refund(NEW.return_id);
    SELECT count(*) INTO refunds FROM payment WHERE return_id = NEW.return_id;
    IF expected > 0 AND refunds <> 1 THEN
        RAISE EXCEPTION 'Refunded return % is due % but has % refund(s)', NEW.return_id, expected, refunds
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_source_complete';
    END IF;
    IF expected = 0 AND refunds <> 0 THEN
        RAISE EXCEPTION 'Zero-value return % must not record a refund', NEW.return_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_source_complete';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER br14_return_complete
    AFTER INSERT OR UPDATE ON return_request
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION br14_check_return_complete();

CREATE FUNCTION br14_check_cancellation_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    balance       NUMERIC(10,2);
    refunds       INT;
    cancellations INT;
BEGIN
    IF NEW.status <> 'cancelled' THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO cancellations FROM order_cancellation WHERE order_id = NEW.order_id;
    IF cancellations <> 1 THEN
        RAISE EXCEPTION 'Cancelled order % must have exactly one cancellation record (it has %)',
                        NEW.order_id, cancellations
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_source_complete';
    END IF;
    -- Money captured before the cancellation: charges less any refund that came from a return.
    SELECT COALESCE(sum(CASE WHEN kind = 'charge' THEN amount ELSE -amount END), 0) INTO balance
    FROM payment WHERE order_id = NEW.order_id AND cancellation_id IS NULL;
    SELECT count(*) INTO refunds FROM payment
    WHERE order_id = NEW.order_id AND cancellation_id IS NOT NULL;
    IF balance > 0 AND refunds <> 1 THEN
        RAISE EXCEPTION 'Cancelled order % has % captured but % cancellation refund(s)',
                        NEW.order_id, balance, refunds
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_source_complete';
    END IF;
    IF balance <= 0 AND refunds <> 0 THEN
        RAISE EXCEPTION 'Cancelled order % has nothing captured, so it must not record a refund',
                        NEW.order_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_source_complete';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER br14_cancellation_complete
    AFTER UPDATE ON customer_order
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION br14_check_cancellation_complete();
