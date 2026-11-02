# How does the JB Hi-Fi database enforce its business rules? {#jbhifi-db-rules}

All 22 business rules live inside PostgreSQL, not in the API. Rules that one row can decide are constraints; rules that must read other rows are triggers. Every failure carries its `brNN_…` name, and the API returns that name as a 409 error code.

- Keys, domains, `CHECK` and `UNIQUE` decide single-row rules; composite foreign keys add “same order”, “same customer” and “same store”.[](source:tables)
- Triggers handle rules that read other rows: they run before the write and raise SQLSTATE 23514 with the rule's name.[](source:rules-header)
- Where two transactions could both pass a check, the trigger first locks a row both need, so the checks run one after the other.[](source:rules-header)
- `app/errors.py` turns that name into the API's error `code`, and a test breaks every rule on purpose.[](source:trace)

@answer scope="Commit 4d49cf5 · sql/ and app/ · PostgreSQL 18"
@meta locale=en quality_profile=standard
@source tables title="Tables, keys and declarative constraints" path=sql/01_tables.sql lines=1:326
@source domains title="Domains: money_aud, email_address and value lists" path=sql/00_domains.sql lines=1:24
@source rules-header title="How every trigger reports and locks" path=sql/02_rules.sql lines=1:6
@source br07 title="BR07: deferred check that an order has a line" path=sql/02_rules.sql lines=78:94
@source br09 title="BR09: status transition trigger" path=sql/02_rules.sql lines=156:177
@source br09-log title="BR09: AFTER trigger that writes the history, and its guards" path=sql/02_rules.sql lines=179:246
@source br12 title="BR12: an assertion emulated by a trigger" path=sql/02_rules.sql lines=277:309
@source br15 title="BR15: promotion triggers on both tables" path=sql/02_rules.sql lines=366:419
@source br20 title="BR20: paid in full, and why READ COMMITTED matters" path=sql/02_rules.sql lines=477:539
@source append title="Append-only records and TRUNCATE guards" path=sql/02_rules.sql lines=541:577
@source br21 title="BR21: cancelled only when fully refunded" path=sql/02_rules.sql lines=613:635
@source views title="Derived data is computed by views" path=sql/03_views.sql lines=1:23
@source errors title="Constraint name to 409 error code" path=app/errors.py lines=91:97
@source db title="One request, one transaction: commit or roll back" path=app/db.py lines=22:29
@source checkout title="T1 checkout, step by step" path=app/services/orders.py lines=127:193
@source stock title="Conditional stock UPDATE" path=app/services/orders.py lines=219:233
@source locks title="Which locks checkout takes, and in what order" path=app/services/orders.py lines=1:17
@source trace title="Rule traceability: rule, mechanism, test" path=docs/rule-traceability.md lines=1:42
@source race title="Concurrency evidence: faulty pattern versus ours" path=docs/concurrency-evidence.md lines=19:28
@source rc title="Why READ COMMITTED is enough here" path=docs/concurrency-evidence.md lines=129:147
@source pg-trigger title="PostgreSQL 18 documentation: CREATE TRIGGER" url=https://www.postgresql.org/docs/18/sql-createtrigger.html

## How was the database designed? {#design}

@workflow id=design-flow title="From requirement to tested rule"
| req | Requirements R1–R14 | external |
| br | Business rules BR01–BR22 | backend |
| er | ER model | backend |
| tables | Tables and keys | database |
| enforce | Constraints and triggers | database |
| tests | A test per rule | backend |
| req > br | |
| br > er | |
| er > tables | map |
| tables > enforce | brNN_ names |
| enforce > tests | 409 code |

@steps id=design-steps
| s-req | Requirements R1–R14 | What customers and staff must do: browse, order, return, adjust stock, read reports. | design-flow | req |
| s-br | Business rules BR01–BR22 | Each rule keeps a permanent ID, so it can be traced to its constraint, its test and the report. | design-flow | br |
| s-er | ER model | Strong and weak entities, one ISA, one recursive and one M:N relationship with an attribute. | design-flow | er |
| s-tables | Tables and keys | Derived values become views, not columns. One BCNF break is deliberate: `return_line.order_id`. | design-flow | tables |
| s-enforce | Constraints and triggers | One-row rules become constraints; rules over other rows become triggers. Each object is named `brNN_…`. | design-flow | enforce |
| s-tests | A test per rule | `tests/test_business_rules.py` breaks each rule and asserts its name; `tests/test_rule_traceability.py` checks the rule table against the catalog. | design-flow | tests |

## What does the schema look like? {#model}

@diagram erd id=schema-erd source=jbhifi-schema.erd.json title="JB Hi-Fi schema: 19 tables in six areas"

@steps id=model-tour
| t-weak | customer_address | Weak entity: its key `(customer_id, address_no)` includes the owner's key. `order_line`, `order_status_history` and `product_spec` follow the same pattern. | schema-erd | customer_address |
| t-mn | inventory | The M:N relationship between store and product, with `quantity` as its attribute. Its key is `(store_id, product_id)`. | schema-erd | inventory |
| t-isa | staff | The ISA (store employee or support staff) is one table with `staff_type`. BR05's `CHECK` requires a store exactly for store staff. | schema-erd | staff |
| t-circular | store | `manager_id` must work at this store. The composite FK to staff is checked at `COMMIT`, because store and staff point at each other. | schema-erd | store |
| t-xor | user_account | A sign-in belongs to one customer or one staff member: two unique FKs and an XOR `CHECK` (BR19). | schema-erd | user_account |
| t-hub | customer_order | After insert only `status` may change (BR09). The total is not stored: `v_order_total` computes it from the lines. | schema-erd | customer_order |
| t-snapshot | order_line | `unit_price` records the price at sale time, a different fact from today's `base_price`. Lines are never edited (BR08). | schema-erd | order_line |
| t-redundant | return_line | It repeats `order_id` on purpose. The composite FK to `return_request (return_id, order_id)` then proves the line comes from the returned order (BR13). | schema-erd | return_line |

## Which mechanism enforces each rule? {#rules}

```mermaid title="How the 22 rules are enforced (number of rules: 8 + 8 + 6 = 22)"
pie
  "Constraints only" : 8
  "Constraints and triggers" : 8
  "Triggers only" : 6
```

| Rule | What it says | Enforced by |
| --- | --- | --- |
| BR01 | Customer email is unique and well-formed | `UNIQUE (email)`; `email_address` domain `CHECK` |
| BR02 | Money is never negative and has two decimals | `money_aud` domain: `NUMERIC(10,2)` with `CHECK (VALUE >= 0)` |
| BR03 | Stock never goes negative | `CHECK (quantity >= 0)` on `inventory` |
| BR04 | Each store has one manager, who works there | `manager_id NOT NULL` and a composite FK to `staff`, deferred to `COMMIT` |
| BR05 | Store staff have one store; support staff have none | `CHECK ((staff_type = 'support') = (store_id IS NULL))` |
| BR06 | Delivery needs an address; Click & Collect has none and uses a retail store | `CHECK`, plus a trigger on the order side and one on the store side |
| BR07 | Quantity above 0, each product once, still on sale, at least one line | `CHECK`, `UNIQUE`, a `BEFORE INSERT` trigger, a deferred constraint trigger |
| BR08 | An order line is a purchase record | `BEFORE INSERT OR UPDATE OR DELETE` trigger and a `TRUNCATE` guard |
| BR09 | Status follows the allowed moves, and every change is logged | Transition table read by a `BEFORE` trigger; an `AFTER` trigger writes history; guards keep it append-only |
| BR10 | A retried request creates at most one order or return | `UNIQUE (customer_id, idempotency_key)` and `UNIQUE (order_id, idempotency_key)` |
| BR11 | Returns only for completed orders, within 30 days | `BEFORE` trigger that reads `order_status_history` |
| BR12 | Returned quantity never exceeds the quantity bought | `BEFORE` trigger that locks the order line |
| BR13 | A return line comes from the returned order | Composite FK `(return_id, order_id)` to `return_request` |
| BR14 | Each refund is for a return or a cancellation, never above the charge; payments are append-only | `UNIQUE`, `CHECK`, three `BEFORE INSERT` triggers, append-only triggers |
| BR15 | Promotions never overlap; the sale price stays below the base price | A trigger on `promotion` and one on `product` |
| BR16 | Addresses are never edited | `BEFORE UPDATE` trigger |
| BR17 | A delivery address is the customer's own, current address | Composite FK and a `BEFORE INSERT` trigger |
| BR18 | Stock changes are logged by staff of that store | Composite FK, a reason-and-sign `CHECK`, an append-only trigger |
| BR19 | A sign-in is one customer or one staff member, never both | XOR `CHECK` and two `UNIQUE` constraints |
| BR20 | Paid only when charged exactly the total, once, while placed | Two triggers and a partial unique index |
| BR21 | Cancelled only when refunds equal charges | `BEFORE UPDATE` trigger that reads `v_order_payment` |
| BR22 | Returns are received at a retail store, by its staff | Trigger and composite FKs to `staff` |

The full table, with the tests that break each rule, is `docs/rule-traceability.md`.[](source:trace)

## What happens when checkout marks an order paid? {#triggers}

@sequence id=paid-move title="Checkout moves an order from placed to paid"
| actor svc | Checkout service | backend |
| actor ord | customer_order | database |
| actor trg | BEFORE triggers | database |
| actor hist | order_status_history | database |
| actor api | Error handler | backend |
| actor web | Storefront | frontend |
| phase | One transaction, READ COMMITTED |
| svc | ord | UPDATE status = 'paid' |
| ord | trg | fire in name order |
| trg | ord | all pass: RETURN NEW | return |
| ord | hist | AFTER trigger logs the move |
| svc | ord | COMMIT runs deferred br07 |
| phase | If any check fails |
| trg | svc | RAISE 23514 with rule name | return |
| svc | api | IntegrityError, rolled back |
| api | web | 409, code = rule name |

@steps id=paid-steps
| p-before | BEFORE triggers | `br09_order_header_immutable`, `br09_order_status_transition`, `br20_paid_in_full` and `br21_cancelled_order_refunded` run in name order. An illegal move therefore fails as BR09 before BR20 checks money. | paid-move | trg |
| p-history | order_status_history | `br09_log_status_change` inserts the next `seq`, with the staff member from `app.staff_id`. A guard refuses rows that no trigger wrote. | paid-move | hist |
| p-commit | customer_order | At `COMMIT`, the deferred `br07_order_has_lines` confirms the order has at least one line. | paid-move | ord |
| p-error | Error handler | It reads `e.diag.constraint_name` and answers 409 with that name as `code`. Nothing from the transaction is kept. | paid-move | api |

Triggers on the same event fire in alphabetical order of their names, so the rule names also set the order of the checks.[](source:pg-trigger) The service commits only if every statement succeeds; any error rolls back the whole request.[](source:db)

## What does a trigger look like? {#trigger-anatomy}

@code source=br09 language=sql

| Trigger kind | When it runs | Used for |
| --- | --- | --- |
| `BEFORE` row trigger | Before each row is written; raising an error stops the statement | The checks of BR06–BR22 |
| `AFTER` row trigger | After the row is written | `br09_log_status_change` writes the history row |
| Constraint trigger, `DEFERRABLE INITIALLY DEFERRED` | At `COMMIT` | `br07_order_has_lines`: lines are inserted after their order |
| Statement trigger, `BEFORE TRUNCATE` | Once per `TRUNCATE`, which skips row triggers | Append-only tables: payments, history, stock log, order and return lines |

Every trigger ends with `RAISE EXCEPTION … USING ERRCODE = 'check_violation', CONSTRAINT = 'brNN_…'`.[](source:rules-header) To the API, a trigger rule then looks exactly like a `CHECK` violation.[](source:errors) PostgreSQL has no multi-table assertion, so BR12 and BR20 emulate one with a trigger.[](source:br12)

## Which status moves does BR09 allow? {#order-states}

@diagram lifecycle id=order-status-flow source=order-status.lifecycle.json title="Order status moves allowed by order_status_transition"

The allowed moves are 13 rows of data, not code: 6 for delivery and 7 for Click & Collect.[](source:br09) Adding a move is an `INSERT`, and the cancellation-refund trigger reads the same table. Two moves carry extra gates: BR20 on placed → paid and BR21 on any move to cancelled.[](source:br21)

## Why do some triggers lock a row first? {#races}

| Race | Without protection | What stops it |
| --- | --- | --- |
| Two checkouts want the last unit | Both read 1 and both sell it | `UPDATE inventory … WHERE quantity >= n`: the second waits, re-checks, updates 0 rows and gets 409 `out_of_stock`. BR03 is the backstop. |
| A double click on Place order | Two orders | `UNIQUE (customer_id, idempotency_key)` with `ON CONFLICT DO NOTHING`: the second request returns the first order (BR10) |
| Two overlapping promotions at once | Each check sees no overlap (write skew) | BR15's trigger locks the product `FOR UPDATE`; the second waits, then fails |
| Two returns for the last units of a line | Both pass the quantity cap | BR12's trigger locks the order line `FOR UPDATE` |
| Two refunds for one order | Refunds exceed the charge | BR14's trigger locks the order `FOR UPDATE` |
| A line added while the order turns paid | BR20 checks a total without that line | BR08 and BR20 triggers lock the order row |
| A Click & Collect order while the store becomes a warehouse | Both commit | BR06 reads the store `FOR SHARE`, so the store update waits |

The lock works under READ COMMITTED because, after waiting, the trigger's next query takes a fresh snapshot and sees the other commit.[](source:br20) Rows are locked in one order, the order row first and then inventory by ascending `product_id`, so two transactions cannot deadlock.[](source:locks) `docs/concurrency-evidence.md` runs each faulty pattern beside ours and records what PostgreSQL reports.[](source:race)

## How do you answer the usual design questions? {#defend}

| Question | Answer |
| --- | --- |
| Why triggers and not `CHECK` constraints? | A `CHECK` sees only the row being written. BR11, BR12, BR14, BR15 and BR20 read other rows, and PostgreSQL has no `CREATE ASSERTION`. |
| Why store `unit_price` when `product` has `base_price`? | It is the price at sale time, a different fact. There is no dependency product → `unit_price`, so it is not redundancy. |
| Why are order totals not stored? | A total is derived data. `v_order_total` computes it from the lines, so it can never disagree with them. |
| Doesn't `return_line.order_id` break BCNF? | Yes: `return_id` → `order_id`. The composite FK to `return_request` makes a wrong copy impossible, and it enforces BR13 without a trigger. |
| How is the staff ISA mapped? | One table with a `staff_type` discriminator. BR05's `CHECK` ties `store_id` to the type. |
| Why is the manager FK deferred? | `store` and `staff` reference each other. A new store and its manager go in one transaction, so the FK is checked at `COMMIT`. |
| Why `UNIQUE (store_id, staff_id)` if `staff_id` is the key? | It gives composite FKs a target, “staff member X of store S”, for BR04, BR18 and BR22. |
| Why keep status moves in a table? | The BR09 trigger only looks the move up. Changing the workflow is a data change, not a code change. |
| Who writes `order_status_history`? | Only the `AFTER` trigger. A `pg_trigger_depth()` guard refuses direct inserts, and other triggers block updates and deletes. |
| Why not an exclusion constraint for BR15? | It needs the `btree_gist` extension, which is beyond the unit. The trigger locks the product and checks for overlap instead. |
| Why READ COMMITTED and not SERIALIZABLE? | Targeted locks already serialise the risky checks. SERIALIZABLE would abort one transaction with 40001, and every service would need a retry loop. |
| Why can't an address be edited? | Old orders point at it. Editing means retiring it with `is_active` and adding a new row (BR16); BR17 refuses retired addresses for new orders. |

Answers about READ COMMITTED follow the project's own evidence and argument.[](source:rc)

## How can you show it working? {#demo}

- [ ] Start the database with `docker compose up -d`.
- [ ] Run `pytest tests/test_business_rules.py`: each test breaks one rule and asserts its `brNN_…` name.
- [ ] Run `pytest tests/test_rule_traceability.py` to show the rule table matches the database catalog.
- [ ] Run `pytest -s tests/test_concurrency_evidence.py` to replay the races and print what each pattern does.
- [ ] In psql, break BR09 inside a transaction and read the `CONSTRAINT NAME` line.

```sql title="Break BR09 on purpose (psql, rolled back)"
-- docker compose exec db psql -U jbhifi -d jbhifi
\set VERBOSITY verbose
BEGIN;
UPDATE customer_order SET status = 'picking'
WHERE order_id = (SELECT order_id FROM customer_order WHERE status = 'delivered' LIMIT 1);
-- expect: A delivery order cannot move from delivered to picking
-- and:    CONSTRAINT NAME:  br09_order_status_transition
ROLLBACK;
```
