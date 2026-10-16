# Indexes and EXPLAIN

**Optional, beyond Week 10 (Weeks 11–12), plan T-8.** The indexes are in `sql/05_indexes.sql`, apart from the
required schema.

**The short version.** On the seeded data (1,500 orders), every hot query already takes about a millisecond or
less, with or without new indexes. The two indexes added here are for when the data grows. They don't make
today's pages faster in a way anyone would notice. What this document shows is how to read a query plan, how to
pick an index for a query, and why most candidate indexes were left out.

## Method

- **Database.** The seeded dev database (`scripts/reset_db.py`), freshly `ANALYZE`d, PostgreSQL 18.6.
  - The largest tables are `order_status_history` (7,341 rows), `order_line` (2,009), `payment` (1,635) and
    `customer_order` (1,500).
  - Everything fits in shared buffers, so these are warm-cache timings.
- **The SQL measured is what the services really send.** A recording cursor captured it from the real service
  functions:
  - `list_customer_orders`, for customer 29 (the most orders: 37);
  - `list_store_orders` for store 10, statuses paid/picking/ready;
  - `build_store_report` for store 10, 30 days;
  - `list_customer_returns` for customer 17;
  - `customer_history` for customer 29;
  - `get_order`.

  BR11's and BR14's trigger queries were copied from `sql/02_rules.sql`.
- **Each statement ran under `EXPLAIN (ANALYZE, BUFFERS)`, with and without the indexes, interleaved on one
  connection.**
  - "Without" drops both indexes inside a savepoint, then rolls back to restore them.
  - Three rounds of 7 runs each way; the fastest of the 21.
  - Measuring the two versions in separate sessions moved even queries that use neither index by up to ±0.2 ms,
    which is more than most of the differences below. Interleaving removes that drift.

## Results

| Query | Without | With | What the plan does |
|---|---|---|---|
| Q1 my orders, `GET /customers/{id}/orders` | 0.956 ms | 0.954 ms | no change: `br10_order_idempotency_unique` already finds the customer's 37 orders (see *Not added*) |
| Q2 store queue, `GET /stores/{id}/orders?status=…` | 0.977 ms | 0.898 ms | `customer_order`: Seq Scan, 1,497 rows removed by the filter → Bitmap Index Scan on `customer_order_store_placed_idx`, 132 rows, of which the status filter keeps 3 |
| Q3 store report: low stock | 0.298 ms | 0.199 ms | `customer_order` in `v_sale_line`: Seq Scan → index on store and date (as below) |
| Q3 store report: sales by category | 0.278 ms | 0.177 ms | the same |
| Q3 store report: sales total | 0.253 ms | 0.146 ms | the same (plans below) |
| Q3 store report: return rate by category | 0.345 ms | 0.235 ms | the same |
| Q3 store report: return rate by product | 0.308 ms | 0.205 ms | the same |
| Q4 a customer's returns | 0.229 ms | 0.228 ms | no change: the customer's orders by `br10_order_idempotency_unique`, the refund by `br14_refund_once_per_return`; `return_request` (79 rows), `return_line` and `order_line` are read whole, which is cheaper at this size |
| Q5 support history | 0.809 ms | 0.793 ms | no change: hash joins over whole tables beat 37 index lookups at this size |
| Q6 BR11 completion time (trigger) | 0.006 ms | 0.006 ms | no change: `order_status_history`'s primary key `(order_id, seq)` |
| Q7 BR14 refund trigger: one order's payments | 0.036 ms | 0.004 ms | `payment`: Seq Scan, 1,634 rows removed → Index Scan on `payment_order_idx` |
| Q8 `GET /orders/{id}`: `v_order_payment` | 0.035 ms | 0.007 ms | the same |

### The store report's sales total, without and with the index

Without: every order is read, and all but the store's 22 in the window are thrown away.

```text
Hash  (actual time=0.113..0.113 rows=22.00 loops=1)
  ->  Seq Scan on customer_order o  (cost=0.00..117.75 rows=21 width=4) (actual time=0.092..0.111 rows=22.00 loops=1)
        Filter: (((status)::text <> ALL ('{placed,cancelled}'::text[])) AND (fulfilling_store_id = 10) AND (placed_at >= (now() - '30 days'::interval)))
        Rows Removed by Filter: 1478
Execution Time: 0.253 ms
```

With: one index search finds exactly those 22, and only the status is checked on the rows themselves.

```text
Hash  (actual time=0.008..0.008 rows=22.00 loops=1)
  ->  Bitmap Heap Scan on customer_order o  (cost=4.51..55.73 rows=21 width=4) (actual time=0.003..0.006 rows=22.00 loops=1)
        Recheck Cond: ((fulfilling_store_id = 10) AND (placed_at >= (now() - '30 days'::interval)))
        Filter: ((status)::text <> ALL ('{placed,cancelled}'::text[]))
        ->  Bitmap Index Scan on customer_order_store_placed_idx  (cost=0.00..4.50 rows=22 width=0) (actual time=0.002..0.002 rows=22.00 loops=1)
              Index Cond: ((fulfilling_store_id = 10) AND (placed_at >= (now() - '30 days'::interval)))
Execution Time: 0.146 ms
```

The rest of that plan is unchanged: `order_line` (2,009 rows) is still read whole and hash-joined, which at this
size is cheaper than 22 index lookups.

### BR14's refund trigger, without and with the index

```text
Seq Scan on payment  (cost=0.00..37.52 rows=1 width=12) (actual time=0.016..0.033 rows=1.00 loops=1)
  Filter: ((payment_id <> 0) AND (order_id = 700))
  Rows Removed by Filter: 1634
Execution Time: 0.036 ms
```

```text
Index Scan using payment_order_idx on payment  (cost=0.28..8.30 rows=1 width=12) (actual time=0.001..0.001 rows=1.00 loops=1)
  Index Cond: (order_id = 700)
  Filter: (payment_id <> 0)
Execution Time: 0.004 ms
```

The trigger fires on every payment, and for a refund it runs this query, so its cost is paid inside T2 (a refund)
and T4 (a cancellation's refund). Without the index, it grows with the number of payments in the whole shop, not
with the order's own.

## The two indexes

- **`customer_order_store_placed_idx ON customer_order (fulfilling_store_id, placed_at)`.** It serves the store
  queue and all five store-report sections. `fulfilling_store_id` is a foreign key, and PostgreSQL indexes primary
  keys and `UNIQUE` constraints, not foreign keys. The store comes first because the queries test it for equality
  and `placed_at` for a range. With that order, one store's orders sit together in date order, so a window is a
  single run of index entries. The other order, `(placed_at, fulfilling_store_id)`, would read every store's
  orders in the window and check the store on each. At this size the planner accepted either order (tried), but
  with many stores only the first stays proportional to one store's orders.
- **`payment_order_idx ON payment (order_id)`.** It serves BR14's refund cap (`br14_refunds_within_charged`),
  BR21 (`v_order_payment`) and `GET /orders/{id}`, which all read every payment of one order. `order_id` is a
  foreign key. BR20's paid-in-full check reads only an order's charges (`kind = 'charge'`), which the existing
  partial index `br20_one_charge_per_order` already serves.

## Not added, and why

- **"This customer's orders" (`customer_order.customer_id`), although it is a foreign key.** I first proposed
  `(customer_id, placed_at)`. The plans showed that every such lookup, in Q1, Q4 and all five in Q5, already uses
  `br10_order_idempotency_unique`. PostgreSQL built that index for the `UNIQUE (customer_id, idempotency_key)`
  constraint, and `customer_id` is its first column. A B-tree index serves any condition on a leading prefix of
  its columns. Added, the new index gave the same estimated cost (4.56..72.53), and the plan still sorted by
  `placed_at`, because the list is built after joins. The only gain was size: 64 kB against 144 kB. **Not every
  foreign key needs its own index.**
- **`order_line (product_id)`** (a foreign key). No hot query looks order lines up by product. The reports find a
  store's orders by date first, then join their lines; with the index in place the planner still read
  `order_line` whole.
- **An order's history, lines and returns.** These are already covered:
  - `order_status_history` by its primary key `(order_id, seq)`;
  - `order_line` by its primary key and by `br07_order_line_product_once (order_id, product_id)`;
  - `return_request` by `br10_return_idempotency_unique (order_id, idempotency_key)`, though at 79 rows the planner
    reads it whole;
  - `return_line` by its primary key.
- **`inventory (product_id)`, `promotion (product_id)`.** 624 and 9 rows: a sequential scan reads them in a
  handful of pages.
- **Searching customers by name (`GET /customers?q=`).** `ILIKE '%…%'` can't use a B-tree. It would need the
  `pg_trgm` extension, which is further outside the unit.

## What the indexes cost

- **Every write keeps them up to date.**
  - Each checkout (T1) inserts one `customer_order` row and one charge into `payment`.
  - Each refund (T2) and each cancellation (T4) inserts a `payment` row.
  - Each of those inserts now writes one more index entry.
  - Status changes (BR09's moves, T4's cancel) don't touch `customer_order_store_placed_idx`: neither of its
    columns ever changes (`br09_order_header_immutable`). So those updates remain eligible for PostgreSQL's
    heap-only updates, which skip the indexes.
- **Space.** On the seed, `customer_order_store_placed_idx` takes 96 kB (the table 672 kB) and `payment_order_idx`
  56 kB (the table 104 kB).
- **On small tables the planner may skip them.** When it estimates that reading a table whole is cheaper, it
  does. That is why `order_line` (2,009 rows) and Q5's tables are still read whole above, despite their primary
  key indexes. In the test database, which has no generated seed, the choice varies with the statistics, and the
  tests have to allow for it (below).

## Follow-up, not done here

Most of Q1's and Q2's time (0.66–0.81 ms of about 0.95 ms) is `v_order_summary` totalling **every** order through
`v_order_total` (a HashAggregate over all 1,500 orders and 2,009 lines) before joining the few it needs. That
cost grows with the shop's total number of orders, not with the customer's or the store's, and no index changes
it. The fix would be to rewrite the view so it totals only the orders asked for, for example with a correlated
subquery or `LATERAL`. That changes a view rather than adding an index, and at about 1 ms it isn't needed now.

## How it is tested

`tests/test_indexes.py`:

- **The definition check.** Both indexes exist exactly as defined (`pg_indexes.indexdef`). This also pins the
  column order.
- **The plan checks.** For the statement each service really sends (captured the same way), the test turns
  sequential scans off for its own transaction (`SET LOCAL enable_seqscan = off`) and checks the JSON plan. The
  index must be used with the query's filter column as an `Index Cond`, not as a filter applied afterwards.
  Turning sequential scans off doesn't choose an index; it only removes one option. So an index on the wrong
  column, or a service that stops filtering that way, fails.
- **The plan checks use Robina, a store almost no other test orders from.** The test database's statistics
  depend on what earlier tests committed. Run alone, a plain `EXPLAIN` already chose the index. In a full run,
  where most committed orders are at Sydney CBD, the planner once read the whole primary-key index instead for
  that store, which made an earlier version of the test fail intermittently. An index is for a selective filter,
  and Robina's is one.
