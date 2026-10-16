"""The seed planner (scripts/generate_seed.py), without a database: a small reference shaped like the real one
(the same store ids, personas and scripted SKUs), planned at full size. What the plan promises before any SQL runs:
the same seed gives the same plan, everything happens before the anchor and in order, stock never goes below zero,
customers cancel only before picking, and a retired address is never used again (spec §5).
"""
from collections import defaultdict
from decimal import Decimal

import pytest

from scripts import generate_seed as gen

NSW_RETAIL, BONDI, PARRAMATTA, MELBOURNE, BRISBANE, WAREHOUSE = 1, 2, 3, 5, 9, 13
SKUS = {"APL-AP4": "189.00", "JBL-FLIP7-B": "149.95", "SONY-WH1000XM5-B": "549.00", "APL-MBA13-M4-256": "1799.00",
        "SAM-S25-256": "1399.00", "LEN-TABM11-128": "349.00", "JBL-T770NC-B": "179.95", "LG-OLED65C5": "3499.00"}


def a_reference() -> gen.Reference:
    stores = [gen.Store(NSW_RETAIL, "Sydney CBD", "retail", "NSW"), gen.Store(BONDI, "Bondi Junction", "retail", "NSW"),
              gen.Store(PARRAMATTA, "Parramatta", "retail", "NSW"), gen.Store(MELBOURNE, "Melbourne Central", "retail", "VIC"),
              gen.Store(BRISBANE, "Brisbane City", "retail", "QLD"), gen.Store(WAREHOUSE, "Eastern Creek DC", "warehouse", "NSW")]
    products = [gen.Product(i, sku, Decimal(price), True) for i, (sku, price) in enumerate(SKUS.items(), start=1)]
    products.append(gen.Product(99, "OLD-RETIRED", Decimal("99.00"), False))
    staff = {store.store_id: [store.store_id * 100 + n for n in range(3)] for store in stores}
    staff[NSW_RETAIL] = [1, 14, 15]                    # Olivia (manager), Aiden, Zara: the demo signs in as them
    stock = {(store.store_id, product.product_id): 3 for store in stores for product in products}
    personas = {"alice.morgan@example.com": gen.Persona("alice.morgan@example.com", 1),
                "ben.okafor@example.com": gen.Persona("ben.okafor@example.com", 2),
                "mei.zhou@example.com": gen.Persona("mei.zhou@example.com", 1),
                "tom.fraser@example.com": gen.Persona("tom.fraser@example.com", 1)}
    return gen.Reference(products, stores, staff, stock, personas)


@pytest.fixture(scope="module")
def reference():
    return a_reference()


@pytest.fixture(scope="module")
def events(reference):
    return gen.plan(reference)


def of(events, kind):
    return [event for event in events if isinstance(event, kind)]


def test_the_same_seed_gives_the_same_plan(reference, events):
    assert gen.plan(reference) == events
    assert gen.plan(reference, seed=gen.SEED + 1) != events


def test_the_plan_has_the_planned_size(events):
    assert len(of(events, gen.Checkout)) == gen.ORDERS
    assert len(of(events, gen.Customer)) == gen.CUSTOMERS
    assert [checkout.order_id for checkout in of(events, gen.Checkout)] == list(range(1, gen.ORDERS + 1))


def test_everything_happens_before_the_anchor_in_time_order(events):
    times = [event.t for event in events]
    assert times == sorted(times)
    assert max(times) < 0
    assert all(gen.at(t)[0] >= 1 and 0 <= gen.at(t)[1] < gen.DAY for t in times)
    assert gen.at(-180) == (1, 1260) and gen.at(-gen.DAY) == (1, 0)    # 21:00 and midnight, a day before the anchor


def test_orders_are_placed_between_8am_and_10pm_within_the_window(events):
    for checkout in of(events, gen.Checkout):
        days, minutes = gen.at(checkout.t)
        assert 1 <= days <= gen.WINDOW_DAYS and 8 * 60 <= minutes < 22 * 60


def test_each_customer_signs_up_before_their_first_order(events):
    first_order = {}
    for checkout in of(events, gen.Checkout):
        first_order.setdefault(checkout.email, checkout.t)
    for customer in of(events, gen.Customer):
        assert customer.t < first_order.get(customer.email, 0)


def test_each_orders_steps_follow_one_another(events):
    steps = defaultdict(list)
    for event in events:
        if isinstance(event, (gen.Checkout, gen.Move, gen.Cancel)):
            steps[event.order_id].append(event)
    for order_steps in steps.values():
        assert isinstance(order_steps[0], gen.Checkout)
        assert all(a.t < b.t for a, b in zip(order_steps, order_steps[1:]))
        assert all(not isinstance(step, gen.Checkout) for step in order_steps[1:])


def test_customers_cancel_before_picking_and_stores_cancel_uncollected_orders(events):
    moved = defaultdict(list)
    cancels = of(events, gen.Cancel)
    for event in events:
        if isinstance(event, gen.Move):
            moved[event.order_id].append(event)
    by_customer = [cancel for cancel in cancels if cancel.staff_id is None]
    by_store = [cancel for cancel in cancels if cancel.staff_id is not None]
    assert by_customer and by_store
    for cancel in by_customer:
        assert cancel.from_status == "paid" and moved[cancel.order_id] == []
    for cancel in by_store:
        assert cancel.from_status == "ready" and [move.status for move in moved[cancel.order_id]][-1] == "ready"
    assert 0.02 <= len(cancels) / gen.ORDERS <= 0.07


def test_moves_follow_each_methods_path_and_are_made_by_that_stores_staff(reference, events):
    paths = {"click_collect": ["picking", "ready", "collected"], "delivery": ["picking", "shipped", "delivered"]}
    checkouts = {checkout.order_id: checkout for checkout in of(events, gen.Checkout)}
    moved = defaultdict(list)
    for move in of(events, gen.Move):
        moved[move.order_id].append(move)
        assert move.staff_id in reference.staff_by_store[checkouts[move.order_id].store_id]
    for order_id, moves in moved.items():
        statuses = [move.status for move in moves]
        assert statuses == paths[checkouts[order_id].method][:len(statuses)]


def test_stock_never_goes_below_zero(reference, events):
    stock = dict(reference.stock)
    checkouts, requests, receipts = {}, {}, {}
    for event in events:
        if isinstance(event, gen.Receive):
            stock[(event.store_id, event.product_id)] += event.delta
            assert event.delta > 0 and event.staff_id in reference.staff_by_store[event.store_id]
        elif isinstance(event, gen.Checkout):
            checkouts[event.order_id] = event
            for line in event.lines:
                stock[(event.store_id, line.product_id)] -= line.quantity
                assert stock[(event.store_id, line.product_id)] >= 0, event
        elif isinstance(event, gen.Cancel) and event.from_status in ("paid", "ready"):
            order = checkouts[event.order_id]
            for line in order.lines:
                stock[(order.store_id, line.product_id)] += line.quantity
        elif isinstance(event, gen.ReturnRequested):
            requests[event.return_id] = event
        elif isinstance(event, gen.ReturnReceived):
            receipts[event.return_id] = event
        elif isinstance(event, gen.ReturnRefunded):                # T2 puts the units back where they came in
            request, store = requests[event.return_id], receipts[event.return_id].store_id
            for line_no, quantity in request.lines:
                stock[(store, checkouts[request.order_id].lines[line_no - 1].product_id)] += quantity
    assert of(events, gen.Receive)                     # 3 units each: deliveries were needed


def test_orders_are_well_formed(reference, events):
    active = {product.product_id for product in reference.products if product.is_active}
    stores = {store.store_id: store for store in reference.stores}
    for checkout in of(events, gen.Checkout):
        ids = [line.product_id for line in checkout.lines]
        assert ids == sorted(set(ids)) and set(ids) <= active          # numbered in product_id order, on sale
        assert 1 <= len(ids) <= 3 and all(line.quantity in (1, 2) for line in checkout.lines)
        if checkout.method == "click_collect":
            assert stores[checkout.store_id].store_type == "retail" and checkout.address_no is None
        else:
            assert checkout.address_no is not None
    assert len({checkout.key for checkout in of(events, gen.Checkout)}) == gen.ORDERS


def test_a_retired_address_is_never_used_again(events):
    retired = set()
    for event in events:
        if isinstance(event, gen.AddressRetired):
            retired.add((event.email, event.address_no))
        elif isinstance(event, gen.Checkout) and event.address_no is not None:
            assert (event.email, event.address_no) not in retired
    assert len(of(events, gen.AddressRetired)) >= gen.CUSTOMERS // 20             # about 10% move house


def test_the_scripted_scenarios_are_in_the_plan(events):
    def orders_of(email):
        return [checkout for checkout in of(events, gen.Checkout) if checkout.email == email]

    def last_status(order_id):
        steps = [e for e in events if isinstance(e, (gen.Move, gen.Cancel)) and e.order_id == order_id]
        return "paid" if not steps else ("cancelled" if isinstance(steps[-1], gen.Cancel) else steps[-1].status)

    alice = {(order.method, last_status(order.order_id), gen.at(order.t)[0]) for order in orders_of(gen.ALICE)}
    assert {("delivery", "delivered", 45), ("click_collect", "collected", 7), ("click_collect", "ready", 2),
            ("click_collect", "paid", 1)} <= alice
    assert "cancelled" in {last_status(order.order_id) for order in orders_of(gen.BEN)}
    assert "shipped" in {last_status(order.order_id) for order in orders_of(gen.MEI)}
    queue = [last_status(order.order_id) for order in of(events, gen.Checkout)
             if order.store_id == NSW_RETAIL and gen.at(order.t)[0] <= 2]
    assert queue.count("paid") >= 4 and queue.count("picking") >= 3


def test_staff_work_store_hours_and_customers_waking_hours(events):
    """Staff move orders and take deliveries 09:00–20:59; customers sign up, order and cancel 07:00–23:59. So no
    event falls in the night, where the hour that doesn't exist when daylight saving starts (02:00–03:00) is."""
    for event in events:
        minutes = gen.at(event.t)[1]
        staff = isinstance(event, (gen.Move, gen.Receive, gen.ReturnReceived, gen.ReturnRefunded, gen.ReturnRejected)) \
            or (isinstance(event, gen.Cancel) and event.staff_id)
        if staff:
            assert 9 * 60 <= minutes < 21 * 60, event
        elif not isinstance(event, (gen.AddressAdded, gen.AddressRetired)):    # address rows carry no time
            assert 7 * 60 <= minutes < 24 * 60, event


def test_the_generator_reads_and_writes_utf8_whatever_the_locale(tmp_path):
    """The helpers and the file contain → ≥ —: on a machine whose default encoding isn't UTF-8 (Windows' cp1252,
    or here an ASCII C locale), reading or writing them without saying UTF-8 breaks the file."""
    import os
    import subprocess
    import sys
    target = tmp_path / "seed.sql"
    script = ("from pathlib import Path; from scripts import generate_seed as g; text = g.render([]); "
              f"g.write(text, Path({str(target)!r})); assert Path({str(target)!r}).read_bytes().decode('utf-8') == text")
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C", "LANG": "C"}
    result = subprocess.run([sys.executable, "-c", script], cwd=gen.ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr



# ---------------------------------------------------------------- returns

def return_paths(events):
    """{return_id: [its events in order]}, starting with the request."""
    paths = defaultdict(list)
    for event in events:
        if isinstance(event, (gen.ReturnRequested, gen.ReturnReceived, gen.ReturnRefunded, gen.ReturnRejected)):
            paths[event.return_id].append(event)
    return paths


def test_returns_are_asked_for_within_30_days_of_completion(events):
    completed = {}
    for move in of(events, gen.Move):
        if move.status in ("collected", "delivered"):
            completed[move.order_id] = move.t
    requests = of(events, gen.ReturnRequested)
    for request in requests:
        assert request.order_id in completed and completed[request.order_id] < request.t
        assert request.t - completed[request.order_id] <= 30 * gen.DAY
        assert 8 * 60 <= gen.at(request.t)[1] < 22 * 60
    assert len({request.order_id for request in requests}) == len(requests)          # one return per order
    assert [request.return_id for request in requests] == list(range(1, len(requests) + 1))
    assert len({request.key for request in requests}) == len(requests)
    assert 0.03 <= len(requests) / len(completed) <= 0.10


def test_returns_go_requested_received_then_refunded_or_rejected_at_a_retail_store(reference, events):
    stores = {store.store_id: store for store in reference.stores}
    kinds = defaultdict(int)
    for path in return_paths(events).values():
        assert isinstance(path[0], gen.ReturnRequested) and all(a.t < b.t for a, b in zip(path, path[1:]))
        assert [type(e) for e in path[1:2]] in ([], [gen.ReturnReceived])
        if len(path) > 1:
            store = path[1].store_id
            assert stores[store].store_type == "retail"
            assert all(e.staff_id in reference.staff_by_store[store] for e in path[1:])
        assert len(path) <= 3 and (len(path) < 3 or isinstance(path[2], (gen.ReturnRefunded, gen.ReturnRejected)))
        kinds[type(path[-1]).__name__] += 1
        if isinstance(path[-1], gen.ReturnRejected):
            assert path[-1].reason
    assert set(kinds) == {"ReturnRequested", "ReturnReceived", "ReturnRefunded", "ReturnRejected"}
    assert kinds["ReturnRefunded"] > kinds["ReturnRejected"]


def test_returns_never_exceed_what_was_bought_and_some_are_partial(events):
    checkouts = {checkout.order_id: checkout for checkout in of(events, gen.Checkout)}
    partial = 0
    for request in of(events, gen.ReturnRequested):
        bought = {n: line.quantity for n, line in enumerate(checkouts[request.order_id].lines, start=1)}
        assert request.lines and all(1 <= quantity <= bought[n] for n, quantity in request.lines)
        partial += sum(quantity for _, quantity in request.lines) < sum(bought.values())
    assert partial >= 3


def test_the_scripted_returns_are_in_the_plan(events):
    checkouts = {checkout.order_id: checkout for checkout in of(events, gen.Checkout)}
    paths = return_paths(events)
    alice = [path for path in paths.values() if checkouts[path[0].order_id].email == gen.ALICE]
    assert any(len(path) == 1 and gen.at(path[0].t)[0] == 1 for path in alice)   # asked for yesterday, waiting
    waiting = [path for path in paths.values()
               if len(path) == 2 and path[1].store_id == NSW_RETAIL and gen.at(path[1].t)[0] == 3]
    assert waiting                                                                 # received at Sydney CBD 3 days ago
