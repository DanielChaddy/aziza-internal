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
