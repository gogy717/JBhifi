-- Derived data is computed by views, never stored, so it can't disagree with its source (plan T-2).

-- R2: the price a product sells for right now. BR15 allows at most one active promotion per product,
-- so the LEFT JOIN yields exactly one row per product.
CREATE VIEW v_product_current_price AS
SELECT p.product_id,
       p.base_price,
       pr.promotion_id,
       pr.sale_price,
       pr.ends_at                             AS promotion_ends_at,
       COALESCE(pr.sale_price, p.base_price)  AS current_price
FROM product p
LEFT JOIN promotion pr
       ON pr.product_id = p.product_id
      AND pr.starts_at <= now() AND now() < pr.ends_at;

CREATE VIEW v_order_total AS
SELECT o.order_id,
       count(l.line_no)                             AS line_count,
       COALESCE(sum(l.quantity * l.unit_price), 0)  AS total
FROM customer_order o
LEFT JOIN order_line l ON l.order_id = o.order_id
GROUP BY o.order_id;

-- R5: one row per order for "my orders" (and later the store's order queue): where it is fulfilled, its
-- total, and when its status last changed, which is the newest history row (a correlated subquery).
CREATE VIEW v_order_summary AS
SELECT o.order_id,
       o.customer_id,
       o.placed_at,
       o.status,
       o.fulfilment_method,
       o.fulfilling_store_id,
       s.name                            AS fulfilling_store_name,
       t.total,
       t.line_count,
       (SELECT max(h.changed_at)
        FROM order_status_history h
        WHERE h.order_id = o.order_id)   AS last_updated_at
FROM customer_order o
JOIN store s         ON s.store_id = o.fulfilling_store_id
JOIN v_order_total t ON t.order_id = o.order_id;

-- What each order has been charged and refunded, and the balance the shop still holds (charged - refunded).
-- Payments are summed per order in the subquery, *before* the join, so each order meets at most one row
-- and nothing can multiply its payments (summed after a join with its lines, each payment would count once
-- per line). The LEFT JOIN keeps orders with no payments yet; COALESCE makes their sums 0, and the casts
-- keep two decimals, so the API shows 0.00, not 0.
CREATE VIEW v_order_payment AS
SELECT o.order_id,
       CAST(COALESCE(p.charged, 0) AS NUMERIC(10,2))                            AS charged,
       CAST(COALESCE(p.refunded, 0) AS NUMERIC(10,2))                           AS refunded,
       CAST(COALESCE(p.charged, 0) - COALESCE(p.refunded, 0) AS NUMERIC(10,2))  AS balance
FROM customer_order o
LEFT JOIN (SELECT order_id,
                  sum(CASE WHEN kind = 'charge' THEN amount END) AS charged,
                  sum(CASE WHEN kind = 'refund' THEN amount END) AS refunded
           FROM payment
           GROUP BY order_id) p ON p.order_id = o.order_id;

-- R11: an order's status timeline: who, when, from → to. A change made by the customer or the system has
-- no staff member, so this is a LEFT JOIN (an inner join would drop those rows). No ORDER BY in the view:
-- readers sort by seq, because an order's first rows can share one changed_at (one transaction's now()).
CREATE VIEW v_order_timeline AS
SELECT h.order_id,
       h.seq,
       h.from_status,
       h.to_status,
       h.changed_at,
       h.changed_by_staff_id,
       st.full_name AS changed_by_name
FROM order_status_history h
LEFT JOIN staff st ON st.staff_id = h.changed_by_staff_id;

-- ===== SP4: reports =====

-- R9: what counts as a sale, defined once for every report. A sale is an order line whose order is paid and not
-- cancelled ('placed' exists only inside checkout, before the charge). It is dated by when the order was placed
-- and credited to the store that fulfils it — the store checkout took the stock from, and the one a cancellation
-- puts it back into — at the price paid (order_line.unit_price, plan T-1), not today's price.
CREATE VIEW v_sale_line AS
SELECT o.order_id,
       l.line_no,
       o.fulfilling_store_id       AS store_id,
       o.placed_at,
       l.product_id,
       p.category_id,
       l.quantity,
       l.unit_price,
       l.quantity * l.unit_price   AS line_total
FROM customer_order o
JOIN order_line l ON l.order_id = o.order_id
JOIN product p    ON p.product_id = l.product_id
WHERE o.status NOT IN ('placed', 'cancelled');

-- ===== SP3: returns =====

-- What each return is worth: its items at the prices they were bought at (order_line.unit_price, BR08).
-- The refund (BR14), T2 and the return pages all read it, so the amount is worked out in one place.
-- The lines are joined to their order lines in parentheses *before* the LEFT JOIN: written as
-- "LEFT JOIN return_line … JOIN order_line …", the joins group left to right and the inner join would drop a
-- return that has no lines yet. Such a return keeps its row here, worth 0 and 0.00.
CREATE VIEW v_return_value AS
SELECT r.return_id,
       r.order_id,
       CAST(COALESCE(sum(rl.quantity), 0) AS INT)                            AS quantity,
       CAST(COALESCE(sum(rl.quantity * ol.unit_price), 0) AS NUMERIC(10,2)) AS value
FROM return_request r
LEFT JOIN (return_line rl
           JOIN order_line ol ON ol.order_id = rl.order_id AND ol.line_no = rl.line_no)
       ON rl.return_id = r.return_id
GROUP BY r.return_id, r.order_id;
