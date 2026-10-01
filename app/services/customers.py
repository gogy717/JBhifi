"""Customers: the support team's directory, and each customer's own record."""
from app.auth import require_customer_self, require_support
from app.errors import NotFound


def list_customers(cur, actor):
    require_support(actor)
    cur.execute("SELECT customer_id, full_name, email FROM customer ORDER BY customer_id")
    return cur.fetchall()


def get_customer(cur, actor, customer_id: int):
    require_customer_self(actor, customer_id)
    cur.execute(
        "SELECT customer_id, full_name, email, phone, created_at FROM customer WHERE customer_id = %s",
        (customer_id,),
    )
    customer = cur.fetchone()
    if customer is None:
        raise NotFound("Customer", customer_id)
    # Current addresses first, then past ones (kept because addresses are never edited, BR16).
    cur.execute(
        """
        SELECT address_no, line1, suburb, state, postcode, is_active
        FROM customer_address
        WHERE customer_id = %s
        ORDER BY is_active DESC, address_no
        """,
        (customer_id,),
    )
    customer["addresses"] = cur.fetchall()
    return customer
