-- Indexes chosen from measured query plans (docs/indexes-explain.md). Optional, beyond Week 10 (Weeks 11-12,
-- plan T-8): kept in their own file, apart from the required schema, so they can be explained or left out on
-- their own.
--
-- PostgreSQL already indexes every PRIMARY KEY and UNIQUE constraint, but not foreign keys. At the seeded size
-- (1,500 orders) every query here takes about a millisecond with or without these; they are for when the data
-- grows. Each one costs every INSERT and UPDATE of its table one more index entry to keep.
--
-- Not added, because an index already serves the query: "this customer's orders" (GET /customers/{id}/orders,
-- the returns and the support history) is answered by br10_order_idempotency_unique, whose first column is
-- customer_id; an order's history by order_status_history's primary key (order_id, seq); a return's order by
-- br10_return_idempotency_unique (order_id first).

-- A store's orders: the store queue (GET /stores/{id}/orders, oldest first) and every section of the store
-- report, which reads a store's sales in a placed_at window (v_sale_line). fulfilling_store_id is a foreign key.
CREATE INDEX customer_order_store_placed_idx ON customer_order (fulfilling_store_id, placed_at);

-- An order's payments: the BR14 refund triggers, BR20, BR21 (v_order_payment) and GET /orders/{id} sum one
-- order's payments. br20_one_charge_per_order covers only its charges (WHERE kind = 'charge'). order_id is a
-- foreign key.
CREATE INDEX payment_order_idx ON payment (order_id);
