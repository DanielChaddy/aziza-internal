"""The dataset is the source of truth for what the salon sells.

THE property of this file: a row `catalog_data.py` no longer holds stops being sellable. Without
it a de-duplication that edits the dataset never reaches the database — the duplicate stays
active, stays in the prompt's catalog block and stays resolvable, and the edit looks done.

The people half of the same rule is `tests/test_staff.py` §3. Needs a database.
"""

from __future__ import annotations

import pytest

from aziza_adk import catalog_data, queries

_KEEP_PRODUCTS = [row["product_ref"] for row in catalog_data.PRODUCTS]
_KEEP_SERVICES = [row["service_ref"] for row in catalog_data.SERVICES]

_GONE = "prd-retired-sentinel"


@pytest.fixture
def stocked(conn):
    """A product the dataset does not hold, removed again however the case ends."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO products (product_ref, name, price_client, price_specialist, aliases) "
            "VALUES (%(r)s, 'Prueba Sentinel', '1.00', '1.00', '') "
            "ON CONFLICT (product_ref) DO UPDATE SET active = TRUE",
            {"r": _GONE},
        )
    yield _GONE
    with conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE product_ref = %(r)s", {"r": _GONE})


def _active(conn, ref: str) -> bool | None:
    row = queries.fetchone(
        conn, "SELECT active FROM products WHERE product_ref = %(r)s", {"r": ref}
    )
    return None if row is None else row["active"]


def test_a_product_absent_from_the_dataset_is_retired(conn, stocked):
    queries.retire_absent(conn, _KEEP_PRODUCTS, _KEEP_SERVICES)
    assert _active(conn, stocked) is False


def test_retiring_does_not_erase_it(conn, stocked):
    """A past sale line names the row, and what the salon charged is not a test's to remove."""
    queries.retire_absent(conn, _KEEP_PRODUCTS, _KEEP_SERVICES)
    assert _active(conn, stocked) is not None


def test_a_product_the_dataset_still_holds_is_left_alone(conn, stocked):
    """The keep-list is every ref in the dataset, so a run that retires one must retire ONLY it."""
    queries.retire_absent(conn, _KEEP_PRODUCTS, _KEEP_SERVICES)
    assert _active(conn, _KEEP_PRODUCTS[0]) is True


def test_the_catalog_stops_offering_a_retired_row(conn, stocked):
    """The prompt's catalog block and the resolver both read `product_catalog`, which is what
    makes retirement reach the model rather than only the table."""
    queries.retire_absent(conn, _KEEP_PRODUCTS, _KEEP_SERVICES)
    assert stocked not in {p.product_ref for p in queries.product_catalog(conn)}
