# Concurrency Evidence Implementation Plan

> **For agentic workers:** implement task by task (superpowers:executing-plans). Steps use `- [ ]`.

**Goal:** paired tests — the faulty pattern and ours — for lost update, deadlock and write skew, and
`docs/concurrency-evidence.md` that report §4 quotes.

**Architecture:** a small support module that runs each transaction on its own connection and waits for a blocked
one through `pg_stat_activity`; one test file with the scenarios; one document. No product code, no `sql/`.

**Tech Stack:** PostgreSQL 18, psycopg2, pytest, `concurrent.futures`.

**Spec:** `docs/superpowers/specs/2026-10-16-concurrency-evidence-design.md`

## Global Constraints

- Tests: `/Users/ethan/Dev/Course/comp9120/JBhifi/.venv/bin/pytest` (test DB `jbhifi_test_sp3` from `.env`).
- No changes to `app/`, `sql/` or the web; the real triggers are never disabled.
- Every test rolls back and closes every connection in `finally`; demo tables are `demo_promotion_<random>`,
  dropped `IF EXISTS` first and at the end.
- `lock_timeout = '10s'` on every racing connection; no `sleep` to order steps.
- No AI attribution in commits, PR, progress, spec or plan.

## Review Focus

- A thread's exception must reach the test (a future's `.result()`), never be swallowed → every future is read.
- The deadlock victim is PostgreSQL's choice → assert exactly one `DeadlockDetected`, not which.
- SSI may abort at the second `INSERT` or at `COMMIT` → the serializable test accepts either step, asserts exactly
  one 40001.
- `wait_until_blocked` must fail loudly (not pass) if the connection never blocks → it raises after a timeout.
- Rows committed by one test can't leak into another's assertions → each test makes its own products.

---

### Task 1: Support module and the lost-update pair

**Files:** create `tests/concurrency_support.py`, `tests/test_concurrency_evidence.py`.

**Produces:** `begin(isolation="READ COMMITTED") -> conn` (own connection, isolation first, `lock_timeout`);
`backend_pid(conn) -> int`; `wait_until_blocked(pid, timeout=5.0) -> float` (seconds polled, raises
`AssertionError` on timeout); `a_stocked_product(quantity, store_id=1) -> int` (committed); `stock(product_id,
store_id=1) -> int`; `close_all(*conns)` (rollback + close, ignoring already-closed). Uses
`concurrent.futures.ThreadPoolExecutor` in the tests.

- [ ] `test_read_then_write_back_loses_an_update_and_sells_the_last_unit_twice` (both commit, stock 0, two sales,
  no `CheckViolation`).
- [ ] `test_conditional_update_sells_the_last_unit_once` (A 1 row; B blocked → after A commits, B 0 rows; stock 0).
- [ ] `test_conditional_update_under_repeatable_read_fails_with_a_serialization_error_instead` (B blocked → after
  A commits, `SerializationFailure`, pgcode 40001; stock 0).
- [ ] Run; mutation check: drop `AND quantity >= 1` from the "ours" statement → the test fails (two rows / −1 →
  BR03). Commit `Concurrency evidence: lost update, and the conditional UPDATE that prevents it`.

### Task 2: The deadlock pair

- [ ] `test_locking_two_rows_in_opposite_orders_deadlocks_and_postgres_aborts_one` (`deadlock_timeout = '100ms'`;
  exactly one `DeadlockDetected`, 40P01; the survivor commits; the victim's stock change is rolled back).
- [ ] `test_locking_rows_in_product_id_order_makes_the_second_wait_and_both_succeed` (B blocked on P1 while
  holding nothing; both commit; each product −2).
- [ ] Run; commit `Concurrency evidence: a deadlock from opposite lock orders, and none in product_id order`.

### Task 3: The write-skew trio

- [ ] `test_check_then_insert_under_read_committed_lets_two_overlapping_promotions_in` (demo table; 2 overlapping
  rows).
- [ ] `test_check_then_insert_under_serializable_aborts_one_and_its_retry_is_refused` (exactly one 40001; the retry
  sees the other row and inserts nothing; 1 row).
- [ ] `test_br15_locks_the_product_so_two_overlapping_promotions_have_one_winner` (real `promotion`; B blocked in
  the trigger's `FOR UPDATE`; then `br15_promotion_no_overlap`; 1 promotion).
- [ ] Run; commit `Concurrency evidence: write skew under READ COMMITTED and SERIALIZABLE, and BR15's product lock`.

### Task 4: Document, progress, PR

- [ ] `pytest -s tests/test_concurrency_evidence.py` → paste the printed results; write
  `docs/concurrency-evidence.md` (summary table, scenarios, tutor question 4 with the list of tests that pin every
  conditional `UPDATE` and parent lock, scope label).
- [ ] Full `pytest`; the file five times in a row; `doc/progress.md` entry; push; PR with "Plan changes" (§5
  concurrency story, §8 test list) and the five-run result.
