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
from conversation_core import fold
from psycopg.rows import dict_row

from aziza_adk import config
from aziza_adk.catalog import Product, Service
from aziza_adk.money import ZERO as ZERO_MONEY
from aziza_adk.receipts import Line, Payment

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

#: The statuses a specialist's day is counted in. `partial` earns its commission like any other:
#: the work was done, and collecting the balance is the salon's job rather than hers (§7).
WORKED_STATUSES = ("paid", "partial")


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
               COALESCE(ARRAY_AGG(DISTINCT d.code)
                        FILTER (WHERE d.code IS NOT NULL), '{}'::text[]) AS disciplines,
               COALESCE(ARRAY_AGG(DISTINCT r.code)
                        FILTER (WHERE r.code IS NOT NULL), '{}'::text[]) AS roles
        FROM specialists s
        LEFT JOIN specialist_disciplines sd ON sd.specialist_id = s.id
        LEFT JOIN disciplines d             ON d.id = sd.discipline_id
        LEFT JOIN specialist_roles sr       ON sr.specialist_id = s.id
        LEFT JOIN roles r                   ON r.id = sr.role_id
        WHERE s.telegram_user_id = %(tg)s AND s.active
        GROUP BY s.id
        """,
        {"tg": telegram_user_id},
    )


def stand_down_absent(conn: psycopg.Connection, keep_refs: list[str]) -> int:
    """Deactivate every specialist whose ref is not in `keep_refs`. Answers how many.

    The dataset is the source of truth for WHO MAY TALK TO THIS ASSISTANT: a Telegram id the
    database does not hold active reaches nothing (§3). Without this, deleting someone from the
    dataset and re-seeding would leave their id working — a credential nobody meant to keep.

    Deactivated rather than deleted, which is the same rule the schema enforces on `sales`: the
    salon's record of what she billed stays, and she is stood down rather than erased.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE specialists SET active = FALSE "
            "WHERE active AND NOT (specialist_ref = ANY(%(refs)s))",
            {"refs": keep_refs},
        )
        return cur.rowcount


def retire_absent(
    conn: psycopg.Connection, product_refs: list[str], service_refs: list[str]
) -> int:
    """Deactivate every product and service whose ref the dataset no longer holds. Answers how many.

    What `stand_down_absent` is for people, and for the same reason: a row left active after the
    dataset drops it is still sellable and still listed in the prompt's catalog block, so a
    de-duplication that only edits the dataset does not reach the database at all (§5).

    Deactivated rather than deleted — a past sale line names the row, and that is the salon's own
    record of what it charged.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE products SET active = FALSE WHERE active AND NOT (product_ref = ANY(%(refs)s))",
            {"refs": product_refs},
        )
        retired = cur.rowcount
        cur.execute(
            "UPDATE services SET active = FALSE WHERE active AND NOT (service_ref = ANY(%(refs)s))",
            {"refs": service_refs},
        )
        return retired + cur.rowcount


def working_specialists(conn: psycopg.Connection) -> list[dict]:
    """Everyone whose work can be recorded, with the disciplines each holds.

    Holding a discipline is the whole test, and it is why an owner who also does salon work
    appears here while one who does none does not — naming somebody with nothing to record is not
    a thing to resolve to. The list is what a spoken name is matched against, the same way a
    spoken service is matched against the catalog.

    Someone with no Telegram id is included: the salon records her work, she simply cannot enter
    it herself.
    """
    return fetchall(
        conn,
        """
        SELECT s.id, s.specialist_ref, s.full_name,
               COALESCE(ARRAY_AGG(d.code ORDER BY d.code)
                        FILTER (WHERE d.code IS NOT NULL), '{}'::text[]) AS disciplines
        FROM specialists s
        JOIN specialist_disciplines sd ON sd.specialist_id = s.id
        JOIN disciplines d             ON d.id = sd.discipline_id
        WHERE s.active
        GROUP BY s.id
        ORDER BY s.full_name
        """,
    )


# --- what the salon sells ---------------------------------------------------


def service_catalog(conn: psycopg.Connection) -> list[Service]:
    """Every active service, as the resolver and the prompt block both want it."""
    rows = fetchall(
        conn,
        """
        SELECT sv.service_ref, sv.name, d.code AS discipline,
               sv.price_female, sv.price_male, sv.aliases
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
            price_female=row["price_female"],
            price_male=row["price_male"],
            aliases=tuple(a for a in (row["aliases"] or "").split("|") if a),
        )
        for row in rows
    ]


def product_catalog(conn: psycopg.Connection) -> list[Product]:
    """Every active product. No discipline join: selling one is not authorized against a skill."""
    rows = fetchall(
        conn,
        """
        SELECT product_ref, name, price_client, price_specialist, aliases
        FROM products WHERE active ORDER BY name
        """,
    )
    return [
        Product(
            product_ref=row["product_ref"],
            name=row["name"],
            price_client=row["price_client"],
            price_specialist=row["price_specialist"],
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
        "SELECT id, sale_ref, client_id, client_name, client_gender, gender_source, "
        "       services_total, products_total FROM sales "
        "WHERE specialist_id = %(sid)s AND status = 'open'",
        {"sid": specialist_id},
    )


def create_sale(
    conn: psycopg.Connection,
    specialist_id: int,
    client_name: str,
    *,
    client_id: int,
    client_gender: str,
    gender_source: str,
    recorded_by: int,
) -> dict:
    """Open a ticket. Raises `psycopg.errors.UniqueViolation` when one is already open —
    the index is the guarantee, and the tool's own check is only there to say it kindly."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sales (sale_ref, specialist_id, recorded_by, client_id, client_name, "
            "                   client_gender, gender_source) "
            "VALUES (gen_random_uuid()::text, %(sid)s, %(by)s, %(cid)s, %(name)s, %(gender)s, "
            "        %(source)s) "
            "RETURNING id, sale_ref, client_id, client_name, client_gender, gender_source, "
            "          services_total, products_total",
            {
                "sid": specialist_id,
                "by": recorded_by,
                "cid": client_id,
                "name": client_name,
                "gender": client_gender,
                "source": gender_source,
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row


#: Which column a client reads. A fixed mapping, never a value that reached us from outside.
_PRICE_COLUMN = {"female": "price_female", "male": "price_male"}


def unpriceable_lines(conn: psycopg.Connection, sale_id: int, gender: str) -> list[str]:
    """Services already on this ticket that the salon does not offer to that client.

    Asked BEFORE re-pricing: the column is NOT NULL on the line, so a service with no price for
    the new client cannot simply be re-priced, and silently dropping the line would change a
    ticket the specialist has read. She is told which line, and removes it herself.
    """
    column = _PRICE_COLUMN[gender]
    rows = fetchall(
        conn,
        f"SELECT l.service_name FROM sale_lines l JOIN services sv ON sv.id = l.service_id "
        f"WHERE l.sale_id = %(sale)s AND sv.{column} IS NULL ORDER BY l.id",
        {"sale": sale_id},
    )
    return [r["service_name"] for r in rows]


def gender_affects_ticket(conn: psycopg.Connection, sale_id: int) -> bool:
    """Whether any service on this ticket is priced differently for different clients.

    What decides if the ticket names the client at all: on an acrylic-only ticket both columns
    hold the same amount, so saying which one was read tells the specialist nothing.
    """
    row = fetchone(
        conn,
        "SELECT EXISTS (SELECT 1 FROM sale_lines l JOIN services sv ON sv.id = l.service_id "
        "               WHERE l.sale_id = %(sale)s "
        "                 AND sv.price_female IS DISTINCT FROM sv.price_male) AS differs",
        {"sale": sale_id},
    )
    return bool(row and row["differs"])


def set_sale_gender(
    conn: psycopg.Connection, sale_id: int, gender: str, gender_source: str
) -> None:
    """Re-price every line on the ticket for a different client, in one transaction.

    The snapshot rule on sale_lines protects a quote from a later CATALOG edit; this is not one.
    The client was wrong, so the quote was wrong, and a ticket whose lines disagreed with its own
    client would be the actual defect.
    """
    column = _PRICE_COLUMN[gender]
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE sale_lines l SET unit_price = sv.{column}, "
            f"                        line_total = sv.{column} * l.quantity "
            f"FROM services sv WHERE sv.id = l.service_id AND l.sale_id = %(sale)s",
            {"sale": sale_id},
        )
        cur.execute(
            "UPDATE sales SET client_gender = %(gender)s, gender_source = %(source)s, "
            "  services_total = (SELECT COALESCE(SUM(line_total), 0) FROM sale_lines "
            "                    WHERE sale_id = %(sale)s) "
            "WHERE id = %(sale)s",
            {"sale": sale_id, "gender": gender, "source": gender_source},
        )
    conn.commit()


def add_line(
    conn: psycopg.Connection,
    sale_id: int,
    service: Service,
    quantity: int,
    unit_price: Decimal,
) -> None:
    """Add a service at the CATALOG price, snapshotting it, and recompute the ticket's total.

    `unit_price` is the column the ticket's client reads, chosen by `catalog.price_for` — still
    off the catalog row, never from the model.

    One transaction, so a line can never exist against a stale total.
    """
    line_total = unit_price * Decimal(quantity)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sale_lines "
            "  (sale_id, service_id, service_name, unit_price, quantity, line_total) "
            "SELECT %(sale)s, sv.id, sv.name, %(price)s, %(qty)s, %(total)s "
            "FROM services sv WHERE sv.service_ref = %(ref)s",
            {
                "sale": sale_id,
                "ref": service.service_ref,
                "price": unit_price,
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


def add_product_line(
    conn: psycopg.Connection, sale_id: int, product: Product, quantity: int
) -> None:
    """Sell a product on the open ticket, at the client price, and recompute products_total.

    Writes to its own table and its own total. Nothing here touches services_total, which is what
    keeps a product out of the commission base (§7).
    """
    line_total = product.price_client * Decimal(quantity)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sale_product_lines "
            "  (sale_id, product_id, product_name, unit_price, quantity, line_total) "
            "SELECT %(sale)s, p.id, p.name, %(price)s, %(qty)s, %(total)s "
            "FROM products p WHERE p.product_ref = %(ref)s",
            {
                "sale": sale_id,
                "ref": product.product_ref,
                "price": product.price_client,
                "qty": quantity,
                "total": line_total,
            },
        )
        cur.execute(
            "UPDATE sales SET products_total = "
            "  (SELECT COALESCE(SUM(line_total), 0) FROM sale_product_lines "
            "   WHERE sale_id = %(sale)s) "
            "WHERE id = %(sale)s",
            {"sale": sale_id},
        )
    conn.commit()


def sale_product_lines(conn: psycopg.Connection, sale_id: int) -> list[Line]:
    """The ticket's products, in the order they were added."""
    rows = fetchall(
        conn,
        "SELECT product_name, quantity, unit_price, line_total FROM sale_product_lines "
        "WHERE sale_id = %(sale)s ORDER BY id",
        {"sale": sale_id},
    )
    return [
        Line(
            name=r["product_name"],
            quantity=r["quantity"],
            unit_price=r["unit_price"],
            line_total=r["line_total"],
        )
        for r in rows
    ]


def record_purchase(
    conn: psycopg.Connection,
    specialist_id: int,
    product: Product,
    quantity: int,
    business_date: dt.date,
    recorded_by: int,
) -> Decimal:
    """Debit a specialist for what she took for herself, and answer with the amount.

    At `price_specialist`, which is not a price any client can be given.
    """
    amount = product.price_specialist * Decimal(quantity)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO specialist_ledger "
            "  (specialist_id, recorded_by, kind, product_id, description, amount, "
            "   business_date) "
            "SELECT %(sid)s, %(by)s, 'purchase', p.id, p.name, %(amount)s, %(day)s "
            "FROM products p WHERE p.product_ref = %(ref)s",
            {
                "sid": specialist_id,
                "by": recorded_by,
                "ref": product.product_ref,
                "amount": amount,
                "day": business_date,
            },
        )
    conn.commit()
    return amount


def record_settlement(
    conn: psycopg.Connection,
    specialist_id: int,
    amount: Decimal,
    business_date: dt.date,
    description: str,
    recorded_by: int,
    settles: str,
    method: str,
) -> None:
    """Credit a payment against one of what she owes. Partial is ordinary, not an exception."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO specialist_ledger "
            "  (specialist_id, recorded_by, kind, settles, method, description, amount, "
            "   business_date) "
            "VALUES (%(sid)s, %(by)s, 'payment', %(settles)s, %(method)s, %(desc)s, %(amount)s, "
            "        %(day)s)",
            {
                "sid": specialist_id,
                "by": recorded_by,
                "settles": settles,
                "method": method,
                "desc": description,
                "amount": amount,
                "day": business_date,
            },
        )
    conn.commit()


def record_loan(
    conn: psycopg.Connection,
    specialist_id: int,
    amount: Decimal,
    business_date: dt.date,
    description: str,
    recorded_by: int,
    method: str,
) -> None:
    """Money out of the register and into her hand. A debit like a purchase, and kept apart from
    one because owing for a drink and owing cash are not the same thing to be told you owe."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO specialist_ledger "
            "  (specialist_id, recorded_by, kind, method, description, amount, business_date) "
            "VALUES (%(sid)s, %(by)s, 'loan', %(method)s, %(desc)s, %(amount)s, %(day)s)",
            {
                "sid": specialist_id,
                "by": recorded_by,
                "method": method,
                "desc": description,
                "amount": amount,
                "day": business_date,
            },
        )
    conn.commit()


def debt_balances(conn: psycopg.Connection, specialist_id: int) -> dict[str, Decimal]:
    """What she owes, split the way she is told it: `purchase`, `loan`, and their `total`.

    A payment reduces the one it names, which is why `settles` exists — reported gross the two
    would only ever grow, and a part payment would have to belong to both.
    """
    row = fetchone(
        conn,
        """
        SELECT COALESCE(SUM(CASE WHEN kind = 'purchase' THEN amount
                                 WHEN settles = 'purchase' THEN -amount ELSE 0 END), 0) AS purchase,
               COALESCE(SUM(CASE WHEN kind = 'loan' THEN amount
                                 WHEN settles = 'loan' THEN -amount ELSE 0 END), 0) AS loan
        FROM specialist_ledger WHERE specialist_id = %(sid)s
        """,
        {"sid": specialist_id},
    )
    purchase = row["purchase"] if row else Decimal("0.00")
    loan = row["loan"] if row else Decimal("0.00")
    return {"purchase": purchase, "loan": loan, "total": purchase + loan}


def debt_balance(conn: psycopg.Connection, specialist_id: int) -> Decimal:
    """Everything she owes right now. Derived from the ledger, never stored."""
    return debt_balances(conn, specialist_id)["total"]


# --- the register ------------------------------------------------------------


def open_tickets(conn: psycopg.Connection) -> list[dict]:
    """Every ticket still open, with whose it is. What stops the register being closed early."""
    return fetchall(
        conn,
        "SELECT s.client_name, sp.full_name FROM sales s "
        "JOIN specialists sp ON sp.id = s.specialist_id "
        "WHERE s.status = 'open' ORDER BY sp.full_name",
    )


def expected_register(conn: psycopg.Connection, day: dt.date) -> dict[str, Decimal]:
    """What each account should hold at the end of `day`, by the entries alone.

    `amount + tip`, and NOT minus the change: `amount` is what the ticket received, so a note
    handed over and its change are already netted there. A reader expecting `change_given` to be
    subtracted would double-count it — which is why that column is reported and never summed here.

    Cash tips are in the drawer until they are handed over at the end of the day, so they are part
    of what the count should find (§7).
    """
    totals = {"cash": ZERO_MONEY, "banreservas": ZERO_MONEY, "bhd": ZERO_MONEY}
    rows = fetchall(
        conn,
        """
        SELECT method, SUM(delta) AS delta FROM (
            SELECT p.method, p.amount + p.tip AS delta
              FROM sale_payments p JOIN sales s ON s.id = p.sale_id
             WHERE s.business_date = %(day)s AND s.status IN ('paid', 'partial')
            UNION ALL
            SELECT method, amount FROM client_ledger
             WHERE business_date = %(day)s AND kind = 'payment'
            UNION ALL
            SELECT method, CASE WHEN kind = 'loan' THEN -amount ELSE amount END
              FROM specialist_ledger
             WHERE business_date = %(day)s AND kind IN ('loan', 'payment')
        ) moves GROUP BY method
        """,
        {"day": day},
    )
    for row in rows:
        totals[row["method"]] = row["delta"]
    return totals


def tips_owed(conn: psycopg.Connection, day: dt.date) -> list[dict]:
    """What each specialist is handed at the end of `day`. Hers in full, and paid out of the
    drawer the count is measured against — so it is reported beside the close, not deducted."""
    return fetchall(
        conn,
        """
        SELECT sp.full_name, SUM(p.tip) AS tips
          FROM sale_payments p
          JOIN sales s       ON s.id = p.sale_id
          JOIN specialists sp ON sp.id = s.specialist_id
         WHERE s.business_date = %(day)s AND p.tip > 0
         GROUP BY sp.full_name ORDER BY sp.full_name
        """,
        {"day": day},
    )


def register_close_for(conn: psycopg.Connection, day: dt.date) -> dict | None:
    return fetchone(
        conn, "SELECT * FROM register_closes WHERE business_date = %(day)s", {"day": day}
    )


def record_register_close(
    conn: psycopg.Connection,
    day: dt.date,
    closed_by: int,
    counted: dict[str, Decimal],
    expected: dict[str, Decimal],
) -> None:
    """Both figures, and never the difference: see the table."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO register_closes "
            "  (business_date, closed_by, counted_cash, counted_banreservas, counted_bhd, "
            "   expected_cash, expected_banreservas, expected_bhd) "
            "VALUES (%(day)s, %(by)s, %(cc)s, %(cb)s, %(ch)s, %(ec)s, %(eb)s, %(eh)s)",
            {
                "day": day,
                "by": closed_by,
                "cc": counted["cash"],
                "cb": counted["banreservas"],
                "ch": counted["bhd"],
                "ec": expected["cash"],
                "eb": expected["banreservas"],
                "eh": expected["bhd"],
            },
        )
    conn.commit()


def void_sale(conn: psycopg.Connection, sale_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE sales SET status = 'void' WHERE id = %(sale)s", {"sale": sale_id})
    conn.commit()


# --- the money --------------------------------------------------------------


def add_payment(
    conn: psycopg.Connection,
    sale_id: int,
    method: str,
    amount: Decimal,
    tip: Decimal,
    change_given: Decimal = Decimal("0.00"),
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sale_payments (sale_id, method, amount, tip, change_given) "
            "VALUES (%(sale)s, %(method)s, %(amount)s, %(tip)s, %(change)s)",
            {
                "sale": sale_id,
                "method": method,
                "amount": amount,
                "tip": tip,
                "change": change_given,
            },
        )
    conn.commit()


def sale_payments(conn: psycopg.Connection, sale_id: int) -> list[Payment]:
    rows = fetchall(
        conn,
        "SELECT method, amount, tip, change_given FROM sale_payments "
        "WHERE sale_id = %(sale)s ORDER BY id",
        {"sale": sale_id},
    )
    return [
        Payment(
            method=r["method"], amount=r["amount"], tip=r["tip"], change_given=r["change_given"]
        )
        for r in rows
    ]


def close_sale(
    conn: psycopg.Connection, sale_id: int, business_date: dt.date, status: str = "paid"
) -> None:
    """Close the ticket and stamp the day it belongs to.

    `status` is 'paid' or 'partial' — settled, or closed with a balance the client carries. Both
    close it, because one open ticket per specialist is enforced by the index and a client who
    leaves owing must not stop her serving anybody else.

    The date is passed in rather than taken from `now()`: a night that runs past midnight belongs
    to the day it started, and only the caller knows the salon's clock.
    """
    if status not in ("paid", "partial"):
        raise ValueError(f"not a closing status: {status!r}")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sales SET status = %(status)s, paid_at = now(), business_date = %(day)s "
            "WHERE id = %(sale)s AND status = 'open'",
            {"sale": sale_id, "day": business_date, "status": status},
        )
    conn.commit()


# --- who owes the salon -----------------------------------------------------


def client_for(conn: psycopg.Connection, name: str) -> dict:
    """The client that name refers to, created on her first visit.

    Matched on the FOLDED name, so "MARÍA" and "maria" are one person rather than two balances.
    Two different people who share a name share a row until something asks for a phone — the
    schema says so where the column is.
    """
    key = fold(name)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO clients (client_ref, name, folded) "
            "VALUES (gen_random_uuid()::text, %(name)s, %(key)s) "
            "ON CONFLICT (folded) DO UPDATE SET name = clients.name "
            "RETURNING id, client_ref, name, phone",
            {"name": name.strip(), "key": key},
        )
        row = cur.fetchone()
    conn.commit()
    return row


def find_client(conn: psycopg.Connection, name: str) -> dict | None:
    """The client that name refers to, or None. Never creates: settling a debt against a person
    the salon has never seen would answer a typo with a new client rather than a question."""
    return fetchone(
        conn,
        "SELECT id, client_ref, name, phone FROM clients WHERE folded = %(key)s",
        {"key": fold(name)},
    )


def client_balance(conn: psycopg.Connection, client_id: int) -> Decimal:
    """What she owes right now. Derived from the ledger, never stored."""
    row = fetchone(
        conn,
        "SELECT COALESCE(SUM(CASE WHEN kind = 'debt' THEN amount ELSE -amount END), 0) "
        "  AS balance FROM client_ledger WHERE client_id = %(cid)s",
        {"cid": client_id},
    )
    return row["balance"] if row else Decimal("0.00")


def record_client_debt(
    conn: psycopg.Connection,
    client_id: int,
    sale_id: int,
    amount: Decimal,
    business_date: dt.date,
    recorded_by: int,
) -> None:
    _client_ledger_row(conn, client_id, sale_id, "debt", amount, business_date, recorded_by, None)


def record_client_payment(
    conn: psycopg.Connection,
    client_id: int,
    amount: Decimal,
    business_date: dt.date,
    recorded_by: int,
    method: str,
) -> None:
    _client_ledger_row(conn, client_id, None, "payment", amount, business_date, recorded_by, method)


def _client_ledger_row(
    conn: psycopg.Connection,
    client_id: int,
    sale_id: int | None,
    kind: str,
    amount: Decimal,
    business_date: dt.date,
    recorded_by: int,
    method: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO client_ledger (client_id, sale_id, kind, method, recorded_by, amount, "
            "                           business_date) "
            "VALUES (%(cid)s, %(sale)s, %(kind)s, %(method)s, %(by)s, %(amount)s, %(day)s)",
            {
                "cid": client_id,
                "sale": sale_id,
                "kind": kind,
                "method": method,
                "by": recorded_by,
                "amount": amount,
                "day": business_date,
            },
        )
    conn.commit()


# --- the end of the day -----------------------------------------------------


def period_services(
    conn: psycopg.Connection, specialist_id: int, start: dt.date, end: dt.date
) -> Decimal:
    """What she billed in services across a pay period, inclusive of both ends.

    The base for what has accrued toward pay-day. Tips are not in it — they are handed over the
    same evening, so there is nothing of them left to accumulate (§7).
    """
    row = fetchone(
        conn,
        "SELECT COALESCE(SUM(services_total), 0) AS total FROM sales "
        "WHERE specialist_id = %(sid)s AND status = ANY(%(worked)s) "
        "  AND business_date BETWEEN %(start)s AND %(end)s",
        {"sid": specialist_id, "start": start, "end": end, "worked": list(WORKED_STATUSES)},
    )
    return row["total"] if row else ZERO_MONEY


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
                      AND status = ANY(%(worked)s)), 0) AS services_total,
          COALESCE((SELECT SUM(p.tip) FROM sale_payments p JOIN sales s ON s.id = p.sale_id
                    WHERE s.specialist_id = %(sid)s AND s.business_date = %(day)s
                      AND s.status = ANY(%(worked)s)), 0) AS tips,
          COALESCE((SELECT SUM(products_total) FROM sales
                    WHERE specialist_id = %(sid)s AND business_date = %(day)s
                      AND status = ANY(%(worked)s)), 0) AS products_total,
          -- Her WHOLE outstanding balance, not this day's entries: what she owes is what she
          -- carries, and reporting only today's would read as if the rest were settled. Split,
          -- because owing for a drink and owing cash are told apart on her message (§7).
          COALESCE((SELECT SUM(CASE WHEN kind = 'purchase' THEN amount
                                    WHEN settles = 'purchase' THEN -amount ELSE 0 END)
                    FROM specialist_ledger WHERE specialist_id = %(sid)s), 0) AS owed_products,
          COALESCE((SELECT SUM(CASE WHEN kind = 'loan' THEN amount
                                    WHEN settles = 'loan' THEN -amount ELSE 0 END)
                    FROM specialist_ledger WHERE specialist_id = %(sid)s), 0) AS owed_loans
        """,
        {"sid": specialist_id, "day": business_date, "worked": list(WORKED_STATUSES)},
    )


def owners_with_a_channel(conn: psycopg.Connection) -> list[dict]:
    """Every active owner the assistant can actually message. Who is asked to close the register."""
    return fetchall(
        conn,
        """
        SELECT sp.id, sp.full_name, sp.telegram_user_id
        FROM specialists sp
        JOIN specialist_roles sr ON sr.specialist_id = sp.id
        JOIN roles r             ON r.id = sr.role_id
        WHERE sp.active AND r.code = 'owner' AND sp.telegram_user_id IS NOT NULL
        ORDER BY sp.id
        """,
    )


def specialists_billed_on(conn: psycopg.Connection, business_date: dt.date) -> list[dict]:
    """Everyone who billed on that day. Nobody else is owed a message."""
    return fetchall(
        conn,
        """
        SELECT DISTINCT sp.id, sp.full_name, sp.telegram_user_id
        FROM sales s JOIN specialists sp ON sp.id = s.specialist_id
        WHERE s.business_date = %(day)s AND s.status = ANY(%(worked)s)
        ORDER BY sp.id
        """,
        {"day": business_date, "worked": list(WORKED_STATUSES)},
    )


def claim_summary(
    conn: psycopg.Connection,
    specialist_id: int,
    business_date: dt.date,
    *,
    services_total: Decimal,
    commission: Decimal,
    tips: Decimal,
    products_total: Decimal,
    owed_products: Decimal,
    owed_loans: Decimal,
    period_commission: Decimal,
) -> bool:
    """Claim the right to send one specialist's end-of-day message. True when it is ours.

    DOES NOT COMMIT: the caller commits only once the message has actually gone out, so a failed
    send rolls the claim back and the next run retries it. The unique constraint is what makes a
    second sender lose rather than duplicate.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO daily_summaries "
            "  (specialist_id, business_date, services_total, commission, tips, "
            "   products_total, owed_products, owed_loans, period_commission) "
            "VALUES (%(sid)s, %(day)s, %(services)s, %(commission)s, %(tips)s, "
            "        %(products)s, %(owed_p)s, %(owed_l)s, %(period)s) "
            "ON CONFLICT (specialist_id, business_date) DO NOTHING",
            {
                "sid": specialist_id,
                "day": business_date,
                "services": services_total,
                "commission": commission,
                "tips": tips,
                "products": products_total,
                "owed_p": owed_products,
                "owed_l": owed_loans,
                "period": period_commission,
            },
        )
        return cur.rowcount == 1
