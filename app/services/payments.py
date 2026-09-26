"""The simulated payment ledger (BR14).

Every entry is written inside the caller's transaction — these helpers never commit. A zero amount writes
no row at all: the domain allows zero, but a payment must be positive, and a zero-value order still needs
its status and stock to advance.
"""
from decimal import Decimal

BREAK_EVEN = Decimal("0.00")


def record_charge(cur, order_id: int, amount: Decimal) -> int | None:
    """The money taken for an order. Returns the payment id, or None when nothing was charged."""
    if Decimal(amount) <= BREAK_EVEN:
        return None
    cur.execute(
        "INSERT INTO payment (order_id, kind, amount) VALUES (%s, 'charge', %s) RETURNING payment_id",
        (order_id, amount),
    )
    return cur.fetchone()["payment_id"]


def record_refund(cur, order_id: int, amount: Decimal, *, return_id: int | None = None,
                  cancellation_id: int | None = None) -> int | None:
    """A refund against exactly one source: a received return, or a cancellation."""
    if (return_id is None) == (cancellation_id is None):
        raise ValueError("a refund needs exactly one source: a return or a cancellation")
    if Decimal(amount) <= BREAK_EVEN:
        return None
    cur.execute(
        "INSERT INTO payment (order_id, kind, amount, return_id, cancellation_id) "
        "VALUES (%s, 'refund', %s, %s, %s) RETURNING payment_id",
        (order_id, amount, return_id, cancellation_id),
    )
    return cur.fetchone()["payment_id"]
