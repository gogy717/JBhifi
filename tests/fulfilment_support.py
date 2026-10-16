"""Committed orders for the fulfilment and cancellation tests, placed by a real checkout (T1), so stock really
was taken and cancelling can be seen giving it back. Each call makes its own product and customer, so nothing
depends on what other tests committed.
"""
import uuid
from typing import NamedTuple

from app.auth import Actor
from tests.checkout_support import SYDNEY_CBD, a_customer, a_product, checkout_request, committed, order_body


class Bought(NamedTuple):
    order_id: int
    customer_id: int
    email: str                  # tests.auth_support.as_customer(email) signs in as the buyer
    product_id: int
    store_id: int               # the fulfilling store: stock came from here
    total: str


def bought(*, quantity: int = 2, method: str = "click_collect", store_id: int = SYDNEY_CBD, stock: int = 5,
           price: str = "100.00") -> Bought:
    """A paid order for `quantity` of a new product stocked (`stock` units) at `store_id`, checked out by a new
    customer with one address. A delivery goes to that address."""
    product = a_product(price, stock=stock, store_id=store_id)
    customer_id, email = a_customer()
    body = order_body([(product, quantity)], method=method, store_id=store_id,
                      address_no=1 if method == "delivery" else None)
    order, _ = checkout_request(Actor("customer", customer_id, "Checkout Tester"), uuid.uuid4(), body)
    return Bought(order["order_id"], customer_id, email, product["product_id"], store_id, str(order["total"]))


def status_of(order_id: int) -> str:
    return committed("SELECT status FROM customer_order WHERE order_id = %s", (order_id,))[0]["status"]


def history_of(order_id: int) -> list[tuple]:
    """The order's committed history as (from_status, to_status, changed_by_staff_id), oldest first."""
    rows = committed("""SELECT from_status, to_status, changed_by_staff_id FROM order_status_history
                        WHERE order_id = %s ORDER BY seq""", (order_id,))
    return [(row["from_status"], row["to_status"], row["changed_by_staff_id"]) for row in rows]


def payments_of(order_id: int) -> list[tuple]:
    """The order's committed payments as (kind, amount as a string, return_id), in the order they were taken."""
    rows = committed("SELECT kind, amount, return_id FROM payment WHERE order_id = %s ORDER BY payment_id",
                     (order_id,))
    return [(row["kind"], str(row["amount"]), row["return_id"]) for row in rows]
