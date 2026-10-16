"""Customers: the support team's directory, each customer's own record, and their delivery addresses."""
from app.auth import require_customer_self, require_own_account, require_support
from app.errors import NotFound
from app.services.filters import contains_pattern


def list_customers(cur, actor, q: str | None = None):
    """The directory (support only). q narrows it to customers whose name or email contains q, in any case;
    its % and _ are matched literally (contains_pattern escapes them)."""
    require_support(actor)
    q = (q or "").strip()
    if not q:
        cur.execute("SELECT customer_id, full_name, email FROM customer ORDER BY customer_id")
        return cur.fetchall()
    pattern = contains_pattern(q)
    cur.execute(
        """
        SELECT customer_id, full_name, email FROM customer
        WHERE full_name ILIKE %s OR email ILIKE %s
        ORDER BY customer_id
        """,
        (pattern, pattern),
    )
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


def add_address(cur, actor, customer_id: int, body):
    """Add a delivery address under the customer's next address number (a weak entity: 1, 2, 3, … per customer).

    Two adds at once would both read the same max(address_no), so the customer row is locked first: the second
    add waits for the first to commit, and its INSERT — a new statement, so a new snapshot under READ
    COMMITTED — then sees the first one's address and takes the next number.
    """
    require_own_account(actor, customer_id)
    cur.execute("SELECT 1 FROM customer WHERE customer_id = %s FOR UPDATE", (customer_id,))
    cur.execute(
        """
        INSERT INTO customer_address (customer_id, address_no, line1, suburb, state, postcode)
        SELECT %s, COALESCE(max(address_no), 0) + 1, %s, %s, %s, %s
        FROM customer_address
        WHERE customer_id = %s
        RETURNING address_no, line1, suburb, state, postcode, is_active
        """,
        (customer_id, body.line1, body.suburb, body.state, body.postcode, customer_id),
    )
    return cur.fetchone()


def retire_address(cur, actor, customer_id: int, address_no: int):
    """Retire an address: it stays, because orders placed with it point at it (BR16), but no new order may use
    it (BR17). Retiring it again changes nothing and answers with the same row."""
    require_own_account(actor, customer_id)
    # `AND is_active`: an address already retired is left alone, not rewritten.
    cur.execute(
        """
        UPDATE customer_address SET is_active = FALSE
        WHERE customer_id = %s AND address_no = %s AND is_active
        RETURNING address_no, line1, suburb, state, postcode, is_active
        """,
        (customer_id, address_no),
    )
    retired = cur.fetchone()
    if retired is not None:
        return retired
    cur.execute(
        """
        SELECT address_no, line1, suburb, state, postcode, is_active
        FROM customer_address
        WHERE customer_id = %s AND address_no = %s
        """,
        (customer_id, address_no),
    )
    address = cur.fetchone()
    if address is None:
        raise NotFound("Address", address_no)
    return address                                  # already retired: the same answer, nothing changed
