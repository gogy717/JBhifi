# Business rules BR01–BR18

Every rule lives in the database, normally as a named constraint or trigger whose name begins `brNN_`.
`app/errors.py` turns a violation into `409 Conflict` with `error.code` equal to that constraint name, so
the API and the browser show the database's own answer rather than a second copy of the rule.

Trigger rules raise SQLSTATE `23514` (`check_violation`) with `CONSTRAINT = 'brNN_…'`, which is why a
trigger rule and a CHECK rule look identical to the client. When two transactions could both pass a check,
the trigger takes a row lock (`SELECT … FOR UPDATE`) first so the checks run one after the other.

Direct rule tests are in `tests/test_business_rules.py` unless noted.

## The rules

| Rule | Meaning | Mechanism (exact name) | Service responsibility | Tests |
|---|---|---|---|---|
| BR01 | A customer's email is well-formed and unique, stored lower-case | domain `email_address` (`br01_email_format`) and `br01_customer_email_unique` | any future customer-creation API normalises before inserting; the demo seed already stores lower case | `test_br01_email_is_well_formed`, `test_br01_email_is_unique` |
| BR02 | Money is non-negative with exactly two decimals | domain `money_aud` (`br02_money_nonneg`) | all money is `NUMERIC(10,2)`/`Decimal`; the API never accepts floats for prices | `test_br02_money_is_never_negative` |
| BR03 | Stock never goes negative | `br03_inventory_qty_nonneg` | checkout decrements conditionally (`… WHERE quantity >= %s`); cancellations and returns restock relatively | `test_br03_stock_never_goes_negative`, `tests/test_transactions.py`, `tests/test_checkout_transactions.py` |
| BR04 | A store's manager works at that store | `br04_store_manager_works_here`, a deferred composite FK | no API changes stores; the seed and tests create a store and its manager in one transaction | `test_br04_manager_works_at_the_store`, `test_br04_a_new_store_and_its_manager_in_one_transaction` |
| BR05 | Store staff have a store; support staff do not | `br05_staff_store_matches_type` | the session actor reads `staff_type`/`store_id` from the row, never from the cookie | `test_br05_store_staff_have_a_store_and_support_staff_do_not` |
| BR06 | Delivery orders have an address; Click & Collect is at a retail store | `br06_order_address_matches_method` and trigger `br06_collect_at_retail_store` | checkout rejects a non-retail collection store with the same code the trigger would raise | `test_br06_delivery_has_an_address_and_collect_does_not`, `test_br06_collect_only_at_a_retail_store` |
| BR07 | A line's quantity is positive and a product appears once per order | `br07_order_line_qty_positive`, `br07_order_line_product_once` | checkout rejects duplicate lines as a 422 before writing | `test_br07_line_quantity_is_positive_and_a_product_appears_once` |
| BR08 | An order line keeps the price, product and quantity it was sold at | trigger `br08_order_line_immutable` (unit-price changes report `br08_unit_price_immutable`) | checkout writes the server's current price; nothing may edit a committed line | `test_br08_unit_price_never_changes`, `tests/test_lifecycle_rules.py` |
| BR09 | Status follows the allowed transitions for the fulfilment method, and every change is logged | `order_status_transition` rows, trigger `br09_order_status_transition`, history trigger `br09_log_status_change` | staff fulfilment uses the transition table as the authority; the customer's checkout sets `placed → paid` | `test_br09_new_orders_start_as_placed`, `test_br09_status_moves_only_along_allowed_transitions`, `test_br09_every_status_change_is_logged_with_who_made_it` |
| BR10 | A retried checkout creates at most one order | `br10_order_idempotency_unique (customer_id, idempotency_key)` plus `request_fingerprint` | checkout resolves the key under the customer lock: a replay returns the order, changed content is `409 idempotency_conflict` | `test_br10_one_order_per_idempotency_key`, `tests/test_checkout.py` |
| BR11 | Returns only for delivered or collected orders, within 30 days | trigger `br11_return_window` using `return_request_is_in_window`; `requested_at` is server-generated | the return service resolves a replay before the window check, then relies on the trigger | `test_br11_only_completed_orders_can_be_returned`, `test_br11_a_just_completed_order_can_be_returned`, `tests/test_lifecycle_rules.py` |
| BR12 | Returned quantity never exceeds the quantity bought | trigger `br12_return_qty_within_purchased`; `br12_return_line_ownership` and `br12_return_line_editable` guard the row's life | one returning customer's requests are serialised by the trigger's lock on the order line | `test_br12_cannot_return_more_than_was_bought`, `test_br12_rejected_returns_do_not_count`, `test_br12_a_rejected_return_cannot_be_reopened`, `tests/test_rule_concurrency.py` |
| BR13 | Return lines come from the returned order | composite FKs `br13_return_line_same_order` and `return_line_order_line_fk` | the return service copies `order_id` from the parent request and `line_no` from the purchased lines | `test_br13_return_lines_come_from_the_returned_order` |
| BR14 | Refunds never exceed what was charged, and each source refunds once | `br14_refund_has_source`, `br14_refund_once_per_return`, `br14_refund_once_per_cancellation`, triggers `br14_refunds_within_charged` and `br14_refund_matches_source`, and the deferred `br14_source_complete` | `payments.record_charge`/`record_refund` write the ledger; cancellation and return processing set `SET CONSTRAINTS ALL IMMEDIATE` before returning | `test_br14_refunds`, `tests/test_lifecycle_schema.py`, `tests/test_rule_concurrency.py` |
| BR15 | A promotion is below the base price and promotions never overlap | trigger `br15_promotion_rules` (`br15_promotion_below_base_price`, `br15_promotion_no_overlap`) and `br15_base_price_above_promotions` | the admin promotion/service writes through the trigger; checkout reads the price from `v_product_current_price` | `test_br15_sale_price_is_below_the_base_price`, `test_br15_promotions_for_a_product_never_overlap`, `test_br15_base_price_stays_above_current_promotions` |
| BR16 | Addresses are never edited, only replaced | trigger `br16_address_immutable`: only `is_active` may change | the account service only inserts a new address or sets `is_active = false`; an order keeps pointing at the address row it was placed with | `test_br16_addresses_are_immutable` |
| BR17 | A delivery address belongs to the ordering customer | composite FK `br17_order_address_is_customers` | checkout locks and checks the customer's own active address before writing | `test_br17_delivery_address_belongs_to_the_customer` |
| BR18 | Every manual stock change is logged and the log is append-only | `br18_adjustment_staff_at_store`, `br18_adjustment_delta_matches_reason`, `br18_adjustment_append_only`, `quantity_after` snapshot | `app/services/inventory.py` writes the inventory update and the log row in one transaction; the actor comes from the session, never the body | `test_br18_only_staff_of_that_store_adjust_its_stock`, `test_br18_change_matches_its_reason`, `test_br18_the_log_is_append_only` |

`test_current_price_includes_the_running_promotion` covers `v_product_current_price` itself.

## Rules that are not business rules

The schema also protects records that no numbered rule names, because an audit or financial record is
worthless if it can be rewritten:

| Protection | Trigger |
|---|---|
| A placed order keeps its customer, key, fulfilment method, store, address and placement time; only `status` may move | `order_immutable` |
| The payment ledger cannot be edited or deleted | `payment_append_only` |
| Order and return status histories cannot be edited or deleted | `order_status_history_append_only`, `return_status_history_append_only` |
| A cancellation record cannot be edited or deleted | `order_cancellation_append_only` |
| A category cannot be moved into its own subtree | `category_no_cycle` |
| A return moves only `requested → received → refunded`, or `requested`/`received → rejected` | `return_status_transition` |

## Where the rules are exercised

| Test file | What it proves |
|---|---|
| `tests/test_business_rules.py` | one direct violation per BR01–BR18, asserted against the constraint name |
| `tests/test_transactions.py` | two concurrent stock adjustments on one row, without a lost update |
| `tests/test_lifecycle_rules.py`, `tests/test_lifecycle_schema.py` | the record guards above, the exact 30-day boundary, category cycles, role permissions and the deferred BR14 completeness checks |
| `tests/test_rule_concurrency.py` | BR12, BR14 and BR15 races that could otherwise be decided by write skew |
| `tests/test_api.py` | every endpoint, and that a rule violation reaches the client as a `409` with the constraint name |
| `tests/test_auth.py` | who may act, and that the actor never comes from the request body |
| `tests/test_checkout.py`, `tests/test_checkout_transactions.py`, `tests/test_order_reads.py` | checkout as one transaction, safe replay, protected order reads |
