# Demo walkthrough and video script

A checklist for clicking through the prototype in a browser, persona by persona, and a running order for the
≤ 3-minute showcase video. Each step says where to go, what to click, what you should see, and which requirement
(R#), business rule (BR#) or transaction (T#) it shows — the IDs in `.claude/plan.md`.

**Still to fill in once the seed is merged:** the places marked *[seed: …]* name orders and products from the
generated seed data; replace each with its real order number or product.

## Before you start

1. Start everything from fresh data: `.venv/bin/python scripts/demo.py --reset` (README → Run it). Wait for
   "Ready." and open **http://localhost:3000**.
2. You need the internet: sign-in is Clerk's hosted service.
3. The personas sign in as `<first>.<last>+clerk_test@example.com` with the password you set when you ran
   `DEMO_PASSWORD='…' scripts/clerk_personas.py`. If Clerk asks for an email code, it is **424242**.

   | Persona | Who | Signs in as |
   |---|---|---|
   | Alice Morgan | customer | `alice.morgan+clerk_test@example.com` |
   | Aiden Chen | store staff, Sydney CBD | `aiden.chen+clerk_test@example.com` |
   | Olivia Nguyen | manager, Sydney CBD | `olivia.nguyen+clerk_test@example.com` |
   | Nora Fitzgerald | support | `nora.fitzgerald+clerk_test@example.com` |

4. Use one browser profile (or private window) per persona, so two can be signed in side by side.
5. When the database refuses something, the page shows a box headed **"Rejected by the database"** with the
   rule's name in a code box (e.g. `br03_inventory_qty_nonneg`). That box is the evidence that the rule lives in
   the database.

## Alice — customer (storefront, `/`)

| # | Where | Do | You should see | Shows |
|---|---|---|---|---|
| 1 | Home | **Sign in** (top right) as Alice | "Hi, Alice"; her name in the header | R14, BR19 |
| 2 | Header | **My store** → Sydney CBD | Deals and stock now for Sydney CBD | R3 |
| 3 | **Shop all products** | Filter by a category and a price range, **Apply** | Only matching products; promotions at the sale price | R1, R2 |
| 4 | A product → **Details** | Look at "Where it is in stock" | Quantity per store, "your store" tagged, the warehouse badged | R3 |
| 5 | **Add to cart** → **Cart** → **Checkout** | **Click & Collect** at Sydney CBD → **Place order** | The order page: status *paid*; timeline placed → paid; Payment charged = total | R4, T1, BR08, BR20 |
| 6 | Checkout again | **Delivery** to one of her addresses, ship from the warehouse → **Place order** | A delivery order, paid | R4, BR06, BR17 |
| 7 | **My orders** → the order from step 5 | **Cancel order…** → **Yes, cancel it** | Status *cancelled*; Payment shows the refund and a balance of $0.00; the timeline gains → cancelled | T4, BR14, BR21, R11 |
| 8 | **My orders** → *[seed: Alice's collected order from the last 30 days]* | In "Return items", pick a quantity and a reason → **Request return** | "Return #N requested…" | R6, BR11, BR12, BR10 |
| 9 | **Returns** | — | The new return, badge **Requested** | R6 |
| 10 | **My orders** → *[seed: Alice's order completed more than 30 days ago]* | Look for "Return items" | "The 30-day return window closed on …" — no form | R6, BR11 |
| 11 | (optional) API docs, http://127.0.0.1:8000/docs | `POST /api/v1/orders/{order_id}/returns` for that old order | 409 `br11_return_window`: the database refuses even when the page is bypassed | BR11, R12 |
| 12 | **Account** | **Add address** → **Save address**; then **Retire…** an old one | The new address listed; the retired one kept for old orders but no longer offered at checkout | BR16, BR17 |

## Aiden — store staff, Sydney CBD (admin, `/admin`)

| # | Where | Do | You should see | Shows |
|---|---|---|---|---|
| 1 | **Orders** | Show "To do" | Sydney CBD's queue, oldest first, including Alice's Click & Collect order | R7 |
| 2 | That order | **Start picking** → **Ready for collection** → **Mark collected** | "Order #N is now …"; the timeline names Aiden on each move | R7, R11, BR09 |
| 3 | Same order in two tabs | Click the same next step in both | The second tab gets a notice that the order moved on (`status_changed`) and reloads | R7 (one winner) |
| 4 | A Click & Collect order at Sydney CBD that is *ready* but wasn't collected | **Cancel order…** → **Yes, cancel it** | Cancelled, refunded, restocked. The transition table allows ready → cancelled (not collected in time); the customer could only cancel before picking | T4, BR09, BR21 |
| 5 | **Returns** | Open Alice's requested return (Alice step 8) → **Receive at Sydney CBD** | Status **Received** | R8, BR22 |
| 6 | Same return | **Refund $X…** → **Restock and refund $X** | Status **Refunded**; Inventory shows the units back; Alice's order shows the refund | R8, T2, BR14 |
| 7 | Another requested return *[seed: a requested return at Sydney CBD]* | **Receive** → **Reject…**, give a reason → **Reject** | Status **Rejected**; Alice's Returns page shows the reason | R8 |
| 8 | **Inventory** | **+1** / **−1**, or **Adjust…** with a reason → **Save adjustment** | The quantity changes; "Recent adjustments" lists who, why and by how much | R13, T3, BR18 |
| 9 | **Inventory**, a product with 0–1 left | **Adjust…** → remove more than there is → **Save adjustment** | "Rejected by the database" · `br03_inventory_qty_nonneg` | BR03 |
| 10 | **Reports** | — | "Store reports are for the store's manager and for support staff." | R9 (who may read) |

## Olivia — manager, Sydney CBD (admin)

| # | Where | Do | You should see | Shows |
|---|---|---|---|---|
| 1 | **Reports** | **30 days**, then **7 days** and **90 days** | Revenue, Orders, Units sold; Low stock (≤ 3 left or under 14 days of cover); Sales by category; Return rate by category and by product | R9, plan §6 #4 and #6 |
| 2 | Reports, the bottom panel | State **NSW**, then **NT** | Products in stock at all four NSW stores; for NT, "no retail stores … all products qualify" (vacuous truth) | plan §6 #5 |
| 3 | **Promotions** | **New promotion** for a product that already has one in that period → **Create** | "Rejected by the database" · `br15_promotion_no_overlap` | BR15 |
| 4 | **Products** → a product | Change the price → **Save** | The new price on the storefront; past orders keep the price paid | R2, BR08 |

## Nora — support (admin)

| # | Where | Do | You should see | Shows |
|---|---|---|---|---|
| 1 | **Support** | Find a customer: type "alice" | Alice Morgan in the results | R10 |
| 2 | Alice | — | Profile and addresses; Orders; Returns (lines, value, refund, status, receiving store, rejection reason); History, newest first: each status change with who made it, payments, return events (refund just before "refunded") | R10, R11 |
| 3 | **Reports** | Pick another store, e.g. Bondi Junction | That store's report | R9 |
| 4 | **Orders**, **Returns**, **Inventory** | Pick any store | She can read every store's records; there are no buttons to move orders, handle returns or adjust stock | permissions (R14) |

## Video script — "the last console on launch day" (≤ 3 minutes)

The story: one database is the source of truth, and it decides even when two people act at the same moment.

**Set up before recording**

- A console with exactly **one** unit at Sydney CBD: *[seed: the launch console]* — or Aiden's **Inventory →
  Adjust…** (stocktake) down to 1.
- Two customers in two browser windows side by side: Alice, and a second customer (in a private window,
  **Create account** with a `+clerk_test` address — code 424242).
- Aiden signed in in a third window, Olivia or Nora in a fourth.

| Time | Shot | Say / show |
|---|---|---|
| 0:00–0:15 | Title, then the architecture line from the README | "A retailer's catalogue, stock, orders and returns, with the rules enforced by PostgreSQL itself." |
| 0:15–0:40 | Alice finds the console; "Where it is in stock" shows **1** at Sydney CBD | Per-store stock (R3) |
| 0:40–1:20 | Both customers at checkout, Click & Collect at Sydney CBD; **Place order** in both windows, one right after the other | One gets the order page (*paid*); the other gets **"Not enough stock"** — "Sydney CBD has 0 … Nothing was charged." The stock update locks the row, so the second checkout waits, re-checks and fails cleanly; `CHECK (quantity >= 0)` (BR03) is the backstop (T1). Mention that the race is also proven by an automated concurrency test. |
| 1:20–1:35 | The second customer switches to **Delivery** from the warehouse and succeeds | The shopper recovers; nothing was half-saved |
| 1:35–2:00 | Aiden: **Orders** → the order → picking → ready → collected | The timeline records who and when (R7, R11, BR09) |
| 2:00–2:30 | Alice requests a return; Aiden receives and refunds it | One transaction restocks and refunds (R6, R8, T2) |
| 2:30–2:45 | Aiden tries to remove more stock than exists | "Rejected by the database" · `br03_inventory_qty_nonneg` |
| 2:45–3:00 | Nora's **Support** history for the customer, or Olivia's **Reports** | Everything that happened, from one source of truth (R9, R10) |

If time is short, drop the 2:30 shot first, then the delivery recovery.
