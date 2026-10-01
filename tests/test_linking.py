"""The first time a subject signs in, link it to our data (app/auth.py, spec §4.3): staff by email, else an
existing customer by email, else a new customer. These tests commit, so each uses fresh emails/subjects."""
import uuid

from fastapi.testclient import TestClient

from app import identity
from app.auth import link_account
from app.main import app
from tests.auth_support import as_subject, bearer
from tests.support import connect, run_at_once

client = TestClient(app)
API = "/api/v1"


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


def fresh(prefix: str) -> tuple[str, str]:
    """A new (subject, email) pair no other test uses."""
    tag = uuid.uuid4().hex[:10]
    return f"user_{prefix}_{tag}", f"{prefix}.{tag}@example.com"


def committed(query: str, params=()):
    """Run one statement in its own committed transaction; return its first row, if any."""
    conn = connect()
    with conn, conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone() if cur.description else None
    conn.close()
    return row


def accounts_for(subject: str) -> int:
    return committed("SELECT count(*) AS n FROM user_account WHERE auth_subject = %s", (subject,))["n"]


def me(headers):
    return client.get(f"{API}/me", headers=headers)


def test_me_needs_a_signed_in_caller():
    assert error_of(client.get(f"{API}/me")) == (401, "not_signed_in")
    assert error_of(client.get(f"{API}/me", headers={"Authorization": "Basic YWxpY2U6cHc="})) == (401, "invalid_token")
    assert error_of(client.get(f"{API}/me", headers={"Authorization": "Bearer"})) == (401, "invalid_token")


def test_public_reads_need_no_sign_in():
    assert client.get(f"{API}/products").status_code == 200


def test_a_new_email_becomes_a_new_customer():
    subject, email = fresh("shopper")
    response = me(as_subject(subject, email, name="New Shopper"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["kind"], body["display_name"], body["store_id"]) == ("customer", "New Shopper", None)
    assert committed("SELECT email FROM customer WHERE customer_id = %s", (body["id"],))["email"] == email


def test_an_existing_customer_email_links_in_any_case():
    subject, email = fresh("existing")
    customer_id = committed("INSERT INTO customer (email, full_name) VALUES (%s, 'Existing Customer') "
                            "RETURNING customer_id", (email,))["customer_id"]
    body = me(as_subject(subject, email.upper())).json()
    assert (body["kind"], body["id"]) == ("customer", customer_id)
    assert committed("SELECT count(*) AS n FROM customer WHERE lower(email) = %s", (email,))["n"] == 1


def test_a_staff_email_links_to_that_staff_member():
    subject, email = fresh("staffer")
    staff_id = committed("INSERT INTO staff (store_id, staff_type, full_name, email) "
                         "VALUES (3, 'store', 'New Staffer', %s) RETURNING staff_id", (email,))["staff_id"]
    body = me(as_subject(subject, email)).json()
    assert (body["kind"], body["id"], body["store_id"], body["staff_type"], body["runs_store"]) \
        == ("staff", staff_id, 3, "store", False)


def test_an_unverified_email_is_refused_and_nothing_is_written():
    subject, email = fresh("unverified")
    assert error_of(me(as_subject(subject, email, verified=False))) == (403, "email_not_verified")
    assert committed("SELECT count(*) AS n FROM customer WHERE email = %s", (email,))["n"] == 0
    assert accounts_for(subject) == 0


def test_an_unreachable_provider_is_a_503_and_nothing_is_written():
    subject, _ = fresh("unknown")                         # never registered: the fake provider can't find it
    assert error_of(me(bearer(subject))) == (503, "identity_provider_unavailable")
    assert accounts_for(subject) == 0


def test_an_email_the_database_refuses_is_a_409_and_nothing_is_written():
    subject, _ = fresh("bademail")
    assert error_of(me(as_subject(subject, "someone@localhost"))) == (409, "br01_email_format")
    assert accounts_for(subject) == 0


def test_the_provider_is_asked_only_the_first_time(monkeypatch):
    subject, email = fresh("once")
    asked = []
    provider = identity.fetch_profile                      # the fake installed by conftest.py
    monkeypatch.setattr(identity, "fetch_profile", lambda s: asked.append(s) or provider(s))
    assert me(as_subject(subject, email)).status_code == 200
    assert me(bearer(subject)).status_code == 200
    assert asked == [subject]


def first_request(subject: str):
    """What one request does to link a subject: its own connection, one transaction."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            return dict(link_account(cur, subject))
    finally:
        conn.close()


def test_two_first_requests_at_once_make_one_link():
    subject, email = fresh("racing")
    as_subject(subject, email)
    results = run_at_once(2, lambda: first_request(subject))
    assert all(isinstance(result, dict) for result in results), results
    assert results[0] == results[1]
    assert committed("SELECT count(*) AS n FROM customer WHERE email = %s", (email,))["n"] == 1
    assert accounts_for(subject) == 1


# A seeded person signing in for the first time: under `next dev` the page asks GET /me twice at once.
# Both requests find the existing row, so nothing serialises them before the user_account insert.

def test_two_first_sign_ins_of_an_existing_customer_make_one_link():
    for _ in range(20):
        subject, email = fresh("existing_race")
        committed("INSERT INTO customer (email, full_name) VALUES (%s, 'Existing Racer')", (email,))
        as_subject(subject, email)
        results = run_at_once(2, lambda: first_request(subject))
        assert all(isinstance(result, dict) for result in results), results
        assert accounts_for(subject) == 1


def test_two_first_sign_ins_of_an_existing_staff_member_make_one_link():
    for _ in range(20):
        subject, email = fresh("staff_race")
        committed("INSERT INTO staff (store_id, staff_type, full_name, email) "
                  "VALUES (3, 'store', 'Racing Staffer', %s)", (email,))
        as_subject(subject, email)
        results = run_at_once(2, lambda: first_request(subject))
        assert all(isinstance(result, dict) for result in results), results
        assert accounts_for(subject) == 1


def test_a_person_already_linked_to_another_sign_in_is_a_readable_409():
    subject, email = fresh("relinked")
    old_subject, _ = fresh("old")
    customer_id = committed("INSERT INTO customer (email, full_name) VALUES (%s, 'Relinked Customer') "
                            "RETURNING customer_id", (email,))["customer_id"]
    committed("INSERT INTO user_account (auth_subject, customer_id) VALUES (%s, %s)", (old_subject, customer_id))
    response = me(as_subject(subject, email))
    assert error_of(response) == (409, "br19_account_one_customer")
    assert "already linked" in response.json()["error"]["message"]
    assert accounts_for(subject) == 0
