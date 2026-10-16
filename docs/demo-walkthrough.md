# Demo walkthrough and video script

A checklist for clicking through the prototype in a browser, persona by persona, and a running order for the
≤ 3-minute showcase video. Each step says where to go, what to click, what you should see, and which requirement
(R#), business rule (BR#) or transaction (T#) it shows — the IDs in `.claude/plan.md`.

The orders, returns and stock named below come from the generated seed (`sql/20_seed_generated.sql`). Their
numbers are the same on every rebuild; their dates are relative to the day the database was built, so they are
given as "about N days ago". The steps change the data (a cancelled order stays cancelled), so start from a fresh
database before a run-through or a recording.

## Before you start

1. Start everything from fresh data: `.venv/bin/python scripts/demo.py --reset` (README → Run it). Wait for
   "Ready." and open **http://localhost:3000**.

   | In the seed | What it is |
   |---|---|
   | Order **#1141** (Alice) | delivered about 40 days ago (placed about 45 days ago): its 30-day return window closed about 10 days ago |
   | Order **#1436** (Alice) | Click & Collect at Sydney CBD, collected about 5 days ago: AirPods 4 and a JBL Flip 7 speaker; return **#79** (the speaker) is *requested*, the AirPods can still be returned |
   | Order **#1488** (Alice) | Click & Collect at Sydney CBD, *ready* to collect |
   | Order **#1500** (Alice) | Click & Collect at Sydney CBD, *paid* (a Galaxy S25, $1,199.00) — for the cancel step |
   | Return **#78** (Ryan Rossi) | AirPods 4, *received* at Sydney CBD by Aiden, waiting to be refunded or rejected |
   | PlayStation 5 Console (Slim, Disc) | exactly **1** at Sydney CBD ($799.95): the video's last console. Chatswood has 2, the warehouse 77 |
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
| 7 | **My orders** | — | Order **#1488** under "Ready to collect" | R5 |
| 8 | **My orders** → **#1500** (paid) | **Cancel order…** → "You'll be refunded $1,199.00" → **Yes, cancel it** | Status *cancelled*; Payment shows the $1,199.00 refund and a balance of $0.00; the timeline gains paid → cancelled | T4, BR14, BR21, R11 |
| 9 | **My orders** → **#1436** (collected) | In "Return items": the speaker has nothing left to return (return #79 asks for it); return the AirPods 4 with a reason → **Request return** | "Return #N requested…" | R6, BR11, BR12, BR10 |
| 10 | **Returns** | — | The new return and **#79**, both **Requested** | R6 |
| 11 | **My orders** → **#1141** (delivered about 40 days ago) | Look for "Return items" | "The 30-day return window closed on …" — no form | R6, BR11 |
| 12 | (for the report) the page only hides the form; the refusal itself is the database's | `pytest tests/test_business_rules.py -k br11` | `test_br11_returns_within_30_days_of_completion` passes: an insert past the window fails with `br11_return_window` | BR11 |
| 13 | **Account** | **Add address** → **Save address**; then **Retire…** an old one | The new address listed; the retired one kept for old orders but no longer offered at checkout | BR16, BR17 |

## Aiden — store staff, Sydney CBD (admin, `/admin`)

| # | Where | Do | You should see | Shows |
|---|---|---|---|---|
| 1 | **Orders** | Show "To do" | Sydney CBD's queue, oldest first: paid, picking and ready orders, Alice's **#1488** (ready) among them | R7 |
| 2 | Order **#1489** (paid) | **Start picking** → **Ready for collection** → **Mark collected** | "Order #1489 is now …"; the timeline names Aiden on each move | R7, R11, BR09 |
| 3 | Same order in two tabs | Click the same next step in both | The second tab gets a notice that the order moved on (`status_changed`) and reloads | R7 (one winner) |
| 4 | Order **#1483** (*ready*, not collected) | **Cancel order…** → **Yes, cancel it** | Cancelled, refunded, restocked. The transition table allows ready → cancelled (not collected in time); the customer could only cancel before picking | T4, BR09, BR21 |
| 5 | **Returns** → return **#79** (Alice's speaker) | **Receive at Sydney CBD** | Status **Received** | R8, BR22 |
| 6 | Same return | **Refund $199.95…** → **Restock and refund $199.95** | Status **Refunded**; Inventory shows the speaker back; Alice's order #1436 shows the refund | R8, T2, BR14 |
| 7 | Return **#78** (Ryan Rossi's AirPods, already received) | **Reject…**, give a reason → **Reject** | Status **Rejected**, with the reason (the customer sees it on their Returns page; Nora sees it in Support) | R8 |
| 8 | **Inventory** | **+1** / **−1**, or **Adjust…** with a reason → **Save adjustment** | The quantity changes; "Recent adjustments" lists who, why and by how much | R13, T3, BR18 |
| 9 | **Inventory**, the PlayStation 5 (1 left) | **Adjust…** → remove 2 → **Save adjustment** | "Rejected by the database" · `br03_inventory_qty_nonneg`; still 1 left | BR03 |
| 10 | **Reports** | — | "Store reports are for the store's manager and for support staff." | R9 (who may read) |

## Olivia — manager, Sydney CBD (admin)

| # | Where | Do | You should see | Shows |
|---|---|---|---|---|
| 1 | **Reports** | **30 days**, then **7 days** and **90 days** | Revenue, Orders, Units sold; Low stock (≤ 3 left or under 14 days of cover — the PlayStation 5 with 1 left is there); Sales by category; Return rate by category and by product (the Flip 7 and AirPods from #1436's return near the top) | R9, plan §6 #4 and #6 |
| 2 | Reports, the bottom panel | State **NSW**, then **NT** | Products in stock at all four NSW stores (39 of the 48); for NT, "no retail stores … all 48 active products qualify" (vacuous truth) | plan §6 #5 |
| 3 | **Promotions** | **New promotion** for a product that already has one in that period → **Create** | "Rejected by the database" · `br15_promotion_no_overlap` | BR15 |
| 4 | **Products** → a product | Change the price → **Save** | The new price on the storefront; past orders keep the price paid | R2, BR08 |

## Nora — support (admin)

| # | Where | Do | You should see | Shows |
|---|---|---|---|---|
| 1 | **Support** | Find a customer: type "alice" | Alice Morgan in the results | R10 |
| 2 | Alice | — | Profile and addresses; Orders (#1141, #1436, #1488, #1500, …); Returns (#79: the speaker, $199.95, its status and receiving store); History, newest first: each status change with who made it, payments, return events (a refund just before "refunded") | R10, R11 |
| 2a | Search "ryan rossi" | Open Ryan Rossi | Return #78 with Aiden's rejection reason (after Aiden step 7) | R10 |
| 3 | **Reports** | Pick another store, e.g. Bondi Junction | That store's report | R9 |
| 4 | **Orders**, **Returns**, **Inventory** | Pick any store | She can read every store's records; there are no buttons to move orders, handle returns or adjust stock | permissions (R14) |

## Video script — "the last console on launch day" (≤ 3 minutes)

The story: one database is the source of truth, and it decides even when two people act at the same moment.

**Set up before recording**

- The **PlayStation 5 Console (Slim, Disc)** has exactly **one** unit at Sydney CBD in the seed ($799.95); after a
  rehearsal, `demo.py --reset` brings it back (or Aiden's **Inventory → Adjust…**, a stocktake back to 1).
- Two customers in two browser windows side by side: Alice, and a second customer (in a private window,
  **Create account** with a `+clerk_test` address — code 424242).
- Aiden signed in in a third window, Olivia or Nora in a fourth.

| Time | Shot | Say / show |
|---|---|---|
| 0:00–0:15 | Title, then the architecture line from the README | "A retailer's catalogue, stock, orders and returns, with the rules enforced by PostgreSQL itself." |
| 0:15–0:40 | Alice searches "PlayStation 5"; "Where it is in stock" shows **1** at Sydney CBD | Per-store stock (R3) |
| 0:40–1:20 | Both customers at checkout, Click & Collect at Sydney CBD; **Place order** in both windows, one right after the other | One gets the order page (*paid*); the other gets **"Not enough stock"** — "Sydney CBD has 0 … Nothing was charged." The stock update locks the row, so the second checkout waits, re-checks and fails cleanly; `CHECK (quantity >= 0)` (BR03) is the backstop (T1). Mention that the race is also proven by an automated concurrency test. |
| 1:20–1:35 | The second customer switches to Click & Collect at **Chatswood** (2 left) and succeeds | The shopper recovers; nothing was half-saved |
| 1:35–2:00 | Aiden: **Orders** → the order → picking → ready → collected | The timeline records who and when (R7, R11, BR09) |
| 2:00–2:30 | Aiden receives Alice's return **#79** (the speaker) and refunds $199.95 | One transaction restocks and refunds (R6, R8, T2) |
| 2:30–2:45 | Aiden tries to remove more stock than exists | "Rejected by the database" · `br03_inventory_qty_nonneg` |
| 2:45–3:00 | Nora's **Support** history for the customer, or Olivia's **Reports** | Everything that happened, from one source of truth (R9, R10) |

If time is short, drop the 2:30 shot first, then the delivery recovery.
