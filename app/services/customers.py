"""Customers. Read-only for now: the storefront's demo switcher lists them (plan §7 demo login)."""
from app.errors import NotFound

ADDRESS_COLUMNS = "address_no, line1, suburb, state, postcode, is_active"


def add_address(cur, customer_id: int, body):
    """Add an address, numbered under one lock so two adds cannot pick the same number.

    The customer row is locked first, so concurrent adds queue: each sees the previous one's committed
    `max(address_no)` and the weak entity's key stays unique.
    """
    cur.execute("SELECT 1 FROM customer WHERE customer_id = %s FOR UPDATE", (customer_id,))
    if cur.fetchone() is None:
        raise NotFound("Customer", customer_id)
    cur.execute(
        f"""
        INSERT INTO customer_address (customer_id, address_no, line1, suburb, state, postcode)
        SELECT %s, COALESCE(max(address_no), 0) + 1, %s, %s, %s, %s
        FROM customer_address WHERE customer_id = %s
        RETURNING {ADDRESS_COLUMNS}
        """,
        (customer_id, body.line1.strip(), body.suburb.strip(), body.state, body.postcode, customer_id),
    )
    return cur.fetchone()


def retire_address(cur, customer_id: int, address_no: int):
    """Retire (deactivate) an address. Retiring again returns the same, already-retired address."""
    cur.execute(
        f"""
        UPDATE customer_address SET is_active = FALSE
        WHERE customer_id = %s AND address_no = %s AND is_active
        RETURNING {ADDRESS_COLUMNS}
        """,
        (customer_id, address_no),
    )
    retired = cur.fetchone()
    if retired is not None:
        return retired
    cur.execute(
        f"SELECT {ADDRESS_COLUMNS} FROM customer_address WHERE customer_id = %s AND address_no = %s",
        (customer_id, address_no),
    )
    existing = cur.fetchone()
    if existing is None:
        raise NotFound("Address", address_no)
    return existing                                  # already inactive: the same answer, no change


def list_customers(cur):
    cur.execute("SELECT customer_id, full_name, email FROM customer ORDER BY customer_id")
    return cur.fetchall()


def get_customer(cur, customer_id: int):
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
