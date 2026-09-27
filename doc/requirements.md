# Requirements and implementation decisions

This file is the canonical record of *what this project must do* and *which decisions fill the gaps*.
It was written from the recovered repository (README, `web/README.md`, `web/src/lib/shop-pages.ts`,
`doc/progress.md`, `sql/`) during the implementation audit on 2026-09-26, because the brief the code
refers to (`.claude/plan.md`) is not present in either checkout. Where the original numbered wording is
unavailable it is marked **unknown**, and nothing is invented in its place.

## 1. Working tree

- The implementation targets the **repository root**: the checkout containing this file.
- `JBhifi/` is a nested second checkout recorded as a Git gitlink (commit `84dbbb1`) with no tracked
  `.gitmodules`. Every regular tracked root file had an identical copy there at audit time. It is left in
  place and **not** modified: do not implement changes twice. The team still has to decide whether to keep
  it as a submodule, fold it in, or remove it — that decision is not made here.
- `todo.md` (the implementation plan) is kept as the task list; this file records only the agreed
  requirements and decisions.

## 2. Recovered requirements

Only the requirements quoted by the repository are listed. The wording is the repository's own.

| ID | Requirement (recovered wording) | Where it is stated |
|---|---|---|
| R1 | Browse by category and brand, search, filter by price | `web/src/lib/shop-pages.ts` |
| R2 | Current price, including any active promotion | `web/src/lib/shop-pages.ts` |
| R3 | A product's stock at each store | `web/src/lib/shop-pages.ts` |
| R4 | Place an order for delivery or Click & Collect | `web/src/lib/shop-pages.ts` |
| R5 | View orders with a status timeline | `web/src/lib/shop-pages.ts` |
| R6 | Request returns for completed orders | `web/src/lib/shop-pages.ts` |
| R11 | Every status change is auditable | `web/src/lib/shop-pages.ts` |
| R13 | Manual stock adjustments are logged (who, why, how much, quantity left) | `doc/progress.md` |

**Unknown.** R7, R8, R9, R10 and R12 are referenced only by number, with no recovered wording, and the
original T3+ task definitions are likewise absent. They are **not** invented here. The `shop-pages.ts`
slice labels ("A — Catalogue & stock", "B — Orders & checkout", "C — Returns, staff & reporting") are the
only recovered statement of the intended module structure.

## 3. Business rules BR01–BR18 (as implemented in `sql/`)

The rules live in the database; their exact mechanisms and tests are in `doc/business-rules.md`.

| Rule | Statement |
|---|---|
| BR01 | Customer email is well-formed and unique (stored lower-case). |
| BR02 | Money is non-negative with exactly two decimals. |
| BR03 | Stock never goes negative. |
| BR04 | A store's manager works at that store. |
| BR05 | Store staff have a store; support staff do not. |
| BR06 | Delivery orders have an address; Click & Collect is at a retail store. |
| BR07 | Line quantity > 0 and a product appears once per order. |
| BR08 | An order line keeps the price it was sold at. |
| BR09 | Status follows the allowed transitions for the fulfilment method and is logged. |
| BR10 | A retried checkout creates at most one order. |
| BR11 | Returns only for completed (delivered/collected) orders, within 30 days. |
| BR12 | Returned quantity never exceeds the quantity bought. |
| BR13 | Return lines come from the returned order. |
| BR14 | Refunds never exceed what was charged, and each source refunds once. |
| BR15 | Promotions are below the base price and never overlap. |
| BR16 | Addresses are never edited, only replaced; history is retained. |
| BR17 | A delivery address belongs to the ordering customer. |
| BR18 | Every manual stock change is logged, and the log is append-only. |

## 4. Proposed implementation decisions

These defaults make the recovered scope implementable. They are proposals recorded for team agreement,
not quotations from the missing brief.

1. **Identity and permissions.** A signed, HTTP-only demo session carries either a customer or a staff
   identity; guest browsing stays available. Customers reach only their own account/orders/returns. Store
   staff adjust stock and fulfil orders for their own store, and receive returns at their own retail
   store; support staff read across stores without store-only mutation rights; managers maintain the
   catalogue and promotions. The identity pickers remain explicitly labelled as a demo, and the login
   endpoints are disabled when demo mode is off.
2. **One order, one fulfilment store.** `customer_order.fulfilling_store_id` is preserved; there are no
   split shipments. Click & Collect offers retail stores only; delivery uses a single fulfilment location,
   defaulting to the warehouse but allowing another store with sufficient stock.
3. **Prices and payment.** Prices come from `v_product_current_price` computed inside checkout, never from
   the cart. The submitted `expected_total` is only a comparison value: a changed total returns
   `409 price_changed` before anything commits. Charges/refunds are simulated; no card fields.
4. **Zero-value purchases.** A zero-total order and a zero-value return are allowed; no zero-valued
   `payment` row is written (the domain permits zero, but a payment must be positive). Status and stock
   still advance.
5. **Idempotency.** `Idempotency-Key` is a UUID. Orders scope it to the customer; return requests scope it
   to the order. A normalised request fingerprint distinguishes a replay from changed content: a replay
   returns the same resource without repeating side effects, and the same key with different content
   returns `409 idempotency_conflict`. Staff receive/process/cancel operations are safe to retry through
   locked status checks and unique source records.
6. **Cancellation.** Existing legal cancellation transitions are preserved. A separate cancellation record
   plus a `payment.cancellation_id` reference expresses the refund — an uncompleted order never fabricates
   a merchandise return. Restock and refund happen once, in the cancellation transaction; cancellation is
   exposed to authorised staff.
7. **Returns.** A request is made against a completed order within the inclusive 30-day window; rejected
   requests release their reserved quantities. Receiving records location and staff without restocking.
   Processing a received return atomically restocks the accepted quantities, records the refund and moves
   the return to `refunded`. Rejected/refunded are final. Returned items are assumed resaleable; damaged
   disposition is out of scope.
8. **Audit and history.** Order and return status trails are append-only, and committed financial records
   and purchased line snapshots are immutable. The actor is taken from the verified session via
   transaction-local `set_config`, never from an arbitrary submitted staff id.
9. **Cart and navigation.** A browser cart stores product ids and quantities only and reserves no stock.
   It survives a demo-customer change but identity-specific data and any pending checkout key are cleared.
   The `q` and `category` URL keys emitted by the home page and header are preserved, with `brand`,
   `min_price` and `max_price` added.
10. **Reporting/assessment.** Operational order/return screens come first. The three reports in T16 are a
    **proposed** default because the repository names a reporting slice but supplies no specification; the
    decision to retain them is recorded in §6.

## 5. Definition of done

The recovered scope is complete when:

- All nine customer routes that were reserved (`/products`, `/products/[id]`, `/cart`, `/checkout`,
  `/orders`, `/orders/[id]`, `/returns`, `/stores`, `/account`) perform their documented functions.
- Catalogue/category/brand/current-price filtering and per-store availability work with the existing home
  links.
- Customer, staff and resource/store permissions are enforced by the API, not the browser.
- Delivery and retail-collection checkout commit order/lines/stock/payment/history together and replay
  safely.
- Customers can inspect orders, purchase-time amounts, retained addresses and full timelines.
- Staff can progress both fulfilment paths, cancel in the allowed states, and receive/reject/process
  returns with exactly-once stock and payment effects.
- BR01–BR18 plus the lifecycle and concurrency cases have passing, meaningful tests.
- Demo data, model/rule/transaction notes and AI-use acknowledgements are current.

## 6. Reporting scope decision

The repository names a "Returns, staff & reporting" slice but provides no report specification. Rather
than advertise unbuilt reports, the three proposed reports (sales, low stock, returns) are recorded here
as **retained scope for this delivery**, with the precise grain/filter definitions in `doc/reports.md`.
Anything not so defined — hiring, transfers, manager reassignment, support tickets — is explicitly out of
scope and must not be fabricated.

## 7. Explicitly out of scope

Real payment processing, real identity/login verification, product images, external search, an ORM,
deployment/publishing, damaged-item disposition, split shipments and support-ticket management.
