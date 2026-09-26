# Demonstration

This is the walkthrough the team can run in a tutorial or a recorded demo. It uses one disposable
database, built in one command, that already contains orders at every stage of both fulfilment paths,
returns in every state, a paid cancellation and a deliberately empty store.

The reference data alone (`sql/10_seed_reference.sql`) is enough to browse the catalogue and adjust stock.
The demo scenarios are added by `scripts/seed_demo.py`.

## 1. Build the demo database

From the repository root, with Docker running and the virtual environment active:

```powershell
python scripts/seed_demo.py --database jbhifi_demo --create --seed 9120
```

`--create` drops and rebuilds `jbhifi_demo` from `sql/*.sql`, then adds the scenarios. Without it, the
script seeds an existing disposable database. It refuses to run against `POSTGRES_DB` (`jbhifi`) or any
name that does not end in `_demo` or `_test`, and a second run against the same database stops with
"already contains the demo scenarios" instead of duplicating orders.

Point the API at the seeded database:

```powershell
$env:POSTGRES_DB = "jbhifi_demo"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then start the storefront in another terminal: `cd web; npm run dev`, and open <http://localhost:3000>.
Use **Signed in as** to pick one of the four demo customers and **My store** to pick a retail store.

## 2. What the seeder put there

| Scenario | Customer | Fulfilment | Final state | What it demonstrates |
|---|---|---|---|---|
| `delivery_refunded_partial` | Alice Morgan | Delivery from Eastern Creek DC | Delivered, one line partly refunded | A completed order, a partial return, a restocked item and the original purchase price |
| `collection_return_requested` | Ben Okafor | Click & Collect, Melbourne Central | Collected, a return waiting | The store returns desk has something to receive |
| `delivery_return_received` | Tom Fraser | Delivery from the warehouse | Delivered, a return received | Received is not refunded yet: no money has moved and no stock is back |
| `delivery_return_rejected` | Alice Morgan | Delivery from the warehouse | Delivered, a return rejected | A rejected return stays visible and is final |
| `collection_multiline_refunded` | Ben Okafor | Click & Collect, Melbourne Central | Collected, line 2 refunded | A refund computed from the purchase-time price, not today's promotion |
| `collection_expired_window` | Mei Zhou | Click & Collect, Brisbane City | Collected 45 days ago | The 30-day window has closed: the order page explains why it cannot be returned |
| `delivery_picking` | Alice Morgan | Delivery | Picking | A delivery order part-way through fulfilment |
| `collection_ready` | Tom Fraser | Click & Collect, Sydney CBD | Ready | The highlighted "ready to collect" state |
| `collection_fresh_paid` | Alice Morgan | Click & Collect, Sydney CBD | Paid | A brand-new order for the staff queue |
| `delivery_cancelled` | Mei Zhou | Delivery | Cancelled after payment | A cancellation refund and a restock, with no fabricated merchandise return |
| — | — | — | `LG-43UT8050` at Sydney CBD has 0 stock | An out-of-stock checkout, and the logged `stocktake` adjustment that emptied it |

Together these cover every order status except `shipped` (no scenario is in transit, because the shipping
step is a single click in the staff queue) and every return status.

## 3. The scripted walkthrough (verified)

`scripts/demo_walkthrough.py` drives the same HTTP endpoints the browser uses. Start the API against the
seeded database on a port of your choice, then:

```powershell
python scripts/demo_walkthrough.py --api http://127.0.0.1:8000
```

It performs, in order:

1. guest reads the demo customers, stores and a filtered catalogue;
2. customer sign-in and account read (the address the delivery uses);
3. a delivery checkout from the warehouse, and a Click & Collect checkout at Sydney CBD;
4. a replay of each with the same `Idempotency-Key` — same resource, no second order;
5. a refused warehouse collection (`br06_collect_at_retail_store`);
6. staff fulfilment of the collection order, `paid → picking → ready → collected`, with the history;
7. a refused status change from another store's staff (`403 other_store`);
8. the customer's return request, replayed once;
9. staff receipt, then processing: restock and refund in one transaction;
10. the customer reading the refunded return and its amount;
11. the seeded empty store refusing a checkout with `409 out_of_stock`.

Last run against `jbhifi_demo` on 2026-09-26: **25/25 steps passed**.

## 4. The browser walkthrough

With the storefront, the admin and the API running against `jbhifi_demo`:

1. **Browse.** Home page → *Deals* shows current promotions with stock at *My store*; the header search
   goes to `/products?q=…`; the category links go to `/products?category=…`.
2. **Product.** Open a product from the catalogue: current price with the base price struck through when a
   promotion is running, specs, and stock per store with *My store* first.
3. **Cart.** Add an item, change its quantity, then open `/cart`. The cart stores only product ids and
   quantities — the prices shown are refreshed from the current-price view.
4. **Checkout — delivery.** Sign in as **Alice Morgan**, choose *Delivery* and one of her current addresses,
   and place the order. The order, its lines at the server's prices, the stock, the charge and the
   `placed → paid` history event all commit together.
5. **Checkout — Click & Collect.** Add another item, choose *Click & Collect* at a retail store, and place
   it. Retry it with the same attempt to show that a timeout does not create a second order.
6. **Order timeline.** `/orders` lists both orders newest first; open one for its lines, retained address,
   payment and the status timeline (`/orders/{id}`).
7. **Staff fulfilment.** In `/admin`, sign in as a store staff member for the order's store and progress
   it through the queue: delivery `picking → shipped → delivered`, collection `picking → ready →
   collected`. The queue only shows the signed-in staff member's store; support staff can read across
   stores but cannot move an order.
8. **Cancel.** On a paid order, use **Cancel**: the page shows the refund and the restock, then the order
   becomes `cancelled`. A delivered order offers no cancellation.
9. **Return.** On a delivered/collected order within 30 days, the customer's order page offers a return:
   quantities are limited to what is left, the reason is required, and the exact request is retried safely
   if the network drops.
10. **Returns desk.** `/admin/returns` shows the store's queue. *Receive* records who took it in and where,
    without restocking. *Process* restocks the returned quantities and records the refund from the
    purchase-time prices. *Reject* leaves the order and the money alone and is final.
11. **Back to the customer.** `/returns` shows the status and, once refunded, the amount; the order's
    timeline shows the refund and the status history, including the staff member who acted.

## 5. Refusals worth showing

| What to do | What the API answers |
|---|---|
| Check out `LG-43UT8050` at Sydney CBD (the seeded empty store) | `409 out_of_stock` with the store, product, requested and available quantities |
| Ask for a Click & Collect order at Eastern Creek DC | `409 br06_collect_at_retail_store` |
| Ask for more of a product than the store has | `409 out_of_stock` |
| Retry a checkout with the same key but a different basket | `409 idempotency_conflict` |
| Return an order completed 45 days ago | `409 br11_return_window` |
| Return more units than were bought | `409 br12_return_qty_within_purchased` |
| Reject a delivered order's cancellation | `409 br09_order_status_transition` |
| Adjust stock as staff from another store | `403 other_store` |
| Move an order with a stale `expected_status` | `409 stale_status` |

Every refusal has the same body — `{"error": {"code", "message", "detail"}}` — and the browser shows
`error.code`, which for a database rule is the constraint's own name.

## 6. What the seeder proves

Before it returns, the seeder re-runs the deferred financial checks (`SET CONSTRAINTS ALL IMMEDIATE`) and
reconciles:

- every touched `inventory` row against opening stock, plus the logged adjustments, minus the purchases,
  plus the cancellations and the processed returns;
- every order's charges against the lines it was sold, and its refunds against what was charged;
- every order line's returned quantity against what was bought (BR12).

A disagreement raises and the run fails; nothing is left half-seeded. The same assertions are run in
`tests/test_demo_seed.py`, which also proves that the expired order cannot be returned and that a repeated
seed is refused.

## 7. Resetting

The demo database is disposable. Rebuild it whenever the scenarios or `sql/` change:

```powershell
python scripts/seed_demo.py --database jbhifi_demo --create --seed 9120
```

To return to the shared development data, drop `POSTGRES_DB` from the environment (or restart the API
without it) so it uses `jbhifi` from `.env` again.

