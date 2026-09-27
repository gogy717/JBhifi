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
-- An order line keeps the price it was sold at.

CREATE FUNCTION br08_block_unit_price_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.unit_price IS DISTINCT FROM OLD.unit_price THEN
        RAISE EXCEPTION 'An order line keeps the price it was sold at'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br08_unit_price_immutable';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br08_unit_price_immutable
    BEFORE UPDATE OF unit_price ON order_line
    FOR EACH ROW EXECUTE FUNCTION br08_block_unit_price_change();

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
