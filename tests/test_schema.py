"""What the schema itself guarantees, where no Python does.

Three of these hold properties nothing else in the suite can see. An index is invisible to every
test that only asks for the right answer, so dropping the one on `clients.folded` — which came
free with the UNIQUE that had to go — would be a silent sequential scan on the turn path. And the
identity rule is an ABSENCE of a constraint: that two people called María can both exist is not a
behaviour any query returns, it is a thing the table permits. Needs a database.
"""

from __future__ import annotations

import psycopg
import pytest

from aziza_adk import queries

_REF = "sentinel-schema-"


def _indexes(conn, table: str) -> set[str]:
    return {
        row["indexname"]
        for row in queries.fetchall(
            conn, "SELECT indexname FROM pg_indexes WHERE tablename = %(t)s", {"t": table}
        )
    }


@pytest.fixture
def clients(conn):
    """Client rows a test writes directly, removed however the case ends."""

    def make(name: str, folded: str, phone: str | None) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clients (client_ref, name, folded, phone) "
                "VALUES (%(r)s || gen_random_uuid()::text, %(n)s, %(f)s, %(p)s) RETURNING id",
                {"r": _REF, "n": name, "f": folded, "p": phone},
            )
            return cur.fetchone()["id"]

    yield make
    with conn.cursor() as cur:
        cur.execute("DELETE FROM clients WHERE client_ref LIKE %(r)s", {"r": _REF + "%"})


def test_a_name_is_still_indexed_after_it_stopped_being_unique(conn):
    """The UNIQUE that had to go was the only index on `folded`, and every lookup reads it."""
    assert "ix_clients_named" in _indexes(conn, "clients")


def test_whose_visits_these_are_is_indexed(conn):
    """A client's history orders by day within one person, and nothing else on `sales` leads with
    the client."""
    assert "ix_sales_client_date" in _indexes(conn, "sales")


def test_two_people_who_share_a_name_can_both_exist(conn, clients):
    """THE property this schema change is for. Not a behaviour any query returns — a thing the
    table permits, and until now did not."""
    clients("María", "maria", "8095550101")
    clients("María", "maria", "8295550202")


def test_the_same_name_and_number_cannot_be_entered_twice(conn, clients):
    """The other half: two rows for one person would be two balances for one person."""
    clients("María", "maria", "8095550101")
    with pytest.raises(psycopg.errors.UniqueViolation):
        clients("María", "maria", "8095550101")
    conn.rollback()


def test_two_clients_who_gave_no_number_are_two_rows(conn, clients):
    """Postgres counts NULLs as distinct, which is what keeps everybody who was never asked from
    collapsing into one heap sharing one balance."""
    first = clients("María", "maria", None)
    assert clients("María", "maria", None) != first


def test_a_number_that_is_not_digits_is_refused_by_the_table(conn, clients):
    """The shape is the app's to enforce, and the column refuses to hold anything else — so a
    caller reaching the table another way cannot store a number nothing can match on."""
    with pytest.raises(psycopg.errors.CheckViolation):
        clients("María", "maria", "809-555-0101")
    conn.rollback()


# --- the line ---------------------------------------------------------------


@pytest.fixture
def arrival(conn, clients):
    """An arrival with one want per discipline named, removed however the case ends."""

    def make(name: str, *disciplines: str) -> tuple[int, dict[str, int]]:
        client_id = clients(name, name.lower(), None)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO arrivals (arrival_ref, client_id, business_date) "
                "VALUES (%(r)s || gen_random_uuid()::text, %(c)s, CURRENT_DATE) RETURNING id",
                {"r": _REF, "c": client_id},
            )
            arrival_id = cur.fetchone()["id"]
            wants = {}
            for code in disciplines:
                cur.execute(
                    "INSERT INTO arrival_wants (arrival_id, discipline_id) "
                    "SELECT %(a)s, id FROM disciplines WHERE code = %(d)s RETURNING id",
                    {"a": arrival_id, "d": code},
                )
                wants[code] = cur.fetchone()["id"]
        return arrival_id, wants

    return make


def _serve(conn, want_id: int, specialist_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE arrival_wants SET status = 'serving', served_by = %(s)s WHERE id = %(w)s",
            {"w": want_id, "s": specialist_id},
        )


def test_two_specialists_cannot_have_one_woman_at_once(conn, arrival, make_specialist):
    """THE product rule, made structural. That a client being attended in one line is absent from
    the other is a thing the TABLE forbids, not a filter a query remembers to write — so a second
    reader of the line cannot hand her to somebody else in the moment between two statements."""
    _, wants = arrival("Carmen Schema", "nails", "wax")
    one, two = make_specialist("nails"), make_specialist("wax")
    _serve(conn, wants["nails"], one["id"])
    with pytest.raises(psycopg.errors.UniqueViolation):
        _serve(conn, wants["wax"], two["id"])


def test_a_specialist_cannot_have_two_women_at_once(conn, arrival, make_specialist):
    """The same shape and the same argument as `ux_sales_one_open_per_specialist`."""
    _, first = arrival("Ana Schema", "nails")
    _, second = arrival("Laura Schema", "nails")
    her = make_specialist("nails")
    _serve(conn, first["nails"], her["id"])
    with pytest.raises(psycopg.errors.UniqueViolation):
        _serve(conn, second["nails"], her["id"])


def test_one_place_per_line_per_arrival(conn, arrival):
    """Changing her mind re-opens the row she has rather than writing a second, so no order can
    hold the same woman twice."""
    arrival_id, _ = arrival("Yaritza Schema", "nails")
    with conn.cursor() as cur, pytest.raises(psycopg.errors.UniqueViolation):
        cur.execute(
            "INSERT INTO arrival_wants (arrival_id, discipline_id) "
            "SELECT %(a)s, id FROM disciplines WHERE code = 'nails'",
            {"a": arrival_id},
        )


def test_a_woman_being_attended_by_nobody_is_refused(conn, arrival):
    """`serving` without a specialist is a client in a chair nothing can ever release."""
    _, wants = arrival("Luisa Schema", "nails")
    with conn.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        cur.execute(
            "UPDATE arrival_wants SET status = 'serving' WHERE id = %(w)s", {"w": wants["nails"]}
        )


def test_the_days_line_is_indexed(conn):
    """The line is read on every turn that asks who is next, and an index is invisible to every
    test that only asks for the right answer."""
    assert "ix_arrivals_day" in _indexes(conn, "arrivals")


# --- [5] What the salon buys ---------------------------------------------------------------


@pytest.fixture
def expense(conn, make_specialist):
    """An expense row a test writes directly, at whatever status it wants."""

    def make(owner_id: int, **over):
        values = {
            "ref": _REF,
            "by": owner_id,
            "status": "registered",
            "supplier": "Suplidora",
            "rnc": "131246813",
            "ncf": "B0100000001",
            "invoice_date": "2026-08-28",
            "business_date": "2026-08-28",
            "method": "cash",
            "total": "1180.00",
            **over,
        }
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO expenses (expense_ref, recorded_by, status, supplier, rnc, ncf, "
                "                      invoice_date, business_date, method, total_paid) "
                "VALUES (%(ref)s || gen_random_uuid()::text, %(by)s, %(status)s, %(supplier)s, "
                "        %(rnc)s, %(ncf)s, %(invoice_date)s, %(business_date)s, %(method)s, "
                "        %(total)s) RETURNING id",
                values,
            )
            return cur.fetchone()["id"]

    return make


def test_one_question_waiting_for_an_answer_per_owner(conn, sentinel, make_specialist, expense):
    """ "The invoice I just sent you" has to mean one thing. The index holds under a race, which a
    check in a tool does not — the same argument as one open ticket per specialist (§15)."""
    owner = make_specialist(roles=("owner",))
    expense(owner["id"], status="draft")
    with pytest.raises(psycopg.errors.UniqueViolation):
        expense(owner["id"], status="draft", ncf="B0100000002")


def test_the_same_supplier_invoice_cannot_be_registered_twice(
    conn, sentinel, make_specialist, expense
):
    """It would come off the register twice, and DGII rejects a repeated comprobante too."""
    owner = make_specialist(roles=("owner",))
    expense(owner["id"])
    with pytest.raises(psycopg.errors.UniqueViolation):
        expense(owner["id"])


def test_a_voided_expense_does_not_hold_its_comprobante_hostage(
    conn, sentinel, make_specialist, expense
):
    """A misread that got through is voided and re-entered, so the void must not block it."""
    owner = make_specialist(roles=("owner",))
    expense(owner["id"], status="void")
    expense(owner["id"])


def test_an_invoice_with_no_comprobante_can_be_registered_more_than_once(
    conn, sentinel, make_specialist, expense
):
    """Two colmado receipts in a week are two expenses, and neither has a comprobante to be
    unique on. A blanket index would have made the second one a collision (§15)."""
    owner = make_specialist(roles=("owner",))
    expense(owner["id"], ncf="")
    expense(owner["id"], ncf="")


def test_money_that_moved_names_the_account_it_moved_through(
    conn, sentinel, make_specialist, expense
):
    """The pair is what keeps a credit purchase out of the register and a cash one in it: an
    expense either moved money through an account on a day, or moved none at all (§15)."""
    owner = make_specialist(roles=("owner",))
    expense(owner["id"], business_date=None, method=None)
    with pytest.raises(psycopg.errors.CheckViolation):
        expense(owner["id"], business_date="2026-08-28", method=None, ncf="B0100000009")


def test_what_the_register_and_the_report_read_are_both_indexed(conn):
    """Two different questions over one table — one day's spend, and one month's filing — so one
    index cannot serve both."""
    found = _indexes(conn, "expenses")
    assert "ix_expenses_business_date" in found
    assert "ix_expenses_period" in found
