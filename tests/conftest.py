"""Fixtures for the deterministic gate: no model, no network, no key.

Three quarters of the suite touches no database either — the money, the catalog resolution and
the rendered templates are asserted from values alone, which is what lets the arithmetic behind a
commission be held at all.

What does need one is self-cleaning: test specialists carry a sentinel Telegram id prefix and are
deleted in both setup and teardown, cascading their sales away, so the suite is re-runnable and
order-independent. `REQUIRE_DB=1` turns an absent database from skips into failures, so a partial
run cannot report as a green one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from aziza_adk import config, demo_data, queries  # noqa: E402

#: Test specialists live under this Telegram id prefix, so teardown can find and delete them.
#: Well outside the demo dataset's range, so the two can never collide.
SENTINEL_PREFIX = "9999"


def _no_db(reason: str) -> None:
    (pytest.fail if config.REQUIRE_DB else pytest.skip)(reason)


@pytest.fixture(scope="session")
def conn():
    """An autocommit connection for setup and asserts. Skips — or fails — when the business
    database is unreachable or unseeded."""
    try:
        connection = queries.connect()
    except Exception as exc:  # noqa: BLE001 - psycopg.OperationalError, ImportError, anything
        _no_db(
            f"business database not reachable ({exc}). "
            "Run `docker compose up -d` then scripts/seed_mock.py."
        )
    connection.autocommit = True
    row = queries.fetchone(connection, "SELECT COUNT(*) AS n FROM services")
    if row is None or row["n"] == 0:
        connection.close()
        _no_db("business database is empty — run scripts/seed_mock.py")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def sentinel(conn):
    """Delete every test specialist before and after each case, cascading their sales away."""

    def clean() -> None:
        # The sales go first, and that ORDER is the schema talking: `sales.specialist_id` has no
        # ON DELETE action, so a specialist who has billed cannot be deleted at all. That is the
        # production rule — the sales are the salon's own record, and someone who leaves is
        # deactivated rather than erased. Only a test ever removes both.
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sales WHERE specialist_id IN "
                "  (SELECT id FROM specialists WHERE telegram_user_id LIKE %s)",
                (SENTINEL_PREFIX + "%",),
            )
            cur.execute(
                "DELETE FROM specialists WHERE telegram_user_id LIKE %s", (SENTINEL_PREFIX + "%",)
            )

    clean()
    yield SENTINEL_PREFIX
    clean()


@pytest.fixture
def make_specialist(conn, sentinel):
    """Factory: insert a test specialist holding `disciplines`, and return their session state.

    Returns the shape `session.remember_specialist` writes, so a test can put it straight into a
    fake context — the live path and the test path then seed identically.
    """
    seq = {"n": 0}

    def make(*disciplines: str, full_name: str = "Prueba Sentinel") -> dict:
        seq["n"] += 1
        telegram_user_id = f"{SENTINEL_PREFIX}{seq['n']:04d}"
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO specialists (specialist_ref, telegram_user_id, full_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                (f"sentinel-{telegram_user_id}", telegram_user_id, full_name),
            )
            specialist_id = cur.fetchone()["id"]
            for code in disciplines:
                cur.execute(
                    "INSERT INTO specialist_disciplines (specialist_id, discipline_id) "
                    "SELECT %s, id FROM disciplines WHERE code = %s",
                    (specialist_id, code),
                )
        return {
            "id": specialist_id,
            "specialist_ref": f"sentinel-{telegram_user_id}",
            "full_name": full_name,
            "disciplines": list(disciplines),
            "telegram_user_id": telegram_user_id,
        }

    return make


@pytest.fixture
def fake_http(monkeypatch):
    """Install a scripted HTTP client on a channel module. The fakes are the package's own, so
    this repository does not carry a second one that could disagree with it."""
    from channel_telegram.testing import FakeClient

    def install(module, *script):
        client = FakeClient(script)
        monkeypatch.setattr(module.httpx, "AsyncClient", lambda *a, **k: client)
        return client

    return install


class FakeContext:
    """What ADK hands a tool or a callback, with only the parts these read.

    A real `ToolContext` cannot be built without a Runner, which is exactly what this gate must
    not need.
    """

    def __init__(self, state: dict | None = None) -> None:
        self.state: dict = dict(state or {})
        self.agent_name = "sales_agent"


@pytest.fixture
def ctx():
    """Factory for a fake context. With no specialist, it is an unregistered sender."""

    def make(specialist: dict | None = None) -> FakeContext:
        return FakeContext({"specialist": specialist} if specialist else {})

    return make


@pytest.fixture
def working(ctx, make_specialist):
    """A session belonging to a specialist who does nails. What most tool tests need."""
    who = make_specialist("nails")
    return ctx(who), who


def service_named(name: str) -> dict:
    """One row of the demo catalog, read off the dataset rather than typed here — so a change to
    the prices cannot leave a test asserting an amount the salon no longer charges."""
    for row in demo_data.SERVICES:
        if row["name"] == name:
            return row
    raise AssertionError(f"{name!r} is not in demo_data.SERVICES")
