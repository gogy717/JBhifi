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
