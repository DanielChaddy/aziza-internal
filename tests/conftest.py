"""Fixtures for the deterministic gate: no model, no network, no key.

Three quarters of the suite touches no database either — the money, the catalog resolution and
the rendered templates are asserted from values alone, which is what lets the arithmetic behind a
commission be held at all.

What does need one is self-cleaning: test specialists carry a sentinel `specialist_ref` prefix
and are deleted in both setup and teardown, cascading their sales away, so the suite is
re-runnable and order-independent. `REQUIRE_DB=1` turns an absent database from skips into
failures, so a partial run cannot report as a green one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from aziza_adk import catalog_data, config, queries  # noqa: E402

#: Generated Telegram ids sit under this prefix, well outside the demo dataset's range, so
#: the two can never collide.
SENTINEL_PREFIX = "9999"
#: What teardown matches on. Every factory row carries one, INCLUDING a specialist with no
#: Telegram id — whom an id-matched clean-up would leave behind in the real dataset.
SENTINEL_REF = "sentinel-"

#: The clients the cases open tickets for, registered before each one rather than given a number
#: at seventy call sites. What those cases exercise is the ticket, and a client the salon already
#: knows is the ordinary shape of one: she is never asked for a number again (§3). A case about
#: WHICH client she is names somebody outside this list and registers her itself.
KNOWN_CLIENTS = {
    "Laura": "8090000001",
    "Carmen": "8090000002",
    "Ana": "8090000003",
    "Ariel": "8090000004",
    "MARÍA": "8090000005",
    "Yaritza": "8090000006",
    "Luis": "8090000007",
}


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
    """Delete every test specialist before and after each case, cascading their sales away, and
    register the clients those cases name."""

    def clean() -> None:
        # The records go first, and that ORDER is the schema talking: neither
        # `sales.specialist_id` nor `recorded_by` has an ON DELETE action, so a specialist who has
        # billed — or who has ENTERED an entry for somebody else — cannot be deleted at all. That
        # is the production rule twice over: the sales are the salon's own record and the audit
        # trail is not destroyable, so someone who leaves is deactivated rather than erased. Only
        # a test ever removes both.
        #
        # Matched on either column, because an owner appears in `recorded_by` on rows whose
        # `specialist_id` is somebody else entirely.
        sentinels = "(SELECT id FROM specialists WHERE specialist_ref LIKE %(prefix)s)"
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM specialist_ledger "
                f"WHERE specialist_id IN {sentinels} OR recorded_by IN {sentinels}",
                {"prefix": SENTINEL_REF + "%"},
            )
            # Before the sales they point at: `client_ledger.sale_id` has no ON DELETE action,
            # deliberately, because in the salon a sale is never deleted at all.
            cur.execute(
                f"DELETE FROM client_ledger WHERE recorded_by IN {sentinels} OR sale_id IN "
                f"  (SELECT id FROM sales WHERE specialist_id IN {sentinels} "
                f"                           OR recorded_by IN {sentinels})",
                {"prefix": SENTINEL_REF + "%"},
            )
            cur.execute(
                f"DELETE FROM sales "
                f"WHERE specialist_id IN {sentinels} OR recorded_by IN {sentinels}",
                {"prefix": SENTINEL_REF + "%"},
            )
            # `business_date` is UNIQUE here, so a leftover row would also make the second test
            # that closes a register fail as "already closed" rather than on its own merits.
            cur.execute(
                f"DELETE FROM register_closes WHERE closed_by IN {sentinels}",
                {"prefix": SENTINEL_REF + "%"},
            )
            # Before the specialists, and for the same reason the sales are: `served_by` has no
            # ON DELETE action either, because in the salon a specialist who has taken a client
            # out of the line is not erasable. The wants cascade from the arrival.
            cur.execute(
                f"DELETE FROM arrivals WHERE id IN "
                f"  (SELECT arrival_id FROM arrival_wants WHERE served_by IN {sentinels})",
                {"prefix": SENTINEL_REF + "%"},
            )
            cur.execute(
                "DELETE FROM specialists WHERE specialist_ref LIKE %(prefix)s",
                {"prefix": SENTINEL_REF + "%"},
            )
            # A client the tests invented, recognised by nothing pointing at her rather than by a
            # prefix — she is named the way a real one is. Left behind she would carry a balance
            # into the next run, and "Laura owes nothing" is a case this suite asserts.
            # Every arrival this suite can have made: the clients it registers by name, and the
            # ones a case invented. `arrivals.client_id` cascades, but a KNOWN client survives the
            # sweep below once she has a sale — and her place in the line would survive with her,
            # which is one case leaving the next one a woman already standing in it.
            cur.execute(
                "DELETE FROM arrivals WHERE client_id IN "
                "  (SELECT id FROM clients WHERE phone = ANY(%(phones)s)) "
                "OR client_id IN (SELECT c.id FROM clients c WHERE NOT EXISTS "
                "     (SELECT 1 FROM sales s WHERE s.client_id = c.id))",
                {"phones": list(KNOWN_CLIENTS.values())},
            )
            cur.execute(
                "DELETE FROM clients c WHERE NOT EXISTS "
                "  (SELECT 1 FROM sales s WHERE s.client_id = c.id) "
                "AND NOT EXISTS (SELECT 1 FROM client_ledger l WHERE l.client_id = c.id)"
            )

    def register_known_clients() -> None:
        for name, phone in KNOWN_CLIENTS.items():
            queries.create_client(conn, name, phone)

    clean()
    register_known_clients()
    yield SENTINEL_PREFIX
    clean()


@pytest.fixture
def make_specialist(conn, sentinel):
    """Factory: insert a test specialist holding `disciplines`, and return their session state.

    Returns the shape `session.remember_specialist` writes, so a test can put it straight into a
    fake context — the live path and the test path then seed identically.
    """
    seq = {"n": 0}

    def make(
        *disciplines: str,
        full_name: str = "Prueba Sentinel",
        roles: tuple[str, ...] = (),
        telegram_user_id: str | None = "",
    ) -> dict:
        seq["n"] += 1
        # "" asks for a generated one; None is someone who cannot talk to the assistant at all.
        if telegram_user_id == "":
            telegram_user_id = f"{SENTINEL_PREFIX}{seq['n']:04d}"
        ref = f"{SENTINEL_REF}{seq['n']:04d}"
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO specialists (specialist_ref, telegram_user_id, full_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                (ref, telegram_user_id, full_name),
            )
            specialist_id = cur.fetchone()["id"]
            for code in disciplines:
                cur.execute(
                    "INSERT INTO specialist_disciplines (specialist_id, discipline_id) "
                    "SELECT %s, id FROM disciplines WHERE code = %s",
                    (specialist_id, code),
                )
            for code in roles:
                cur.execute(
                    "INSERT INTO specialist_roles (specialist_id, role_id) "
                    "SELECT %s, id FROM roles WHERE code = %s",
                    (specialist_id, code),
                )
        return {
            "id": specialist_id,
            "specialist_ref": ref,
            "full_name": full_name,
            "disciplines": list(disciplines),
            "roles": list(roles),
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
    """One row of the salon's catalog, read off the dataset rather than typed here — so a change
    to the prices cannot leave a test asserting an amount the salon no longer charges."""
    for row in catalog_data.SERVICES:
        if row["name"] == name:
            return row
    raise AssertionError(f"{name!r} is not in catalog_data.SERVICES")


def product_named(name: str) -> dict:
    """One row of the salon's product list, for the same reason."""
    for row in catalog_data.PRODUCTS:
        if row["name"] == name:
            return row
    raise AssertionError(f"{name!r} is not in catalog_data.PRODUCTS")
