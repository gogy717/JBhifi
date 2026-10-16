# Generated seed data — design

Status: approved on 2026-10-16 (three sections plus the anchor). Branch `gogy717/seed-generated-data`, from
`main` at `b633860`. Plan §7's data volume: ~300 customers and ~1,500 orders over 6 months; returns (~5%) are
added once sub-project 3 is on `main`. Layout from plan §7: `scripts/generate_seed.py` (fixed random seed) →
committed `sql/20_seed_generated.sql`.

## 1. Approach

**Python plans the timeline; SQL replays it through the real rules.** The generator plans every event (a customer
signs up, an order is checked out, moved, cancelled, stock is received, an address is retired) and writes them in
time order as one-line calls to `pg_temp` helper functions. Each helper does what its service does: T1 checkout,
a status move, T4 cancel, T3 stock received. No trigger is disabled, so all ~1,500 orders pass every rule (BR03,
BR06–BR10, BR14, BR16–BR18, BR20, BR21): the seed doubles as integrity evidence for the report. `pg_temp`
functions belong to the loading session and disappear with it, so nothing is added to the schema.

Rejected: Yuhang's approach (insert, then disable the guards and back-date rows), because it switches rules off.
Also rejected: one plain statement per step (a 2–3 MB file) and a data-only file walked by a `DO` loop (the logic
hidden in a loop).

## 2. Time

- **Anchor.** The file runs in one transaction with `SET LOCAL timezone = 'Australia/Sydney'`, as
  `10_seed_reference.sql` does. The anchor is `date_trunc('day', now())`: Sydney midnight on the day the file is
  loaded. Every event is `pg_temp.seed_at(days, minutes)` = anchor − `days` days + `minutes` minutes, with
  `days ≥ 1`, so the whole timeline lies before the anchor. The generator decides what has already happened by
  comparing against the anchor, not against "now". Loading at any hour gives the same rows with every time in
  the past, and the local clock times are right. Times are relative to the load date: like the seeded
  promotions, the data is "the last 182 days" whenever it is built, so the demo database is rebuilt on demo day.
  The price of this choice: "today" means "yesterday evening" at the latest.
- **History times.** `order_status_history.changed_at` defaults to `now()`, and BR09's log trigger is what
  writes history. **Changed existing object:** `br09_log_status_change` now writes `COALESCE(NULLIF(
  current_setting('app.changed_at', true), '')::timestamptz, now())`, read exactly as it already reads
  `app.staff_id`. The trust model is unchanged: these are transaction-local settings (`set_config(…, true)`) that
  the service layer sets and the database trusts. The API never sets `app.changed_at`. The seed's settings end
  with its transaction. Restricting who may set them is a database-role question beyond this course. Other times
  are written as columns: `placed_at` (= the charge's `created_at`, as in T1's single `now()`), the refund's
  `created_at` (= the cancellation), `adjusted_at`, and `customer.created_at` (before the customer's first order).
- **Considered and rejected: a rule that history times never go backwards.** `now()` is the transaction's start
  time. A request that started at t1 and waited on the order's row lock while another request committed a move at
  t2 > t1 can then legitimately write a row dated t1, earlier than the row before it. A monotonic check would
  refuse that legal move. Refusing only future times is safe but adds little. The seed test checks the seed's own
  history is chronological instead.

## 3. Content

- **Customers:** 300 generated ones join the 4 reference customers (so Alice stays customer 1 and staff ids are
  unchanged; persona accounts are linked later by email). Names come from fixed lists;
  `first.last.N@example.com`; one address in the customer's state and a home store there. About 10% retire
  address 1 between two orders and use address 2 afterwards (BR16, BR17).
- **Orders:** about 1,500, placed 08:00–22:00 over 182 days. The number per customer is skewed, averaging about
  5. About 55% are Click & Collect at the home store. About 45% are deliveries, 70% of them from the warehouse
  and the rest from the home store. 1, 2 or 3 lines (about 70/25/5%); cheaper products are chosen more often and
  sometimes bought two at a time. Only products on sale (BR07). Lines are numbered in `product_id` order, as T1
  numbers them. **Unit price** is computed in SQL at load time: the promotion active at `placed_at`, else the base
  price.
- **Moves:** C&C goes picking after 0.5–4 h, ready after 1–24 h more, collected within 0–5 days. Delivery goes
  picking after 1–12 h, shipped after 0.5–2 days, delivered after 1–5 days. A random staff member of the
  fulfilling store makes each move. Any step that would fall after the anchor doesn't happen, so recent orders
  wait in the queues.
- **Cancellations (T4 order: restock → refund → cancelled):** about 3% are cancelled by the customer 0–6 h after
  placing, drawn first, with picking scheduled after the cancel time. About 1% are C&C orders still uncollected
  7 days after `ready`, cancelled by the store.
- **Stock:** the generator tracks every (store, product) in time order. When a sale would need more than is left,
  a `received` adjustment by a staff member of that store comes 1–2 days earlier: +6–12 units at retail, +30–60 at
  the warehouse. It is written as T3 writes one (`UPDATE … RETURNING quantity` → `quantity_after`). Stock is
  received only when needed, so low and zero stock remain for the demo.
- **Scripted scenarios:**
  - Alice: one order delivered 40 days ago (BR11 will refuse a return); one collected 5 days ago at Sydney CBD
    (a return to demo); one C&C order at Sydney CBD ready since yesterday; one paid at about 21:00 yesterday (a
    customer cancel to demo).
  - Ben: a cancelled order and a delivered one. Mei: a delivery that has shipped. Tom: two completed orders.
  - Sydney CBD: 4 paid and 3 picking orders from the last two days, for Aiden and Olivia to move.
  - After SP3: Alice gets a requested return, and about 5% of completed orders get returns in every state.
- **Ids:** order ids are explicit, 1..N in time order, then `setval`. Customers are referenced by email.
  `idempotency_key` values are `uuid5` literals, so the file is reproducible byte for byte.

## 4. Files

- `scripts/seed_helpers.sql`: the hand-written `pg_temp` helpers, embedded verbatim at the top of the output.
- `scripts/generate_seed.py`: builds `<POSTGRES_TEST_DB>_seed` from `sql/` files numbered below 20, reads the
  reference rows, plans with a fixed seed, writes `sql/20_seed_generated.sql`, then loads it into that database
  to prove it passes. Standard library plus psycopg2 and python-dotenv (already required).
- `tests/conftest.py`: skips generated files (name ≥ `20`), so the test database stays reference-only. **Changed
  existing file**, listed in the PR.

## 5. Tests

- `test_business_rules.py` (BR09 section): `test_br09_a_service_can_name_when_a_change_happened`. With
  `app.changed_at` set, the history uses it; unset, it uses `now()`.
- `tests/test_seed_generator.py` (fast, no database):
  - The same seed gives the same text.
  - Volumes are in range.
  - Every offset lies before the anchor.
  - Each customer is created before their first order.
  - Planned stock never goes negative.
  - Every customer cancel comes before picking; every cancellation follows T4's order.
  - A retired address is never used afterwards.
- `tests/test_seed.py`: load files 00–10 into `<POSTGRES_TEST_DB>_seed`, snapshot the stock, load 20, then
  check:
  - The history checks (`history_breaks`) find nothing.
  - Every order at `paid` or later was charged exactly its total, and every cancelled order holds 0.
  - Every order's history is chronological, its first row is at `placed_at`, and its charge is at `placed_at`.
  - Every delivery's address was active when the order was placed.
  - No time is later than `now()`.
  - Stock = snapshot + Σ received − Σ lines of orders not cancelled.
  - The scripted scenarios exist, and the volumes are in range.
  - The committed file equals a fresh generation.
  
  It is timed. If it takes longer than the rest of the suite (~14 s), it gets a `seed` marker and is skipped by
  default. The generator and this test share the `_seed` database, so they must not run at the same time (noted
  in the README).
