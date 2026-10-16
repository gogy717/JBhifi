# Concurrency evidence (report §4)

What goes wrong when two transactions run at once without the right technique, how PostgreSQL reports it, and
the pattern this project uses instead. Each scenario has a test of the faulty pattern and a test of ours, in
`tests/test_concurrency_evidence.py`; the results below are what those tests printed.

- **Reproduce:** `pytest -s tests/test_concurrency_evidence.py` (each test prints one line of results).
- **Environment:** PostgreSQL 18.6, default isolation `READ COMMITTED`, psycopg2, run on 2026-10-16. All eight
  tests passed five runs in a row.
- **Scope:** transactions are Week 9 material. Whether the Week 9 lecture covered SQL isolation levels has not been
  checked yet, so everything below that uses `REPEATABLE READ` or `SERIALIZABLE` is marked *optional — confirm
  against the Week 9 transactions lecture*.
- **Method:** every transaction is its own connection. Steps that can't block run in a fixed order. A statement
  that will block runs in a second thread, and the test polls `pg_stat_activity` until that connection is waiting
  for a lock (`wait_event_type = 'Lock'`) before its next step. The order never depends on sleeping. The holder
  then keeps its lock for 0.3 s before committing, so the waits printed below are about 0.3 s. They are measured
  around the blocked call, so they are approximate.

## Summary

| Scenario | Faulty pattern (test) | Our pattern (test) | Observed | Mechanism |
|---|---|---|---|---|
| 1. Lost update: two customers, last unit | `test_read_then_write_back_loses_an_update_and_sells_the_last_unit_twice` | `test_conditional_update_sells_the_last_unit_once` | faulty: 2 sales of 1 unit, stock 0, no `CHECK` error · ours: 1 sale, B waited 0.31 s and updated 0 rows | conditional `UPDATE` (check and write in one statement) |
| 1b. The same under `REPEATABLE READ` *(optional)* | — | `test_conditional_update_under_repeatable_read_fails_with_a_serialization_error_instead` | B fails with 40001 "could not serialize access due to concurrent update" | isolation level |
| 2. Deadlock: two rows, opposite orders | `test_locking_two_rows_in_opposite_orders_deadlocks_and_postgres_aborts_one` | `test_locking_rows_in_product_id_order_makes_the_second_wait_and_both_succeed` | faulty: one aborted with 40P01, its work rolled back · ours: B waited 0.32 s, both committed | lock order (ascending `product_id`) |
| 3. Write skew: BR15, promotions never overlap | `test_check_then_insert_under_read_committed_lets_two_overlapping_promotions_in` | `test_br15_locks_the_product_so_two_overlapping_promotions_have_one_winner` | faulty: 2 overlapping promotions · ours: B waited 0.31 s, then `br15_promotion_no_overlap`, 1 promotion | parent-row lock (`FOR UPDATE` on the product) |
| 3b. The same check under `SERIALIZABLE` *(optional)* | — | `test_check_then_insert_under_serializable_aborts_one_and_its_retry_is_refused` | one aborted with 40001; its retry sees the other row and inserts nothing; 1 promotion | isolation level |
| 4. Inconsistent reads across a report — phantoms / read skew *(optional)* | `test_read_committed_would_let_a_sale_committed_mid_report_into_later_sections` | `test_repeatable_read_keeps_a_sale_committed_mid_report_out_of_every_section` | (SP4's tests, `tests/test_reports.py`) | isolation level (`REPEATABLE READ READ ONLY`) |

## 1. Lost update: two customers buy the last unit

**The problem.** A read–modify–write in application code: read the stock, work out the new quantity in Python,
write it back as a value. If both customers read before either writes, both see 1 and both write 0. The second
write overwrites the first, so one update is lost and one unit is sold twice. BR03's `CHECK (quantity >= 0)` can't
catch it, because no statement ever writes a negative number. This is the 2026-09-25 ORM experiment
(`doc/progress.md`), rewritten without an ORM.

```text
[1 lost update · faulty] A read 1, B read 1; both wrote back 0 and committed -> 2 sales, stock left 0, no CHECK violation
[1 lost update · ours] A updated 1 row; B waited 0.31s for A's row lock (polled until blocked), then updated 0 rows -> 1 sale, stock left 0
```

**Why ours is right.** Every stock change is relative and computed inside the database (`quantity = quantity ±
n`, never a value worked out in Python); T1's decrement also carries the check in the same statement:
`UPDATE inventory SET quantity = quantity - 1 WHERE … AND quantity >= 1`. B's `UPDATE` waits for A's
row lock. When A commits, PostgreSQL re-evaluates B's `WHERE` on the newest version of the row, finds 0 and
updates no row. Checkout treats "0 rows" as `out_of_stock` and rolls back. BR03's `CHECK` stays as the backstop.

**Under `REPEATABLE READ`** *(optional)*, the same statement doesn't update 0 rows. B may not change a row that
another transaction changed after B's snapshot, so it fails instead:

```text
[1 lost update · repeatable read] A updated 1 row; B -> SerializationFailure 40001: could not serialize access due to concurrent update -> stock left 0
```

The result is still correct, but every service would have to catch 40001 and retry the whole transaction. That is
one reason we stay on `READ COMMITTED` for writes.

## 2. Deadlock: two transactions lock two rows in opposite orders

**The problem.** A takes product P1 and then wants P2; B takes P2 and then wants P1. Each holds the row the other
needs, so neither can continue. After `deadlock_timeout` (1 s by default, lowered to 100 ms in the test),
PostgreSQL finds the cycle and aborts one transaction with SQLSTATE 40P01. Everything that transaction did is
rolled back, and the other transaction then gets its lock and commits. Which one is aborted is PostgreSQL's choice;
in these runs it was A, the one that started waiting first.

```text
[2 deadlock · faulty] A aborted with 40P01 (DeadlockDetected: deadlock detected); B committed -> stock P1 4, P2 4 (5 each before)
[2 deadlock · faulty] PostgreSQL's detail: Process 75312 waits for ShareLock on transaction 86549; blocked by process 75313. Process 75313 waits for ShareLock on transaction 86548; blocked by process 75312.
```

**Why ours is right.** Every transaction that locks several rows of a kind takes them in one global order:
ascending `product_id` for inventory, in T1 (checkout), T2 (restock on refund) and T4 (restock on cancel). Orders
come before returns (T2). B asks for P1 first, so it waits while holding nothing A needs. A finishes, then B
does. There is no cycle, so there can't be a deadlock.

```text
[2 deadlock · ours] A committed; B waited 0.32s (polled until blocked) on P1 holding nothing, then committed -> stock P1 3, P2 3 (5 each before)
```

The same rule on the real checkout: `test_baskets_in_opposite_product_order_do_not_deadlock`
(`tests/test_checkout_transactions.py`, two baskets in opposite orders, ten times over).

## 3. Write skew: one product's promotions never overlap (BR15)

**The problem.** BR15 is a rule over *other* rows: a new promotion is allowed only if no promotion of the same
product overlaps it. The obvious code checks with a `SELECT`, then `INSERT`s. Under `READ COMMITTED`, each check
reads only the rows committed so far, and neither transaction's new row is there yet. Both checks pass and both
transactions insert. No row was written twice, so no row lock ever made one wait. This is write skew.

```text
[3 write skew · read committed] A's check saw an overlap: False; B's: False; both inserted and committed -> 2 overlapping promotions for one product
```

This runs on a demo table shaped like `promotion` but with no trigger, because the real trigger is never switched
off. Disabling it inside each racing transaction would not show the anomaly either: `ALTER TABLE … DISABLE TRIGGER`
takes a `SHARE ROW EXCLUSIVE` lock on the table (measured on PostgreSQL 18.6), which conflicts with itself and with
every `INSERT`'s `ROW EXCLUSIVE`, so the two transactions would run one after the other. Disabling it in a committed
setup step would switch BR15 off for every connection at once.

**Under `SERIALIZABLE`** *(optional)*, PostgreSQL tracks what each transaction read. It sees that each one's insert
falls in what the other read, and aborts one with 40001 rather than let both commit. Retried in a new transaction,
that check now sees the other promotion, and nothing is inserted:

```text
[3 write skew · serializable] B failed at commit with 40001 (SerializationFailure: could not serialize access due to read/write dependencies among transactions); retried, its check saw an overlap: True, so it inserted nothing -> 1 promotion
```

**Why ours is right.** BR15's trigger (`br15_promotion_rules`, `sql/02_rules.sql`) first locks the product row
`FOR UPDATE`, then looks for an overlap. This was decision 4 of 2026-09-26: a trigger that reads other rows locks a
parent row first. B's insert waits in that lock until A commits. The overlap check is the next statement in the
PL/pgSQL function, and under `READ COMMITTED` each statement takes a fresh snapshot, so it sees A's committed
promotion. **That fresh snapshot is what makes locking the parent row work under `READ COMMITTED`.** Locking the
parent turns the two checks into one after the other.

```text
[3 write skew · ours] B's trigger waited 0.31s (polled until blocked) for A's lock on the product, then -> br15_promotion_no_overlap: This product already has a promotion in that period -> 1 promotion
```

## 4. Inconsistent reads across a report: phantoms and read skew *(optional)*

A store report runs several queries. Under `READ COMMITTED` each query takes a fresh snapshot, so a sale committed
between two of them would appear as new rows in the later sections (a phantom) and not in the earlier ones: the
sections would describe different moments (read skew). SP4 runs the report in one `REPEATABLE READ READ ONLY` snapshot, and
pins both sides in `tests/test_reports.py`:
`test_read_committed_would_let_a_sale_committed_mid_report_into_later_sections` and
`test_repeatable_read_keeps_a_sale_committed_mid_report_out_of_every_section`.

## Tutor question 4: is `READ COMMITTED` + conditional `UPDATE` enough, or should we demonstrate `SERIALIZABLE`?

**`READ COMMITTED` is enough for our transactions, because every rule that depends on concurrency uses one of two
patterns** (BR07's "still on sale" and BR17's "current address" deliberately take no lock: each holds at the moment
of the sale, `sql/02_rules.sql`):

- **The check is the write itself.** The conditional `UPDATE` (scenario 1) checks and writes the row in one
  statement.
- **The check runs after a parent row is locked `FOR UPDATE`.** BR08, BR12, BR14, BR15 and BR20 do this, as do T2
  and T4. BR06 and BR22 use `FOR SHARE` when only a change to that row has to wait. Under `READ COMMITTED` the
  second transaction waits for the first, then checks on a fresh snapshot (scenario 3).

Multi-row locks are taken in one global order, so they can't deadlock (scenario 2). Unique constraints settle
retries: `ON CONFLICT` on the idempotency keys (BR10), and `UNIQUE (return_id)` on payment (BR14).

**`SERIALIZABLE` would stop write skew without explicit locks** (scenario 3b), but it has costs. Every service would
have to catch 40001 and retry the whole transaction (scenario 1b shows the same need under `REPEATABLE READ`). It
can also abort transactions that would not have conflicted: here the demo table is scanned without an index, so a
read covers the whole table (argued from how PostgreSQL tracks reads, not shown by a test). We therefore show it as the alternative and don't adopt it.

**`REPEATABLE READ` is used in one place:** the read-only store report, which needs one consistent snapshot
(scenario 4).

**Tests that pin each mechanism.** The race tests release their transactions together on a barrier, and most also
keep each one open for 0.3 s before committing, so the two overlap in practice — but not by construction
(`test_last_unit_has_one_buyer`, `test_baskets_in_opposite_product_order_do_not_deadlock` and
`test_concurrent_adds_get_distinct_numbers` have no hold). Only the eight tests above wait until one transaction is
blocked before the next step. The `get_order` test is sequential: a status change times out while a read holds the
order.

| Mechanism | Where | Test |
|---|---|---|
| Conditional `UPDATE` on stock | T1 checkout | `test_last_unit_has_one_buyer` (`test_checkout_transactions.py`); deterministic: `test_conditional_update_sells_the_last_unit_once` |
| Relative `UPDATE`, BR03 backstop | T3 stock adjustment | `test_concurrent_adjustments_lose_no_update`, `test_concurrent_removals_never_oversell` (`test_transactions.py`) |
| Lock order: inventory by `product_id` | T1 | `test_baskets_in_opposite_product_order_do_not_deadlock`; locks are per store: `test_stock_is_locked_per_store_not_per_product` |
| Order `FOR UPDATE` + one starting status | staff status moves (`advance_order`) and T4 cancel | `test_two_clerks_making_the_same_move_at_once_one_wins`, `test_a_cancel_and_a_move_at_once_have_one_winner`, `test_the_customer_and_the_store_cancelling_at_once_refund_once` (`test_fulfilment_transactions.py`) |
| Order then return `FOR UPDATE`, restock by `product_id` | T2 refund | `test_two_staff_refunding_one_return_refund_it_once`; backstop `UNIQUE (return_id)`: `test_the_refund_unique_key_is_the_backstop` (`test_return_transactions.py`) |
| Order line `FOR UPDATE` | BR12 return quantity | `test_two_requests_for_the_last_units_of_a_line_have_one_winner` (`test_return_transactions.py`) |
| Product `FOR UPDATE` | BR15 promotions | `test_br15_locks_the_product_so_two_overlapping_promotions_have_one_winner` (`test_concurrency_evidence.py`) |
| Store `FOR SHARE` | BR06 | `test_br06_a_store_type_change_and_a_collect_order_race_has_one_winner` (`test_checkout_transactions.py`) |
| Customer `FOR UPDATE` | address numbering | `test_concurrent_adds_get_distinct_numbers` (`test_addresses.py`) |
| Order `FOR SHARE` on read | `get_order` | `test_reading_an_order_holds_off_a_status_change_until_the_read_ends` (`test_order_reads.py`) |
| Unique key + `ON CONFLICT` | BR10 checkout and return retries | `test_concurrent_same_key_creates_one_order` (`test_checkout_transactions.py`), `test_the_same_key_at_once_creates_one_return` (`test_return_transactions.py`) |

**Locks and orders with no race test of their own.** Their rule tests (`tests/test_business_rules.py`) pin what
each refuses, but not the race:

- **BR08 and BR20's order lock.** It makes adding lines and charging wait for `placed → paid`; all three happen
  inside one checkout transaction.
- **The order lock in BR14's refund triggers** (`br14_refunds_within_charged`, and SP2's
  `br14_refund_without_return_is_cancellation`). Every refund takes it, and the second insert in
  `test_the_refund_unique_key_is_the_backstop` waits on it, but no test races two refunds of one order to the cap:
  what can't be reached is the refusal, while every refund equals its return's value and BR12 caps what is
  returned (the refusal is shown with that rule switched off in `test_br14_refunds`). T2 and T4 already hold the
  order when they insert their refund.
- **The restock order of T2 and T4** (ascending `product_id`). Only T1's order is raced; T2 and T4 use the same
  rule in the same loop shape.
- **BR12's lock order over several lines** (`line_no`). The race test returns one line.
- **The base-price side of BR15's product lock** (`br15_check_base_price`: a promotion racing a base-price change).
- **BR22's `FOR SHARE` on the receiving store.** The same pattern as BR06's, which has a race test.
- **The product lock in `replace_specs`**, which makes two replacements of one product's specs run one after the
  other.
