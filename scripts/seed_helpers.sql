-- Seed helpers, embedded at the top of sql/20_seed_generated.sql by scripts/generate_seed.py.
--
-- Each helper does what its service does — T1 checkout (seed_order, seed_line, seed_pay), a status move
-- (seed_move), T4 cancel (seed_cancel), T3 stock received (seed_receive) — at a named time, with the same
-- statements, so every rule's trigger and constraint runs on every seeded row. Nothing is disabled.
--
-- They are temporary functions (schema pg_temp): they belong to the session that loads the file and disappear
-- when it ends, so nothing is added to the schema. A pg_temp function is always called by its full name.
-- Times come from seed_at, relative to the anchor: Sydney midnight on the day the file is loaded (the file sets
-- the time zone). BR09's log reads who and when from app.staff_id and app.changed_at, set here for this
-- transaction only (set_config(…, true)), exactly as the services set app.staff_id.

-- `days` days before the anchor, at `minutes` minutes past midnight on the local clock. With days ≥ 1 it is in the
-- past whenever the file is loaded. The arithmetic is done on the local date and clock (a date plus an interval is
-- a timestamp without time zone), then read as Sydney time: on the days daylight saving starts or ends, counting
-- elapsed minutes from midnight instead would put every later time an hour out. The plan keeps every event between
-- 07:00 and midnight, so none falls in the hour that doesn't exist when daylight saving starts.
-- seed.anchor, if set, stands in for the load date: tests replay the file as of other days with it.
CREATE FUNCTION pg_temp.seed_at(days int, minutes int) RETURNS timestamptz LANGUAGE sql STABLE AS $$
    SELECT (COALESCE(NULLIF(current_setting('seed.anchor', true), '')::date, current_date) - days
            + minutes * interval '1 minute')::timestamptz
$$;

-- A customer signs up (as a first sign-in does, app/auth.py) with their first address.
CREATE FUNCTION pg_temp.seed_customer(p_email text, p_name text, p_phone text, p_at timestamptz, p_line1 text,
                                      p_suburb text, p_state text, p_postcode text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO customer (email, full_name, phone, created_at) VALUES (p_email, p_name, p_phone, p_at);
    INSERT INTO customer_address (customer_id, address_no, line1, suburb, state, postcode)
    SELECT customer_id, 1, p_line1, p_suburb, p_state, p_postcode FROM customer WHERE email = p_email;
END $$;

-- A customer adds an address, and retires one (BR16: never edited; BR17: a retired one can't be ordered to).
CREATE FUNCTION pg_temp.seed_address(p_email text, p_no int, p_line1 text, p_suburb text, p_state text,
                                     p_postcode text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO customer_address (customer_id, address_no, line1, suburb, state, postcode)
    SELECT customer_id, p_no, p_line1, p_suburb, p_state, p_postcode FROM customer WHERE email = p_email;
    IF NOT FOUND THEN RAISE EXCEPTION 'seed: no customer %', p_email; END IF;
END $$;

CREATE FUNCTION pg_temp.seed_retire_address(p_email text, p_no int) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    UPDATE customer_address a SET is_active = FALSE
    FROM customer c
    WHERE c.email = p_email AND a.customer_id = c.customer_id AND a.address_no = p_no;
    IF NOT FOUND THEN RAISE EXCEPTION 'seed: no address % of %', p_no, p_email; END IF;
END $$;

-- T1 step 2: the order header, placed at p_at by the customer. BR06, BR10 and BR17 check it; BR09 logs row 1.
CREATE FUNCTION pg_temp.seed_order(p_order_id int, p_email text, p_key uuid, p_method text, p_store_id int,
                                   p_address_no int, p_at timestamptz) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM set_config('app.staff_id', '', true);
    PERFORM set_config('app.changed_at', p_at::text, true);
    INSERT INTO customer_order (order_id, customer_id, idempotency_key, fulfilment_method, fulfilling_store_id,
                                delivery_address_no, placed_at)
    SELECT p_order_id, customer_id, p_key, p_method, p_store_id, p_address_no, p_at
    FROM customer WHERE email = p_email;
    IF NOT FOUND THEN RAISE EXCEPTION 'seed: no customer %', p_email; END IF;
END $$;

-- T1 steps 3 and 5 for one line: priced as it was when the order was placed (the promotion running then, else
-- the base price; BR15 keeps a product's promotions from overlapping), then the stock is taken where the order is
-- fulfilled. The decrement is unconditional: BR03 (quantity ≥ 0) refuses an oversold seed.
CREATE FUNCTION pg_temp.seed_line(p_order_id int, p_line_no int, p_sku text, p_quantity int) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price)
    SELECT o.order_id, p_line_no, p.product_id, p_quantity,
           COALESCE((SELECT pr.sale_price FROM promotion pr
                     WHERE pr.product_id = p.product_id AND pr.starts_at <= o.placed_at AND o.placed_at < pr.ends_at),
                    p.base_price)
    FROM customer_order o, product p
    WHERE o.order_id = p_order_id AND p.sku = p_sku;
    IF NOT FOUND THEN RAISE EXCEPTION 'seed: order % or product % is missing', p_order_id, p_sku; END IF;

    UPDATE inventory i SET quantity = i.quantity - p_quantity
    FROM customer_order o, product p
    WHERE o.order_id = p_order_id AND p.sku = p_sku
      AND i.store_id = o.fulfilling_store_id AND i.product_id = p.product_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'seed: % is not ranged at the store of order %', p_sku, p_order_id; END IF;
END $$;

-- T1 steps 6 and 7: one charge of the total (none for a zero total), then placed → paid, both at placed_at as in
-- T1's single transaction. BR20 checks the charge equals the total.
CREATE FUNCTION pg_temp.seed_pay(p_order_id int) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_at timestamptz;
BEGIN
    SELECT placed_at INTO v_at FROM customer_order WHERE order_id = p_order_id;
    INSERT INTO payment (order_id, kind, amount, created_at)
    SELECT order_id, 'charge', total, v_at FROM v_order_total WHERE order_id = p_order_id AND total > 0;
    PERFORM set_config('app.staff_id', '', true);
    PERFORM set_config('app.changed_at', v_at::text, true);
    UPDATE customer_order SET status = 'paid' WHERE order_id = p_order_id;
END $$;

-- A status move by a staff member at p_at. BR09 checks it against the transition table and logs it.
CREATE FUNCTION pg_temp.seed_move(p_order_id int, p_status text, p_at timestamptz, p_staff_id int) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM set_config('app.staff_id', p_staff_id::text, true);
    PERFORM set_config('app.changed_at', p_at::text, true);
    UPDATE customer_order SET status = p_status WHERE order_id = p_order_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'seed: no order %', p_order_id; END IF;
END $$;

-- T4 steps 6–8 at p_at, by a staff member or (p_staff_id NULL) the customer: restock if checkout took stock, refund
-- what is held, then cancelled. BR14 allows the refund only while the order can be cancelled; BR21 checks that
-- nothing is held by then. Every product is ranged at every store (10_seed_reference.sql), so the rows exist.
CREATE FUNCTION pg_temp.seed_cancel(p_order_id int, p_at timestamptz, p_staff_id int) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_order customer_order%ROWTYPE;
    v_lines int;
    v_restocked int;
BEGIN
    SELECT * INTO v_order FROM customer_order WHERE order_id = p_order_id FOR UPDATE;
    IF v_order.status IN ('paid', 'ready') THEN
        SELECT count(*) INTO v_lines FROM order_line WHERE order_id = p_order_id;
        UPDATE inventory i SET quantity = i.quantity + l.quantity
        FROM order_line l
        WHERE l.order_id = p_order_id AND i.store_id = v_order.fulfilling_store_id AND i.product_id = l.product_id;
        GET DIAGNOSTICS v_restocked = ROW_COUNT;
        IF v_restocked <> v_lines THEN RAISE EXCEPTION 'seed: order % restocked % of % lines',
                                                         p_order_id, v_restocked, v_lines; END IF;
    END IF;
    INSERT INTO payment (order_id, kind, amount, created_at)
    SELECT order_id, 'refund', balance, p_at FROM v_order_payment WHERE order_id = p_order_id AND balance > 0;
    PERFORM set_config('app.staff_id', COALESCE(p_staff_id::text, ''), true);
    PERFORM set_config('app.changed_at', p_at::text, true);
    UPDATE customer_order SET status = 'cancelled' WHERE order_id = p_order_id;
END $$;

-- T3, reason received, at p_at: the relative UPDATE, then the log row with the quantity it left (BR18 checks the
-- staff member works at that store and that the reason fits the sign).
CREATE FUNCTION pg_temp.seed_receive(p_store_id int, p_sku text, p_delta int, p_staff_id int, p_at timestamptz)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_product int;
    v_after int;
BEGIN
    SELECT product_id INTO v_product FROM product WHERE sku = p_sku;
    UPDATE inventory SET quantity = quantity + p_delta
    WHERE store_id = p_store_id AND product_id = v_product
    RETURNING quantity INTO v_after;
    IF NOT FOUND THEN RAISE EXCEPTION 'seed: % is not ranged at store %', p_sku, p_store_id; END IF;
    INSERT INTO stock_adjustment (store_id, product_id, staff_id, delta, reason, note, quantity_after, adjusted_at)
    VALUES (p_store_id, v_product, p_staff_id, p_delta, 'received', 'Supplier delivery', v_after, p_at);
END $$;

-- ---------------------------------------------------------------- returns (app/services/returns.py)

-- A customer asks to return part of a completed order, at p_at; then its lines. BR11 compares requested_at with
-- the order's completion time in its history; BR12 (no more than bought, over non-rejected returns) and BR13
-- (lines of this order) check each line, and lines are never changed afterwards (br14_return_line_immutable).
CREATE FUNCTION pg_temp.seed_request_return(p_return_id int, p_order_id int, p_key uuid, p_reason text,
                                            p_at timestamptz) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO return_request (return_id, order_id, idempotency_key, reason, requested_at)
    VALUES (p_return_id, p_order_id, p_key, p_reason, p_at);
END $$;

CREATE FUNCTION pg_temp.seed_return_line(p_return_id int, p_line_no int, p_quantity int) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO return_line (return_id, line_no, order_id, quantity)
    SELECT return_id, p_line_no, order_id, p_quantity FROM return_request WHERE return_id = p_return_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'seed: no return %', p_return_id; END IF;
END $$;

-- The service's lock order for every staff action: the order FOR UPDATE, then the return FOR UPDATE.
CREATE FUNCTION pg_temp.seed_lock_return(p_return_id int) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM customer_order o JOIN return_request r ON r.order_id = o.order_id
    WHERE r.return_id = p_return_id
    FOR UPDATE OF o;
    PERFORM 1 FROM return_request WHERE return_id = p_return_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'seed: no return %', p_return_id; END IF;
END $$;

-- The item comes in at a store, taken in by one of its staff. BR22: a retail store.
CREATE FUNCTION pg_temp.seed_receive_return(p_return_id int, p_store_id int, p_staff_id int, p_at timestamptz)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_temp.seed_lock_return(p_return_id);
    UPDATE return_request
    SET status = 'received', received_store_id = p_store_id, processed_by_staff_id = p_staff_id, received_at = p_at
    WHERE return_id = p_return_id;
END $$;

-- T2 at p_at: restock at the receiving store (ascending product_id; make sure of the row, then a relative
-- UPDATE), one refund of what the return is worth (none if 0; BR14 checks it matches the return and stays within
-- the charge), then refunded by a staff member of the receiving store.
CREATE FUNCTION pg_temp.seed_refund_return(p_return_id int, p_staff_id int, p_at timestamptz) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_store int;
    v_line record;
BEGIN
    PERFORM pg_temp.seed_lock_return(p_return_id);
    SELECT received_store_id INTO v_store FROM return_request WHERE return_id = p_return_id;
    FOR v_line IN
        SELECT ol.product_id, rl.quantity
        FROM return_line rl JOIN order_line ol ON ol.order_id = rl.order_id AND ol.line_no = rl.line_no
        WHERE rl.return_id = p_return_id
        ORDER BY ol.product_id
    LOOP
        INSERT INTO inventory (store_id, product_id, quantity) VALUES (v_store, v_line.product_id, 0)
        ON CONFLICT ON CONSTRAINT inventory_pk DO NOTHING;
        UPDATE inventory SET quantity = quantity + v_line.quantity
        WHERE store_id = v_store AND product_id = v_line.product_id;
    END LOOP;
    INSERT INTO payment (order_id, kind, amount, return_id, created_at)
    SELECT order_id, 'refund', value, return_id, p_at FROM v_return_value WHERE return_id = p_return_id AND value > 0;
    UPDATE return_request SET status = 'refunded', resolved_by_staff_id = p_staff_id, resolved_at = p_at
    WHERE return_id = p_return_id;
END $$;

-- Refused once received, with the reason: nothing restocked, nothing refunded.
CREATE FUNCTION pg_temp.seed_reject_return(p_return_id int, p_staff_id int, p_at timestamptz, p_reason text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_temp.seed_lock_return(p_return_id);
    UPDATE return_request
    SET status = 'rejected', rejection_reason = p_reason, resolved_by_staff_id = p_staff_id, resolved_at = p_at
    WHERE return_id = p_return_id;
END $$;
