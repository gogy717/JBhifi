"""Generate sql/20_seed_generated.sql: about 300 customers and 1,500 orders over the last 182 days (plan §7).

Python plans the timeline; SQL replays it through the real rules (docs/superpowers/specs/2026-10-16-seed-design.md).
plan() lays out every event — a customer signs up, an order is checked out, moved, cancelled, stock is received, an
address is retired — with a fixed random seed, in time order. render() writes each event as one call to a pg_temp
helper (scripts/seed_helpers.sql) that does what its service does, so every rule checks every seeded row.

Times are minutes relative to the anchor, Sydney midnight on the day the file is loaded: always negative, so the
whole timeline is in the past whatever time of day the file is loaded.

    python scripts/generate_seed.py

builds the <POSTGRES_TEST_DB>_seed database from the hand-written sql/ files, reads the reference data from it,
writes the file, and loads it into that database to prove it passes. Not at the same time as tests/test_seed.py,
which uses the same database.
"""
from __future__ import annotations

import os
import random
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

SEED = 9120
CUSTOMERS = 300                 # generated, on top of the reference seed's four personas
ORDERS = 1500                   # scripted scenarios included
WINDOW_DAYS = 182
DAY = 24 * 60                   # times are in minutes
HOUR = 60
KEY_NAMESPACE = uuid.UUID("3b0f6c1e-9120-4d6a-8f2e-5a7c1d9e4b20")   # uuid5 retry keys: a reproducible file

ALICE, BEN, MEI, TOM = ("alice.morgan@example.com", "ben.okafor@example.com", "mei.zhou@example.com",
                        "tom.fraser@example.com")
SYDNEY_CBD, PARRAMATTA, MELBOURNE_CENTRAL, BRISBANE_CITY, WAREHOUSE = 1, 3, 5, 9, 13
AIDEN, OLIVIA = 14, 1           # Sydney CBD's staff the demo signs in as

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
SEED_FILE = SQL_DIR / "20_seed_generated.sql"
HELPERS_FILE = ROOT / "scripts" / "seed_helpers.sql"

# ---------------------------------------------------------------- reference data (read from the database)


@dataclass(frozen=True)
class Product:
    product_id: int
    sku: str
    base_price: Decimal
    is_active: bool


@dataclass(frozen=True)
class Store:
    store_id: int
    name: str
    store_type: str             # retail or warehouse
    state: str


@dataclass(frozen=True)
class Persona:
    """A reference customer (10_seed_reference.sql), who already exists: only their current address is needed."""
    email: str
    address_no: int


@dataclass(frozen=True)
class Reference:
    products: list[Product]
    stores: list[Store]
    staff_by_store: dict[int, list[int]]        # store staff (managers included), by store
    stock: dict[tuple[int, int], int]           # (store_id, product_id) → opening quantity
    personas: dict[str, Persona]                # by email

# ---------------------------------------------------------------- events (t = minutes before the anchor, < 0)


@dataclass(frozen=True)
class Customer:
    t: int
    email: str
    full_name: str
    phone: str
    line1: str
    suburb: str
    state: str
    postcode: str


@dataclass(frozen=True)
class AddressAdded:
    t: int
    email: str
    address_no: int
    line1: str
    suburb: str
    state: str
    postcode: str


@dataclass(frozen=True)
class AddressRetired:
    t: int
    email: str
    address_no: int


@dataclass(frozen=True)
class Line:
    sku: str
    product_id: int
    quantity: int


@dataclass(frozen=True)
class Checkout:
    """T1: the order, its lines (in product_id order, as T1 numbers them), its charge and placed → paid."""
    t: int
    order_id: int
    email: str
    key: str
    method: str
    store_id: int
    address_no: int | None
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class Move:
    t: int
    order_id: int
    status: str
    staff_id: int


@dataclass(frozen=True)
class Cancel:
    """T4, by a staff member or (staff_id None) the customer; from_status says whether stock goes back."""
    t: int
    order_id: int
    staff_id: int | None
    from_status: str


@dataclass(frozen=True)
class Receive:
    """T3, reason received: a delivery that arrives before a sale that needs it."""
    t: int
    store_id: int
    sku: str
    product_id: int
    delta: int
    staff_id: int


@dataclass(frozen=True)
class ReturnRequested:
    """A customer asks to return part of a completed order: lines are (line_no, quantity)."""
    t: int
    return_id: int
    order_id: int
    key: str
    reason: str
    lines: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class ReturnReceived:
    t: int
    return_id: int
    store_id: int
    staff_id: int


@dataclass(frozen=True)
class ReturnRefunded:
    """T2: restock at the receiving store and refund what the return is worth."""
    t: int
    return_id: int
    staff_id: int


@dataclass(frozen=True)
class ReturnRejected:
    t: int
    return_id: int
    staff_id: int
    reason: str


def at(t: int) -> tuple[int, int]:
    """A time as (days before the anchor, minutes after that day's midnight): pg_temp.seed_at's arguments."""
    days = -(t // DAY)
    return days, t + days * DAY


def when(days: int, hour: int, minute: int = 0) -> int:
    """The time `days` days before the anchor at hour:minute (the inverse of at())."""
    return -days * DAY + hour * HOUR + minute

# ---------------------------------------------------------------- names and places (standard library only)


FIRST_NAMES = ["Olivia", "Jack", "Charlotte", "Noah", "Amelia", "William", "Isla", "Oliver", "Mia", "Thomas",
               "Ava", "James", "Grace", "Lucas", "Chloe", "Henry", "Zoe", "Ethan", "Ruby", "Leo", "Sophie", "Liam",
               "Harper", "Max", "Ella", "Samuel", "Matilda", "Daniel", "Emily", "Hugo", "Lily", "Ryan", "Sienna",
               "Arjun", "Priya", "Wei", "Mei", "Hiroshi", "Aisha", "Mohammed", "Fatima", "Luca", "Sofia", "Kai"]
LAST_NAMES = ["Smith", "Jones", "Williams", "Brown", "Wilson", "Taylor", "Nguyen", "Johnson", "Martin", "White",
              "Anderson", "Walker", "Thompson", "Harris", "Lee", "Ryan", "Robinson", "Kelly", "King", "Davis",
              "Wright", "Evans", "Roberts", "Green", "Hall", "Wood", "Jackson", "Clarke", "Patel", "Khan", "Chen",
              "Wang", "Li", "Kim", "Singh", "Tran", "Murphy", "O'Brien", "Rossi", "Papadopoulos", "Ali", "Hughes"]
RETURN_REASONS = ["Changed my mind", "Faulty", "Not as described", "Found it cheaper elsewhere",
                  "Doesn't work with my setup", "Arrived damaged"]
REJECTION_REASONS = ["Opened and used", "Damaged after purchase", "Missing accessories and packaging"]
STREETS = ["George St", "King St", "Church St", "High St", "Victoria Rd", "Station St", "Park Rd", "Elizabeth St",
           "Queen St", "Bridge Rd", "Main St", "Ocean Pde", "Railway Pde", "Hill St", "Smith St", "Grove Ave"]
SUBURBS = {
    "NSW": [("Pyrmont", "2009"), ("Surry Hills", "2010"), ("Newtown", "2042"), ("Bondi", "2026"),
            ("Parramatta", "2150"), ("Chatswood", "2067"), ("Marrickville", "2204"), ("Ryde", "2112"),
            ("Penrith", "2750"), ("Manly", "2095")],
    "VIC": [("Fitzroy", "3065"), ("Richmond", "3121"), ("St Kilda", "3182"), ("Brunswick", "3056"),
            ("Footscray", "3011"), ("Box Hill", "3128"), ("Doncaster", "3108"), ("Malvern", "3144")],
    "QLD": [("South Brisbane", "4101"), ("New Farm", "4005"), ("Chermside", "4032"), ("Carindale", "4152"),
            ("Paddington", "4064"), ("Toowong", "4066"), ("Robina", "4226"), ("Indooroopilly", "4068")],
}

# ---------------------------------------------------------------- the plan


@dataclass
class _Shopper:
    email: str
    home: Store
    weight: float = 1.0                         # how often they shop, relative to others
    address_no: int = 1
    customer: Customer | None = None            # None for a persona (already in the reference data)


@dataclass
class _Order:
    """An order before ids are given: when it is placed, what it is, and its later steps (in time order)."""
    t: int
    email: str
    method: str
    store_id: int
    lines: tuple[Line, ...]
    steps: list = field(default_factory=list)  # [(t, "move", status, staff_id) | (t, "cancel", staff_id, from)]
    address_no: int | None = None
    scripted: bool = False                      # a demo scenario: no random return is added to it
    ret: _Return | None = None


@dataclass
class _Return:
    """A return before ids are given: when it is asked for, which lines, and its later steps."""
    t: int
    reason: str
    lines: tuple[tuple[int, int], ...]          # (line_no, quantity)
    steps: list = field(default_factory=list)  # [(t, "received", store_id, staff_id) | (t, "refunded", staff_id)
                                                #  | (t, "rejected", staff_id, reason)]


def plan(reference: Reference, seed: int = SEED) -> list:
    """Every event of the seed, in time order (ties keep the order they were planned in)."""
    rng = random.Random(seed)
    planner = _Planner(reference, rng)
    return planner.run(seed)


class _Planner:
    def __init__(self, reference: Reference, rng: random.Random):
        self.ref, self.rng = reference, rng
        self.stores = {store.store_id: store for store in reference.stores}
        self.retail = [store for store in reference.stores if store.store_type == "retail"]
        self.warehouse = next(store for store in reference.stores if store.store_type == "warehouse")
        self.on_sale = [product for product in reference.products if product.is_active]
        self.by_sku = {product.sku: product for product in self.on_sale}
        # Cheaper products sell more often.
        self.weights = [1 / max(float(product.base_price), 1.0) ** 0.6 for product in self.on_sale]

    def run(self, seed: int) -> list:
        shoppers = self.shoppers()
        orders = self.scripted(shoppers)
        generated = [shopper for shopper in shoppers if shopper.customer is not None]
        for _ in range(ORDERS - len(orders)):
            shopper = self.rng.choices(generated, weights=[s.weight for s in generated])[0]
            orders.append(self.random_order(shopper))
        address_events = self.addresses(shoppers, orders)
        self.sign_up(generated, orders)
        self.returns(shoppers, orders)
        return self.timeline(seed, shoppers, orders, address_events)

    # -------------------------------------------------- customers

    def shoppers(self) -> list[_Shopper]:
        homes = {ALICE: SYDNEY_CBD, BEN: MELBOURNE_CENTRAL, MEI: BRISBANE_CITY, TOM: PARRAMATTA}
        shoppers = [_Shopper(persona.email, self.stores[homes[persona.email]], address_no=persona.address_no)
                    for persona in self.ref.personas.values() if persona.email in homes]
        for n in range(1, CUSTOMERS + 1):
            first, last = self.rng.choice(FIRST_NAMES), self.rng.choice(LAST_NAMES)
            email = f"{first}.{last}.{n}@example.com".lower().replace("'", "")
            home = self.rng.choice(self.retail)
            suburb, postcode = self.rng.choice(SUBURBS[home.state])
            phone = f"04{self.rng.randint(10, 99)} {self.rng.randint(100, 999)} {self.rng.randint(100, 999)}"
            customer = Customer(0, email, f"{first} {last}", phone,
                                f"{self.rng.randint(1, 220)} {self.rng.choice(STREETS)}", suburb, home.state, postcode)
            weight = min(self.rng.paretovariate(1.4), 15.0)         # a few shop often, most a few times
            shoppers.append(_Shopper(email, home, weight, customer=customer))
        return shoppers

    def sign_up(self, generated: list[_Shopper], orders: list[_Order]) -> None:
        """Each generated customer signs up 1–60 days before their first order (or some day in the window), between
        07:00 and 22:59."""
        first = {}
        for order in orders:
            first[order.email] = min(order.t, first.get(order.email, 0))
        for shopper in generated:
            days = at(first[shopper.email])[0] if shopper.email in first else self.rng.randint(1, WINDOW_DAYS)
            t = when(days + self.rng.randint(1, 60), self.rng.randint(7, 22), self.rng.randint(0, 59))
            shopper.customer = Customer(t, *[getattr(shopper.customer, f) for f in
                                             ("email", "full_name", "phone", "line1", "suburb", "state", "postcode")])

    def addresses(self, shoppers: list[_Shopper], orders: list[_Order]) -> list:
        """Give every delivery its address. About 10% of generated customers with two or more orders move house
        between two of them: address 2 is added and address 1 retired then, and later deliveries go to address 2."""
        events = []
        by_email = defaultdict(list)
        for order in orders:
            by_email[order.email].append(order)
        for shopper in shoppers:
            mine = sorted(by_email[shopper.email], key=lambda order: order.t)
            moved_at = None
            if shopper.customer is not None and len(mine) >= 2 and self.rng.random() < 0.2:
                k = self.rng.randint(1, len(mine) - 1)
                before, after = mine[k - 1].t, mine[k].t
                if after - before >= 2:
                    moved_at = (before + after) // 2
                    suburb, postcode = self.rng.choice(SUBURBS[shopper.home.state])
                    line1 = f"{self.rng.randint(1, 220)} {self.rng.choice(STREETS)}"
                    events.append(AddressAdded(moved_at, shopper.email, 2, line1, suburb, shopper.home.state, postcode))
                    events.append(AddressRetired(moved_at, shopper.email, 1))
            for order in mine:
                if order.method == "delivery":
                    order.address_no = 2 if moved_at is not None and order.t > moved_at else shopper.address_no
        return events

    # -------------------------------------------------- orders

    def basket(self) -> tuple[Line, ...]:
        size = self.rng.choices([1, 2, 3], weights=[70, 25, 5])[0]
        chosen: dict[int, Product] = {}
        while len(chosen) < size:
            product = self.rng.choices(self.on_sale, weights=self.weights)[0]
            chosen[product.product_id] = product
        return tuple(Line(p.sku, p.product_id, 2 if p.base_price < 200 and self.rng.random() < 0.2 else 1)
                     for _, p in sorted(chosen.items()))

    def lines_of(self, *skus: str) -> tuple[Line, ...]:
        products = sorted((self.by_sku[sku] for sku in skus), key=lambda product: product.product_id)
        return tuple(Line(product.sku, product.product_id, 1) for product in products)

    def staff(self, store_id: int) -> int:
        return self.rng.choice(self.ref.staff_by_store[store_id])

    def open_hours(self, t: int) -> int:
        """t, or if a store isn't staffed then (09:00–20:59), a little after it next opens: staff don't work
        through the night. It only ever moves a step later, so an order's steps stay in order."""
        minutes = t % DAY                                    # the anchor is a midnight, so this is the clock time
        if minutes < 9 * HOUR:
            return t - minutes + 9 * HOUR + self.rng.randint(0, 90)
        if minutes >= 21 * HOUR:
            return t - minutes + DAY + 9 * HOUR + self.rng.randint(0, 90)
        return t

    def waking_hours(self, t: int) -> int:
        """t, or if it is outside 08:00–21:59 (when customers shop), a little after 08:00 the next morning."""
        minutes = t % DAY
        if minutes < 8 * HOUR:
            return t - minutes + 8 * HOUR + self.rng.randint(0, 120)
        if minutes >= 22 * HOUR:
            return t - minutes + DAY + 8 * HOUR + self.rng.randint(0, 120)
        return t

    # -------------------------------------------------- returns

    def returns(self, shoppers: list[_Shopper], orders: list[_Order]) -> None:
        """About 5% of completed orders (15% of Sydney CBD's, so its return rates have data) get a return, asked for
        1 hour to 25 days after completion (BR11 allows 30), received 1–5 days later, then refunded or rejected."""
        homes = {shopper.email: shopper.home for shopper in shoppers}
        for order in orders:
            if order.scripted or not order.steps or order.steps[-1][1] != "move" \
                    or order.steps[-1][2] not in ("collected", "delivered"):
                continue
            if self.rng.random() >= (0.15 if order.store_id == SYDNEY_CBD else 0.05):
                continue
            asked = self.waking_hours(order.steps[-1][0] + self.rng.randint(HOUR, 25 * DAY))
            if asked >= 0:
                continue
            # A delivery comes back to the customer's own store; Click & Collect to the store it was collected from.
            store = order.store_id if order.method == "click_collect" else homes[order.email].store_id
            order.ret = self.a_return(asked, self.returned_lines(order), store)

    def returned_lines(self, order: _Order) -> tuple[tuple[int, int], ...]:
        """Every line in full, or (about 40%) part of the order: fewer lines, or fewer units of one."""
        lines = [(line_no, line.quantity) for line_no, line in enumerate(order.lines, start=1)]
        if self.rng.random() < 0.4:
            if len(lines) > 1:
                return tuple(sorted(self.rng.sample(lines, self.rng.randint(1, len(lines) - 1))))
            if lines[0][1] > 1:
                return ((lines[0][0], lines[0][1] - 1),)
        return tuple(lines)

    def a_return(self, asked: int, lines: tuple[tuple[int, int], ...], store_id: int, *,
                 outcome: str | None = None) -> _Return:
        """The return's steps from `asked`, each in store hours; any that would come after the anchor waits."""
        ret = _Return(asked, self.rng.choice(RETURN_REASONS), lines)
        received = self.open_hours(asked + self.rng.randint(DAY, 5 * DAY))
        resolved = self.open_hours(received + self.rng.randint(HOUR, 3 * DAY))
        outcome = outcome or ("rejected" if self.rng.random() < 0.15 else "refunded")
        steps = [(received, "received", store_id, self.staff(store_id))]
        if outcome == "rejected":
            steps.append((resolved, "rejected", self.staff(store_id), self.rng.choice(REJECTION_REASONS)))
        else:
            steps.append((resolved, "refunded", self.staff(store_id)))
        for step in steps:
            if step[0] >= 0:
                break
            ret.steps.append(step)
        return ret

    def random_order(self, shopper: _Shopper) -> _Order:
        t = when(self.rng.randint(1, WINDOW_DAYS), self.rng.randint(8, 21), self.rng.randint(0, 59))
        if self.rng.random() < 0.55:
            order = _Order(t, shopper.email, "click_collect", shopper.home.store_id, self.basket())
        else:
            store = self.warehouse if self.rng.random() < 0.7 else shopper.home
            order = _Order(t, shopper.email, "delivery", store.store_id, self.basket())
        self.schedule(order)
        return order

    def schedule(self, order: _Order) -> None:
        """The order's later steps, at realistic delays, each made while the store is staffed. A step that would come
        after the anchor hasn't happened yet, and neither has anything after it."""
        rng, store, open_ = self.rng, order.store_id, self.open_hours
        steps = []
        if rng.random() < 0.03:                     # the customer changes their mind, before picking (by 23:30)
            steps.append((order.t + rng.randint(5, 90), "cancel", None, "paid"))
        elif order.method == "click_collect":
            picking = open_(order.t + rng.randint(30, 4 * HOUR))
            ready = open_(picking + rng.randint(HOUR, DAY))
            steps += [(picking, "move", "picking", self.staff(store)), (ready, "move", "ready", self.staff(store))]
            if rng.random() < 0.02:                             # never collected: the store cancels a week later
                steps.append((open_(ready + 7 * DAY + rng.randint(HOUR, 8 * HOUR)), "cancel", self.staff(store),
                              "ready"))
            else:
                steps.append((open_(ready + rng.randint(10, 5 * DAY)), "move", "collected", self.staff(store)))
        else:
            picking = open_(order.t + rng.randint(HOUR, 12 * HOUR))
            shipped = open_(picking + rng.randint(12 * HOUR, 2 * DAY))
            delivered = open_(shipped + rng.randint(DAY, 5 * DAY))
            steps += [(picking, "move", "picking", self.staff(store)), (shipped, "move", "shipped", self.staff(store)),
                      (delivered, "move", "delivered", self.staff(store))]
        for step in steps:
            if step[0] >= 0:
                break
            order.steps.append(step)

    def scripted(self, shoppers: list[_Shopper]) -> list[_Order]:
        """The demo's orders (spec §3): fixed times, through the same rules and stock as every other order."""
        def order(email, method, store, lines, t, *steps):
            return _Order(t, email, method, store, lines, list(steps), scripted=True)

        def move(t, status, staff):
            return (t, "move", status, staff)

        cbd = [s for s in shoppers if s.customer is not None and s.home.store_id == SYDNEY_CBD] or \
              [s for s in shoppers if s.customer is not None]
        orders = [
            # Alice: a return BR11 refuses (delivered 40 days ago), one to demo (collected 5 days ago), an order
            # ready to collect since yesterday, and one paid last night that she can cancel.
            order(ALICE, "delivery", WAREHOUSE, self.lines_of("SONY-WH1000XM5-B"), when(45, 10),
                  move(when(45, 13), "picking", self.staff(WAREHOUSE)),
                  move(when(44, 9), "shipped", self.staff(WAREHOUSE)),
                  move(when(40, 14), "delivered", self.staff(WAREHOUSE))),
            order(ALICE, "click_collect", SYDNEY_CBD, self.lines_of("APL-AP4", "JBL-FLIP7-B"), when(7, 12, 30),
                  move(when(7, 13, 30), "picking", AIDEN), move(when(7, 16), "ready", AIDEN),
                  move(when(5, 11), "collected", OLIVIA)),
            order(ALICE, "click_collect", SYDNEY_CBD, self.lines_of("JBL-T770NC-B"), when(2, 19),
                  move(when(1, 9, 30), "picking", AIDEN), move(when(1, 11), "ready", AIDEN)),
            order(ALICE, "click_collect", SYDNEY_CBD, self.lines_of("SAM-S25-256"), when(1, 21)),
            # Ben: an order he cancelled, and one delivered. Mei: a delivery on its way. Tom: two completed.
            order(BEN, "click_collect", MELBOURNE_CENTRAL, self.lines_of("APL-AP4"), when(20, 11),
                  (when(20, 13), "cancel", None, "paid")),
            order(BEN, "delivery", WAREHOUSE, self.lines_of("LEN-TABM11-128"), when(14, 10),
                  move(when(14, 15), "picking", self.staff(WAREHOUSE)),
                  move(when(13, 10), "shipped", self.staff(WAREHOUSE)),
                  move(when(10, 12), "delivered", self.staff(WAREHOUSE))),
            order(MEI, "delivery", WAREHOUSE, self.lines_of("APL-MBA13-M4-256"), when(3, 9),
                  move(when(3, 14), "picking", self.staff(WAREHOUSE)),
                  move(when(2, 10), "shipped", self.staff(WAREHOUSE))),
            order(TOM, "click_collect", PARRAMATTA, self.lines_of("JBL-FLIP7-B"), when(60, 10),
                  move(when(60, 11), "picking", self.staff(PARRAMATTA)),
                  move(when(60, 15), "ready", self.staff(PARRAMATTA)),
                  move(when(59, 12), "collected", self.staff(PARRAMATTA))),
            order(TOM, "delivery", PARRAMATTA, self.lines_of("APL-AP4"), when(15, 18),
                  move(when(15, 20), "picking", self.staff(PARRAMATTA)),
                  move(when(14, 11), "shipped", self.staff(PARRAMATTA)),
                  move(when(12, 16), "delivered", self.staff(PARRAMATTA))),
        ]
        # Alice asks to return the speaker from the order she collected 5 days ago: waiting for Sydney CBD to take it.
        collected = next(o for o in orders if o.email == ALICE and o.steps[-1:] and o.steps[-1][2] == "collected")
        speaker = next(n for n, line in enumerate(collected.lines, start=1) if line.sku == "JBL-FLIP7-B")
        collected.ret = _Return(when(1, 10), "Changed my mind", ((speaker, 1),))
        # A return Sydney CBD took in 3 days ago (Aiden), waiting to be refunded or rejected.
        received = order(cbd[7 % len(cbd)].email, "click_collect", SYDNEY_CBD, self.lines_of("APL-AP4"), when(12, 11),
                         move(when(12, 12), "picking", AIDEN), move(when(12, 15), "ready", AIDEN),
                         move(when(10, 14), "collected", OLIVIA))
        received.ret = _Return(when(4, 10), "Faulty", ((1, 1),), [(when(3, 11), "received", SYDNEY_CBD, AIDEN)])
        orders.append(received)
        # Sydney CBD's queue for Aiden and Olivia: four paid and three being picked, from the last two days.
        for n, t in enumerate([when(1, 18), when(1, 19, 15), when(1, 20, 30), when(2, 20)]):
            orders.append(order(cbd[n % len(cbd)].email, "click_collect", SYDNEY_CBD, self.basket(), t))
        for n, (t, picking) in enumerate([(when(2, 10), when(1, 9)), (when(2, 13), when(1, 10)),
                                          (when(2, 16), when(1, 11, 30))]):
            orders.append(order(cbd[(n + 4) % len(cbd)].email, "click_collect", SYDNEY_CBD, self.basket(), t,
                                move(picking, "picking", (AIDEN, OLIVIA)[n % 2])))
        return [o for o in orders if o.email in self.ref.personas or o.email in {s.email for s in shoppers}]

    # -------------------------------------------------- the timeline

    def timeline(self, seed: int, shoppers: list[_Shopper], orders: list[_Order], address_events: list) -> list:
        """Order ids in placing order; every event in time order; then the stock walk, which adds a delivery 1–2
        days before any sale the shelf can't cover."""
        orders.sort(key=lambda order: order.t)                # stable: ties keep the order they were planned in
        events = [shopper.customer for shopper in shoppers if shopper.customer is not None] + address_events
        for order_id, order in enumerate(orders, start=1):
            key = str(uuid.uuid5(KEY_NAMESPACE, f"{seed}:{order_id}"))
            events.append(Checkout(order.t, order_id, order.email, key, order.method, order.store_id,
                                   order.address_no, order.lines))
            for step in order.steps:
                if step[1] == "move":
                    events.append(Move(step[0], order_id, step[2], step[3]))
                else:
                    events.append(Cancel(step[0], order_id, step[2], step[3]))
        returns = sorted(((order.ret, order_id) for order_id, order in enumerate(orders, start=1) if order.ret),
                         key=lambda pair: pair[0].t)
        for return_id, (ret, order_id) in enumerate(returns, start=1):
            key = str(uuid.uuid5(KEY_NAMESPACE, f"{seed}:return:{return_id}"))
            events.append(ReturnRequested(ret.t, return_id, order_id, key, ret.reason, ret.lines))
            for step in ret.steps:
                if step[1] == "received":
                    events.append(ReturnReceived(step[0], return_id, step[2], step[3]))
                elif step[1] == "refunded":
                    events.append(ReturnRefunded(step[0], return_id, step[2]))
                else:
                    events.append(ReturnRejected(step[0], return_id, step[2], step[3]))
        events = self.stocked(_sorted(events))
        return _sorted(events)

    def stocked(self, events: list) -> list:
        stock = dict(self.ref.stock)
        checkouts, requests, receipts, out = {}, {}, {}, []
        for event in events:
            if isinstance(event, Checkout):
                checkouts[event.order_id] = event
                for line in event.lines:
                    have = stock[(event.store_id, line.product_id)]
                    if have < line.quantity:
                        retail = self.stores[event.store_id].store_type == "retail"
                        delta = max(self.rng.randint(6, 12) if retail else self.rng.randint(30, 60),
                                    line.quantity - have)
                        arrives = when(at(event.t)[0] + self.rng.randint(1, 2), self.rng.randint(9, 16),
                                       self.rng.randint(0, 59))         # a day or two before, in store hours
                        out.append(Receive(arrives, event.store_id, line.sku, line.product_id, delta,
                                           self.staff(event.store_id)))
                        stock[(event.store_id, line.product_id)] += delta
                    stock[(event.store_id, line.product_id)] -= line.quantity
            elif isinstance(event, Cancel) and event.from_status in ("paid", "ready"):
                order = checkouts[event.order_id]
                for line in order.lines:
                    stock[(order.store_id, line.product_id)] += line.quantity
            elif isinstance(event, ReturnRequested):
                requests[event.return_id] = event
            elif isinstance(event, ReturnReceived):
                receipts[event.return_id] = event.store_id
            elif isinstance(event, ReturnRefunded):                 # T2 restocks the receiving store
                request = requests[event.return_id]
                for line_no, quantity in request.lines:
                    product = checkouts[request.order_id].lines[line_no - 1].product_id
                    stock[(receipts[event.return_id], product)] += quantity
            out.append(event)
        return out


def _sorted(events: list) -> list:
    """In time order; events at the same minute keep their relative order (Python's sort is stable)."""
    return sorted(events, key=lambda event: event.t)


# ---------------------------------------------------------------- the SQL file


def render(events: list) -> str:
    """The seed file: the helpers, then one helper call per event, in time order, in one transaction."""
    kinds = Counter(type(event).__name__ for event in events)
    cancelled = kinds["Cancel"]
    out = [
        "-- GENERATED by scripts/generate_seed.py — do not edit. To change it, change the generator and run",
        "--     python scripts/generate_seed.py",
        f"-- Seed {SEED}: {kinds['Customer']} customers, {kinds['Checkout']} orders ({cancelled} cancelled), "
        f"{kinds['Receive']} stock deliveries, {kinds['AddressRetired']} address changes, "
        f"{kinds['ReturnRequested']} returns, over {WINDOW_DAYS} days.",
        "-- Every time is relative to the anchor: Sydney midnight on the day this file is loaded "
        "(docs/superpowers/specs/2026-10-16-seed-design.md).",
        "BEGIN;",
        "SET LOCAL timezone = 'Australia/Sydney';",
        "",
        HELPERS_FILE.read_text(encoding="utf-8").rstrip(),
        "",
        "-- ---------------------------------------------------------------- the timeline",
    ]
    for event in events:
        out.extend(_calls(event))
    out += [
        "",
        "-- Order and return ids were given explicitly: move the identities past them, so the API's next ones don't collide.",
        "SELECT setval(pg_get_serial_sequence('customer_order', 'order_id'), (SELECT max(order_id) FROM customer_order));",
        "SELECT setval(pg_get_serial_sequence('return_request', 'return_id'), "
        "(SELECT COALESCE(max(return_id), 1) FROM return_request), (SELECT count(*) > 0 FROM return_request));",
        "COMMIT;",
        "",
    ]
    return "\n".join(out)


def _calls(event) -> list[str]:
    def call(name, *args):
        return f"SELECT pg_temp.{name}({', '.join(_literal(arg) for arg in args)});"

    time = _At(*at(event.t))
    if isinstance(event, Customer):
        return [call("seed_customer", event.email, event.full_name, event.phone, time, event.line1, event.suburb,
                     event.state, event.postcode)]
    if isinstance(event, AddressAdded):
        return [call("seed_address", event.email, event.address_no, event.line1, event.suburb, event.state,
                     event.postcode)]
    if isinstance(event, AddressRetired):
        return [call("seed_retire_address", event.email, event.address_no)]
    if isinstance(event, Checkout):
        return ([call("seed_order", event.order_id, event.email, event.key, event.method, event.store_id,
                      event.address_no, time)]
                + [call("seed_line", event.order_id, line_no, line.sku, line.quantity)
                   for line_no, line in enumerate(event.lines, start=1)]
                + [call("seed_pay", event.order_id)])
    if isinstance(event, Move):
        return [call("seed_move", event.order_id, event.status, time, event.staff_id)]
    if isinstance(event, Cancel):
        return [call("seed_cancel", event.order_id, time, event.staff_id)]
    if isinstance(event, Receive):
        return [call("seed_receive", event.store_id, event.sku, event.delta, event.staff_id, time)]
    if isinstance(event, ReturnRequested):
        return ([call("seed_request_return", event.return_id, event.order_id, event.key, event.reason, time)]
                + [call("seed_return_line", event.return_id, line_no, quantity) for line_no, quantity in event.lines])
    if isinstance(event, ReturnReceived):
        return [call("seed_receive_return", event.return_id, event.store_id, event.staff_id, time)]
    if isinstance(event, ReturnRefunded):
        return [call("seed_refund_return", event.return_id, event.staff_id, time)]
    if isinstance(event, ReturnRejected):
        return [call("seed_reject_return", event.return_id, event.staff_id, time, event.reason)]
    raise TypeError(event)


@dataclass(frozen=True)
class _At:
    days: int
    minutes: int


def _literal(value) -> str:
    """A SQL literal for a value the generator made itself (strings are quoted, quotes doubled)."""
    if value is None:
        return "NULL"
    if isinstance(value, _At):
        return f"pg_temp.seed_at({value.days}, {value.minutes})"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"

# ---------------------------------------------------------------- the database


def seed_database() -> str:
    """The generator's (and tests/test_seed.py's) own database: the test database's name plus _seed."""
    return os.environ.get("POSTGRES_TEST_DB", "jbhifi_test") + "_seed"


def connect(dbname: str):
    return psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"], dbname=dbname,
                            user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
                            cursor_factory=RealDictCursor)


def build_reference_database(dbname: str) -> None:
    """Drop and recreate dbname, then run the hand-written sql/ files (numbered below 20) in order, as Docker does."""
    admin = connect("postgres")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    admin.close()
    conn = connect(dbname)
    conn.autocommit = True
    with conn.cursor() as cur:
        for path in sorted(SQL_DIR.glob("*.sql")):
            if path.name < "20":
                cur.execute(path.read_text(encoding="utf-8"))
    conn.close()


def read_reference(cur) -> Reference:
    cur.execute("SELECT product_id, sku, base_price, is_active FROM product ORDER BY product_id")
    products = [Product(**row) for row in cur.fetchall()]
    cur.execute("SELECT store_id, name, store_type, state FROM store ORDER BY store_id")
    stores = [Store(**row) for row in cur.fetchall()]
    cur.execute("SELECT store_id, staff_id FROM staff WHERE staff_type = 'store' ORDER BY store_id, staff_id")
    staff = defaultdict(list)
    for row in cur.fetchall():
        staff[row["store_id"]].append(row["staff_id"])
    cur.execute("SELECT store_id, product_id, quantity FROM inventory")
    stock = {(row["store_id"], row["product_id"]): row["quantity"] for row in cur.fetchall()}
    cur.execute("""SELECT c.email, min(a.address_no) AS address_no
                   FROM customer c JOIN customer_address a ON a.customer_id = c.customer_id AND a.is_active
                   GROUP BY c.email""")
    personas = {row["email"]: Persona(row["email"], row["address_no"]) for row in cur.fetchall()}
    return Reference(products, stores, dict(staff), stock, personas)


def write(text: str, path: Path = SEED_FILE) -> None:
    """UTF-8 with LF line ends on every platform: the file is compared byte for byte (tests/test_seed.py), and a
    Windows default (cp1252, CRLF) would change it."""
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    load_dotenv(ROOT / ".env")
    dbname = seed_database()
    print(f"building {dbname} from sql/ (files below 20) …")
    build_reference_database(dbname)
    conn = connect(dbname)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            events = plan(read_reference(cur))
            text = render(events)
            print(f"loading the generated seed into {dbname} …")
            cur.execute(text)                       # every rule runs: a failure stops here, before writing
    finally:
        conn.close()
    write(text)
    print(f"wrote {SEED_FILE.relative_to(ROOT)}: {text.splitlines()[2][3:]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
