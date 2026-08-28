"""Synchronous business-database access (psycopg 3). The only module that opens a connection.

The same psycopg 3 driver serves these sync business queries and ADK's async session engine
(agent-platform docs/ADK_LESSONS_LEARNED.md §6b) — no second database dependency.

Callers hand in a connection and own the transaction. That is what lets one tool add a line and
recompute the sale's total in a single commit, and what keeps a half-written ticket impossible.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from aziza_adk import config
from aziza_adk.catalog import Service
from aziza_adk.receipts import Line, Payment

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def connect(db_url: str | None = None) -> psycopg.Connection:
    """A sync connection with dict rows, its session pinned to the salon's timezone.

    Without the pin every TIMESTAMPTZ reads back in the server's zone, and a business date
    derived from one would be a day out for four hours of every twenty-four.
    """
    conn = psycopg.connect(db_url or config.DATABASE_URL, row_factory=dict_row)
    conn.autocommit = True  # no transaction is open right after connect
    conn.execute("SELECT set_config('TimeZone', %s, false)", (config.TIMEZONE,))
    conn.autocommit = False
    return conn


def apply_schema(conn: psycopg.Connection, schema_path: Path = SCHEMA_PATH) -> None:
    """Apply the idempotent business schema. Safe on every script run."""
    with conn.cursor() as cur:
        cur.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def fetchall(conn: psycopg.Connection, sql: str, params: dict | None = None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


def fetchone(conn: psycopg.Connection, sql: str, params: dict | None = None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchone()


# --- who is talking ---------------------------------------------------------


def specialist_by_telegram_id(conn: psycopg.Connection, telegram_user_id: str) -> dict | None:
    """The specialist this sender is, with the disciplines they hold — or None.

    None covers both "nobody" and "no longer working here", which the caller must not
    distinguish out loud.
    """
    return fetchone(
        conn,
        """
        SELECT s.id, s.specialist_ref, s.full_name,
               COALESCE(ARRAY_AGG(d.code ORDER BY d.code)
                        FILTER (WHERE d.code IS NOT NULL), '{}'::text[]) AS disciplines
        FROM specialists s
        LEFT JOIN specialist_disciplines sd ON sd.specialist_id = s.id
        LEFT JOIN disciplines d             ON d.id = sd.discipline_id
        WHERE s.telegram_user_id = %(tg)s AND s.active
        GROUP BY s.id
        """,
        {"tg": telegram_user_id},
    )


# --- what the salon sells ---------------------------------------------------


def service_catalog(conn: psycopg.Connection) -> list[Service]:
    """Every active service, as the resolver and the prompt block both want it."""
    rows = fetchall(
        conn,
        """
        SELECT sv.service_ref, sv.name, d.code AS discipline, sv.price, sv.aliases
        FROM services sv JOIN disciplines d ON d.id = sv.discipline_id
        WHERE sv.active
        ORDER BY d.code, sv.name
        """,
    )
    return [
        Service(
            service_ref=row["service_ref"],
            name=row["name"],
            discipline=row["discipline"],
            price=row["price"],
            aliases=tuple(a for a in (row["aliases"] or "").split("|") if a),
        )
        for row in rows
    ]


def service_id(conn: psycopg.Connection, service_ref: str) -> int | None:
    row = fetchone(
        conn, "SELECT id FROM services WHERE service_ref = %(ref)s", {"ref": service_ref}
    )
    return row["id"] if row else None


# --- the ticket -------------------------------------------------------------


def open_sale(conn: psycopg.Connection, specialist_id: int) -> dict | None:
    """This specialist's open ticket, or None. At most one exists — see the partial index."""
    return fetchone(
        conn,
        "SELECT id, sale_ref, client_name, services_total FROM sales "
        "WHERE specialist_id = %(sid)s AND status = 'open'",
        {"sid": specialist_id},
    )


def create_sale(conn: psycopg.Connection, specialist_id: int, client_name: str) -> dict:
    """Open a ticket. Raises `psycopg.errors.UniqueViolation` when one is already open —
    the index is the guarantee, and the tool's own check is only there to say it kindly."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sales (sale_ref, specialist_id, client_name) "
            "VALUES (gen_random_uuid()::text, %(sid)s, %(name)s) "
            "RETURNING id, sale_ref, client_name, services_total",
            {"sid": specialist_id, "name": client_name},
        )
        row = cur.fetchone()
    conn.commit()
    return row


def add_line(conn: psycopg.Connection, sale_id: int, service: Service, quantity: int) -> None:
    """Add a service at the CATALOG price, snapshotting it, and recompute the ticket's total.

    One transaction, so a line can never exist against a stale total.
    """
    line_total = service.price * Decimal(quantity)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sale_lines "
            "  (sale_id, service_id, service_name, unit_price, quantity, line_total) "
            "SELECT %(sale)s, sv.id, sv.name, %(price)s, %(qty)s, %(total)s "
            "FROM services sv WHERE sv.service_ref = %(ref)s",
            {
                "sale": sale_id,
                "ref": service.service_ref,
                "price": service.price,
                "qty": quantity,
                "total": line_total,
            },
        )
        cur.execute(
            "UPDATE sales SET services_total = "
            "  (SELECT COALESCE(SUM(line_total), 0) FROM sale_lines WHERE sale_id = %(sale)s) "
            "WHERE id = %(sale)s",
            {"sale": sale_id},
        )
    conn.commit()


def sale_lines(conn: psycopg.Connection, sale_id: int) -> list[Line]:
    """The ticket's services, in the order they were added — which is the order they happened."""
    rows = fetchall(
        conn,
        "SELECT service_name, quantity, unit_price, line_total FROM sale_lines "
        "WHERE sale_id = %(sale)s ORDER BY id",
        {"sale": sale_id},
    )
    return [
        Line(
            name=r["service_name"],
            quantity=r["quantity"],
            unit_price=r["unit_price"],
            line_total=r["line_total"],
        )
        for r in rows
    ]


def void_sale(conn: psycopg.Connection, sale_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE sales SET status = 'void' WHERE id = %(sale)s", {"sale": sale_id})
    conn.commit()


# --- the money --------------------------------------------------------------


def add_payment(
    conn: psycopg.Connection, sale_id: int, method: str, amount: Decimal, tip: Decimal
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sale_payments (sale_id, method, amount, tip) "
            "VALUES (%(sale)s, %(method)s, %(amount)s, %(tip)s)",
            {"sale": sale_id, "method": method, "amount": amount, "tip": tip},
        )
    conn.commit()


def sale_payments(conn: psycopg.Connection, sale_id: int) -> list[Payment]:
    rows = fetchall(
        conn,
        "SELECT method, amount, tip FROM sale_payments WHERE sale_id = %(sale)s ORDER BY id",
        {"sale": sale_id},
    )
    return [Payment(method=r["method"], amount=r["amount"], tip=r["tip"]) for r in rows]


def close_sale(conn: psycopg.Connection, sale_id: int, business_date: dt.date) -> None:
    """Mark the ticket paid and stamp the day it belongs to.

    The date is passed in rather than taken from `now()`: a night that runs past midnight belongs
    to the day it started, and only the caller knows the salon's clock.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sales SET status = 'paid', paid_at = now(), business_date = %(day)s "
            "WHERE id = %(sale)s AND status = 'open'",
            {"sale": sale_id, "day": business_date},
        )
    conn.commit()


# --- the end of the day -----------------------------------------------------


def day_totals(conn: psycopg.Connection, specialist_id: int, business_date: dt.date) -> dict:
    """What one specialist billed and was tipped on one day.

    Two subqueries rather than a join: a sale with three payments would multiply its own total
    by three, and the figure that comes out still looks like money.
    """
    return fetchone(
        conn,
        """
        SELECT
          COALESCE((SELECT SUM(services_total) FROM sales
                    WHERE specialist_id = %(sid)s AND business_date = %(day)s
                      AND status = 'paid'), 0) AS services_total,
          COALESCE((SELECT SUM(p.tip) FROM sale_payments p JOIN sales s ON s.id = p.sale_id
                    WHERE s.specialist_id = %(sid)s AND s.business_date = %(day)s
                      AND s.status = 'paid'), 0) AS tips
        """,
        {"sid": specialist_id, "day": business_date},
    )


def specialists_billed_on(conn: psycopg.Connection, business_date: dt.date) -> list[dict]:
    """Everyone with a paid sale on that day. Nobody else is owed a message."""
    return fetchall(
        conn,
        """
        SELECT DISTINCT sp.id, sp.full_name, sp.telegram_user_id
        FROM sales s JOIN specialists sp ON sp.id = s.specialist_id
        WHERE s.business_date = %(day)s AND s.status = 'paid'
        ORDER BY sp.id
        """,
        {"day": business_date},
    )


def claim_summary(
    conn: psycopg.Connection,
    specialist_id: int,
    business_date: dt.date,
    *,
    services_total: Decimal,
    commission: Decimal,
    tips: Decimal,
) -> bool:
    """Claim the right to send one specialist's end-of-day message. True when it is ours.

    DOES NOT COMMIT: the caller commits only once the message has actually gone out, so a failed
    send rolls the claim back and the next run retries it. The unique constraint is what makes a
    second sender lose rather than duplicate.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO daily_summaries "
            "  (specialist_id, business_date, services_total, commission, tips) "
            "VALUES (%(sid)s, %(day)s, %(services)s, %(commission)s, %(tips)s) "
            "ON CONFLICT (specialist_id, business_date) DO NOTHING",
            {
                "sid": specialist_id,
                "day": business_date,
                "services": services_total,
                "commission": commission,
                "tips": tips,
            },
        )
        return cur.rowcount == 1
