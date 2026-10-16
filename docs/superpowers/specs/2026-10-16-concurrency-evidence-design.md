# Concurrency evidence for report §4 — design

Status: approved on 2026-10-16. Branch `gogy717/concurrency-evidence`, from `main` at `f13f35e`. Tests and one
document only: no product code, no `sql/`.

**Goal.** The existing tests show our transactions are right. Report §4 also needs the contrast: what goes wrong
without each technique, and how PostgreSQL reports it. Each scenario gets a test of the faulty pattern and a test
of ours, named so the reader sees what is being shown, and `docs/concurrency-evidence.md` gives the observed
results and answers tutor question 4 (plan §12: is `READ COMMITTED` + conditional `UPDATE` enough, or should we
demonstrate `SERIALIZABLE`?).

**Scope label.** The brief puts transactions in Week 9 and caps the scope at Week 10, but neither course document
lists whether isolation levels were taught. Until the user confirms it against the Week 9 transactions lecture,
the `SERIALIZABLE` and `REPEATABLE READ` material is marked *optional — confirm against the Week 9 transactions
lecture*.

## 1. How two transactions are interleaved reliably (`tests/concurrency_support.py`)

- Each transaction is its own connection (not autocommit; the isolation level is its first statement) with
  `SET LOCAL lock_timeout = '10s'`, so a locking regression fails a test instead of hanging it.
- Steps that can't block run in the main thread in a fixed order (A reads, B reads, A writes, …): deterministic,
  no sleeps.
- A statement that will block runs in a `ThreadPoolExecutor` future; the main thread polls `pg_stat_activity`
  until that connection's `wait_event_type = 'Lock'` (`wait_until_blocked(pid)`), then takes the next step. The
  waiting time recorded for the document is "polled until blocked", not exact.
- The deadlock test sets `deadlock_timeout = '100ms'` locally (the test role is a superuser; the default is 1 s)
  only to make it faster.
- Every test makes and commits its own rows, and in `finally` rolls back and closes every connection it opened.

## 2. Scenarios (`tests/test_concurrency_evidence.py`)

| # | Faulty pattern | Ours |
|---|---|---|
| 1 Lost update (`inventory`, 1 unit, BR03's `CHECK`) | `test_read_then_write_back_loses_an_update_and_sells_the_last_unit_twice`: both read 1, each writes back `quantity = 0` computed in Python; both "sell", stock 0, the `CHECK` never fires (the 2026-09-25 ORM experiment, without the ORM) | `test_conditional_update_sells_the_last_unit_once`: `quantity = quantity - 1 … AND quantity >= 1`; B waits for A's row lock, re-checks the newest row and updates 0 rows. Extra: `test_conditional_update_under_repeatable_read_fails_with_a_serialization_error_instead` — the same at `REPEATABLE READ` gives B 40001, so every service would need a retry |
| 2 Deadlock (two products, P1 < P2) | `test_locking_two_rows_in_opposite_orders_deadlocks_and_postgres_aborts_one`: A holds P1 and wants P2, B holds P2 and wants P1; exactly one gets `DeadlockDetected` (40P01) and is rolled back (which one is PostgreSQL's choice) | `test_locking_rows_in_product_id_order_makes_the_second_wait_and_both_succeed`: both take P1 first, so B waits holding nothing, then both commit (T1, T2, T4's rule) |
| 3 Write skew (BR15: one product's promotions never overlap) | `test_check_then_insert_under_read_committed_lets_two_overlapping_promotions_in` and `test_check_then_insert_under_serializable_aborts_one_and_its_retry_is_refused` on a demo table | `test_br15_locks_the_product_so_two_overlapping_promotions_have_one_winner`: the real trigger takes the product `FOR UPDATE`; B waits, and its overlap check — the next statement in the PL/pgSQL function, so a fresh snapshot under `READ COMMITTED` — sees A's promotion: `br15_promotion_no_overlap` |
| 4 Non-repeatable read | — | referenced, not rewritten: SP4's `test_repeatable_read_keeps_a_sale_committed_mid_report_out_of_every_section` and `test_read_committed_would_let_a_sale_committed_mid_report_into_later_sections` |

The faulty BR15 pattern runs on a committed table `demo_promotion_<random>` with no trigger, dropped at the start
(`IF EXISTS`) and the end, because the real trigger can't be bypassed fairly: `ALTER TABLE … DISABLE TRIGGER` takes
an `ACCESS EXCLUSIVE` lock, which would itself serialise the two transactions and hide the anomaly.

## 3. Document (`docs/concurrency-evidence.md`)

A summary table first (scenario | faulty test | our test | observed | mechanism: conditional `UPDATE`, lock order,
parent lock, isolation level). Then per scenario: the problem, the tests, the observed results (numbers printed by
`pytest -s`, waits marked as polled), and why ours is right. Then tutor question 4: each rule that depends on
concurrency either checks in the write itself (a conditional `UPDATE`) or locks a parent row `FOR UPDATE` before
checking (BR12, BR14, BR15, BR20, T2), so under `READ COMMITTED` a second transaction waits for the first and checks
on a fresh snapshot; `SERIALIZABLE` stops write skew without explicit locks but needs a 40001 retry in every service
and can abort on false positives, so it is shown as the alternative, not adopted; `REPEATABLE READ` is used only for
the read-only report snapshot. Every conditional `UPDATE` and parent lock is pinned by a test, listed by name.

## 4. Verification

Full `pytest`; `test_concurrency_evidence.py` five times in a row; the results go in the PR and `doc/progress.md`.
Each "ours" test is the faulty test with the technique added, so each pair shows that removing the technique
breaks the rule.
