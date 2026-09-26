-- The three reports, as runnable SQL with the expected shapes.
--
-- This file is *not* part of `sql/`: every file in `sql/` is executed while the container builds the
-- database, and these are parameterised queries with placeholders to be driven from Python. The service
-- (`app/services/reports.py`) holds the same statements, which is deliberate — the assessed queries are
-- readable here with their explanations, and the service stays self-contained.
--
-- Boundaries: `from_date` and `to_date` are Sydney calendar dates, `from_date` inclusive and `to_date`
-- exclusive. `timestamp AT TIME ZONE 'Australia/Sydney'` turns a local date into the moment that day
-- starts, so the boundary is the same for every row wherever the server happens to run.

-- ---------------------------------------------------------------------------- 1. Sales per store
-- Grain: one row per store, for payments *booked* in [from_date, to_date) plus orders *placed* in it.
-- The three aggregates are computed in separate CTEs before any join: joining payments to order lines
-- first would multiply a charge by the number of lines on its order, and the total would be wrong.
WITH captured AS (
    SELECT o.fulfilling_store_id                      AS store_id,
           COALESCE(sum(p.amount), 0)                 AS captured_amount,
           count(DISTINCT p.order_id)                 AS charged_orders
    FROM payment p
    JOIN customer_order o ON o.order_id = p.order_id
    WHERE p.kind = 'charge'
      AND p.created_at >= (%(from_date)s::timestamp AT TIME ZONE 'Australia/Sydney')
      AND p.created_at <  (%(to_date)s::timestamp   AT TIME ZONE 'Australia/Sydney')
      AND (%(store_id)s::int IS NULL OR o.fulfilling_store_id = %(store_id)s::int)
    GROUP BY o.fulfilling_store_id
),
refunded AS (
    SELECT o.fulfilling_store_id                      AS store_id,
           COALESCE(sum(p.amount), 0)                 AS refunded_amount,
           count(*)                                   AS refund_count
    FROM payment p
    JOIN customer_order o ON o.order_id = p.order_id
    WHERE p.kind = 'refund'
      AND p.created_at >= (%(from_date)s::timestamp AT TIME ZONE 'Australia/Sydney')
      AND p.created_at <  (%(to_date)s::timestamp   AT TIME ZONE 'Australia/Sydney')
      AND (%(store_id)s::int IS NULL OR o.fulfilling_store_id = %(store_id)s::int)
    GROUP BY o.fulfilling_store_id
),
placed AS (
    SELECT o.fulfilling_store_id AS store_id, count(*) AS order_count
    FROM customer_order o
    WHERE o.placed_at >= (%(from_date)s::timestamp AT TIME ZONE 'Australia/Sydney')
      AND o.placed_at <  (%(to_date)s::timestamp   AT TIME ZONE 'Australia/Sydney')
      AND (%(store_id)s::int IS NULL OR o.fulfilling_store_id = %(store_id)s::int)
    GROUP BY o.fulfilling_store_id
)
SELECT s.store_id,
       s.name                                                                  AS store_name,
       COALESCE(c.captured_amount, 0)::numeric(12,2)                           AS captured_amount,
       COALESCE(r.refunded_amount, 0)::numeric(12,2)                           AS refunded_amount,
       (COALESCE(c.captured_amount, 0) - COALESCE(r.refunded_amount, 0))::numeric(12,2) AS net_receipts,
       COALESCE(pl.order_count, 0)                                             AS order_count,
       COALESCE(c.charged_orders, 0)                                           AS charged_orders,
       COALESCE(r.refund_count, 0)                                             AS refund_count
FROM store s
LEFT JOIN captured  c  ON c.store_id = s.store_id
LEFT JOIN refunded  r  ON r.store_id = s.store_id
LEFT JOIN placed    pl ON pl.store_id = s.store_id
WHERE c.store_id IS NOT NULL OR r.store_id IS NOT NULL OR pl.store_id IS NOT NULL
ORDER BY s.store_id;

-- Expected output after `scripts/seed_demo.py --seed 9120` on a fresh database, for
-- from_date = 2026-08-27, to_date = 2026-09-27 (one store that traded in the period):
--   store_id | store_name  | captured_amount | refunded_amount | net_receipts | order_count
--   ---------+-------------+-----------------+-----------------+--------------+------------
--   ...      | Sydney CBD  | (see doc/reports.md for the hand-calculated figures)

-- ---------------------------------------------------------------------------- 2. Low stock at a store
-- Grain: one row per active product whose quantity at that store is at or below the threshold. The LEFT
-- JOIN is what makes "no inventory row" mean zero rather than missing: a product that has never been
-- stocked still has to appear, because it cannot be sold.
SELECT p.product_id,
       p.sku,
       p.name,
       b.name                              AS brand,
       c.name                              AS category,
       cp.current_price,
       COALESCE(i.quantity, 0)             AS quantity,
       i.store_id IS NOT NULL              AS has_inventory_row
FROM product p
JOIN brand b                    ON b.brand_id = p.brand_id
JOIN category c                 ON c.category_id = p.category_id
JOIN v_product_current_price cp ON cp.product_id = p.product_id
LEFT JOIN inventory i           ON i.product_id = p.product_id AND i.store_id = %(store_id)s::int
WHERE p.is_active
  AND COALESCE(i.quantity, 0) <= %(threshold)s::int
ORDER BY COALESCE(i.quantity, 0), p.name;

-- ---------------------------------------------------------------------------- 3. Returns per store
-- Grain: the *cohort* of return requests created in [from_date, to_date), attributed to the store that
-- fulfilled the order; their current status is counted, and the refund is joined on the request rather
-- than on the payment's own date (a refund that happens next week still belongs to this request).
-- The receiving store is shown separately, because a customer may hand an item back somewhere else.
WITH cohort AS (
    SELECT rr.return_id, rr.status, rr.received_store_id, o.fulfilling_store_id
    FROM return_request rr
    JOIN customer_order o ON o.order_id = rr.order_id
    WHERE rr.requested_at >= (%(from_date)s::timestamp AT TIME ZONE 'Australia/Sydney')
      AND rr.requested_at <  (%(to_date)s::timestamp   AT TIME ZONE 'Australia/Sydney')
      AND (%(store_id)s::int IS NULL OR o.fulfilling_store_id = %(store_id)s::int)
),
refunds AS (
    SELECT return_id, sum(amount) AS refunded_amount
    FROM payment WHERE kind = 'refund' GROUP BY return_id
)
SELECT c.fulfilling_store_id                                        AS store_id,
       s.name                                                       AS store_name,
       count(*)                                                     AS requested_count,
       count(*) FILTER (WHERE c.status = 'received')                AS received_count,
       count(*) FILTER (WHERE c.status = 'refunded')                AS refunded_count,
       count(*) FILTER (WHERE c.status = 'rejected')                AS rejected_count,
       COALESCE(sum(rf.refunded_amount), 0)::numeric(12,2)          AS refunded_amount,
       (SELECT string_agg(rstore.name || ' (' || counts.received || ')', ', '
                          ORDER BY rstore.name)
        FROM (SELECT received_store_id, count(*) AS received
              FROM cohort WHERE received_store_id IS NOT NULL
              GROUP BY received_store_id) counts
        JOIN store rstore ON rstore.store_id = counts.received_store_id) AS receiving_stores
FROM cohort c
JOIN store s      ON s.store_id = c.fulfilling_store_id
LEFT JOIN refunds rf ON rf.return_id = c.return_id
GROUP BY c.fulfilling_store_id, s.name
ORDER BY c.fulfilling_store_id;

-- ---------------------------------------------------------------------------- 4. A nested-query example
-- Division ("which stores have never had a return?") with NOT EXISTS, which is the SQL the plan asks to
-- be able to demonstrate. Read-only, no parameters.
-- Question: which retail stores have fulfilled at least one order but never had a return requested?
SELECT s.store_id, s.name
FROM store s
WHERE s.store_type = 'retail'
  AND EXISTS (SELECT 1 FROM customer_order o WHERE o.fulfilling_store_id = s.store_id)
  AND NOT EXISTS (
        SELECT 1
        FROM return_request rr
        JOIN customer_order o ON o.order_id = rr.order_id
        WHERE o.fulfilling_store_id = s.store_id)
ORDER BY s.store_id;

-- Expected on the seeded demo database: the stores the seed gave orders but no returns (typically the
-- ones that only have in-flight orders).
