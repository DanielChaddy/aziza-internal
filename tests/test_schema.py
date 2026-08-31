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
