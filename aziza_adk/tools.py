"""The model-facing tools.

English names, English docstrings and English keys: the schema is code, and only the values a
specialist reads are Spanish (agent-platform CLAUDE.md).

Every tool returns a dict and never raises — an error is data the model can re-plan around, and a
turn that blows up leaves a specialist mid-sale with no reply. Identity is read from session state
and never from an argument: a commission is what a person is paid, so there is no parameter in
which a model could name a specialist it is not.

The authorization these tools rely on is `guards.before_tool_guard`'s, and they re-check it
anyway: a tool reached some other way must not answer.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from conversation_core import fold
from google.adk.tools import ToolContext

from aziza_adk import catalog, config, money, queries, receipts, session
from aziza_adk.money import ZERO

logger = logging.getLogger("aziza_adk.tools")

#: Every tool needs a registered specialist behind it. `guards.before_tool_guard` refuses each of
#: them without one; the bodies re-check.
SPECIALIST_TOOL_NAMES = frozenset(
    {
        "start_ticket",
        "add_service",
        "show_ticket",
        "void_ticket",
        "record_payment",
        "my_day",
    }
)

#: The writes. A ticket must have been quoted before any of the money ones runs.
WRITE_TOOL_NAMES = frozenset({"start_ticket", "add_service", "void_ticket", "record_payment"})

#: Needs an open ticket to act on.
TICKET_TOOL_NAMES = frozenset({"add_service", "show_ticket", "void_ticket", "record_payment"})

MAX_QUANTITY = 20

_TZ = ZoneInfo(config.TIMEZONE)

# Specialist-facing copy — docs/BRAND_VOICE.md. Spanish, "tú", short, no ceremony.
NOT_REGISTERED_MSG = (
    "No te tengo registrada en el sistema del salón. Pídele a la administración que te agregue "
    "y con gusto seguimos."
)
NO_TICKET_MSG = "No tienes una cuenta abierta. Dime el nombre de la clienta y la abro."
TICKET_ALREADY_OPEN_MSG = "Ya tienes una cuenta abierta. Ciérrala o anúlala antes de abrir otra."
NEED_CLIENT_NAME_MSG = "¿Cómo se llama la clienta?"
UNKNOWN_SERVICE_MSG = "Ese servicio no está en la lista del salón."
AMBIGUOUS_SERVICE_MSG = "Hay más de un servicio con ese nombre. ¿Cuál de estos fue?"
WRONG_DISCIPLINE_MSG = "Ese servicio no es de tu área, así que no puedo cargarlo a tu nombre."
BAD_QUANTITY_MSG = f"La cantidad tiene que ser un número entre 1 y {MAX_QUANTITY}."
EMPTY_TICKET_MSG = "La cuenta todavía no tiene servicios. Dime qué le hiciste primero."
NOT_QUOTED_MSG = "Déjame mostrarte la cuenta con el total antes de cobrar."
BAD_METHOD_MSG = "¿Pagó en efectivo, con tarjeta o por transferencia?"
BAD_AMOUNT_MSG = "No entendí el monto. Dímelo en números, por ejemplo 1500."
OVERPAYMENT_MSG = (
    "Ese monto pasa de lo que falta por cobrar. Si la diferencia es propina, dímelo así."
)
BACKEND_DOWN_MSG = "No pude guardar eso ahora mismo. ¿Lo intentamos de nuevo en un momento?"

#: What a specialist calls each way of paying. The keys are the canonical values the column and
#: the tool argument carry.
_METHODS = {
    "efectivo": "cash",
    "cash": "cash",
    "cheles": "cash",
    "tarjeta": "card",
    "card": "card",
    "credito": "card",
    "debito": "card",
    "transferencia": "transfer",
    "transfer": "transfer",
    "transferencia bancaria": "transfer",
}


def _today() -> dt.date:
    """The salon's own date. A night that runs past midnight still belongs to the day it began,
    which is what the closing hour would encode if the salon gave us one — an open item."""
    return dt.datetime.now(_TZ).date()


def _unauthorized(tool_context: Any) -> dict | None:
    """Defense in depth: the guard already refused, and a tool reached another way must too."""
    if not session.specialist_id(tool_context):
        return {"error": "not_registered", "message": NOT_REGISTERED_MSG}
    return None


def _failed(exc: Exception) -> dict:
    logger.warning("query failed: %s", type(exc).__name__)
    return {"error": "backend_unavailable", "message": BACKEND_DOWN_MSG}


def _ticket_answer(conn, sale: dict, tool_context: Any) -> dict:
    """The rendered ticket, and the record that this specialist has now seen this total.

    Both happen HERE rather than in each caller, because a quote recorded without the specialist
    actually being shown the figure would satisfy the confirm-first gate on its own.
    """
    lines = queries.sale_lines(conn, sale["id"])
    total = sale["services_total"]
    session.remember_quote(tool_context, sale["sale_ref"])
    return {
        "client_name": sale["client_name"],
        "total": money.rd(total),
        "ticket": receipts.render_ticket(sale["client_name"], lines, total),
    }


# --- the ticket -------------------------------------------------------------


def start_ticket(client_name: str, tool_context: ToolContext = None) -> dict:
    """Open a new ticket for a client the specialist just worked on.

    Args:
        client_name: The client's name, as the specialist said it.

    Returns:
        {"opened": true, "client_name": str}, or {"error", "message"}. Opening a second ticket
        while one is still open is an error, not a replacement.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    name = (client_name or "").strip()
    if not name:
        return {"error": "no_client_name", "message": NEED_CLIENT_NAME_MSG}
    try:
        with queries.connect() as conn:
            if queries.open_sale(conn, session.specialist_id(tool_context)):
                return {"error": "ticket_already_open", "message": TICKET_ALREADY_OPEN_MSG}
            sale = queries.create_sale(conn, session.specialist_id(tool_context), name)
    except Exception as exc:  # noqa: BLE001 - a failed turn leaves a specialist mid-sale
        return _failed(exc)
    return {"opened": True, "client_name": sale["client_name"]}


def add_service(service: str, quantity: int = 1, tool_context: ToolContext = None) -> dict:
    """Add a service to the open ticket, at the price the salon charges for it.

    The price is NEVER an argument: this looks the service up in the salon's catalog and takes
    the price from there. A service the salon does not sell is refused rather than invented.

    Args:
        service: What the specialist called the service, in their own words.
        quantity: How many times it was done. Defaults to 1.

    Returns:
        The updated ticket — {"client_name", "total", "ticket"} — or {"error", "message"}. On
        "ambiguous_service" the "options" list names what it might have been; ask which.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if not isinstance(quantity, int) or not 1 <= quantity <= MAX_QUANTITY:
        return {"error": "bad_quantity", "message": BAD_QUANTITY_MSG}
    try:
        with queries.connect() as conn:
            sale = queries.open_sale(conn, session.specialist_id(tool_context))
            if sale is None:
                return {"error": "no_open_ticket", "message": NO_TICKET_MSG}

            found = catalog.resolve(service, queries.service_catalog(conn))
            if found.candidates:
                return {
                    "error": "ambiguous_service",
                    "message": AMBIGUOUS_SERVICE_MSG,
                    "options": [s.name for s in found.candidates],
                }
            if found.match is None:
                return {
                    "error": "unknown_service",
                    "message": UNKNOWN_SERVICE_MSG,
                    "options": list(catalog.names(queries.service_catalog(conn))),
                }
            if found.match.discipline not in session.disciplines(tool_context):
                return {
                    "error": "wrong_discipline",
                    "message": WRONG_DISCIPLINE_MSG,
                    "service": found.match.name,
                }

            queries.add_line(conn, sale["id"], found.match, quantity)
            return _ticket_answer(
                conn, queries.open_sale(conn, session.specialist_id(tool_context)), tool_context
            )
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def show_ticket(tool_context: ToolContext = None) -> dict:
    """Show the open ticket: the client, each service with its price, and the total.

    Returns:
        {"client_name", "total", "ticket"} — send "ticket" to the specialist as it came, without
        rewriting a figure — or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    try:
        with queries.connect() as conn:
            sale = queries.open_sale(conn, session.specialist_id(tool_context))
            if sale is None:
                return {"error": "no_open_ticket", "message": NO_TICKET_MSG}
            return _ticket_answer(conn, sale, tool_context)
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def void_ticket(tool_context: ToolContext = None) -> dict:
    """Cancel the open ticket without charging anything. Use it when a service was recorded
    wrong; the specialist then opens a new one.

    Returns:
        {"voided": true} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    try:
        with queries.connect() as conn:
            sale = queries.open_sale(conn, session.specialist_id(tool_context))
            if sale is None:
                return {"error": "no_open_ticket", "message": NO_TICKET_MSG}
            queries.void_sale(conn, sale["id"])
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)
    return {"voided": True}


# --- the money --------------------------------------------------------------


def record_payment(
    method: str, amount: str, tip: str = "0", tool_context: ToolContext = None
) -> dict:
    """Record one payment against the open ticket, and close it once the balance reaches zero.

    Call this once per payment method. A client paying part in cash and part by card is two
    calls, and the ticket stays open until the two add up to the total.

    Args:
        method: How they paid — cash, card or transfer, in the specialist's own words.
        amount: What was handed over for the SERVICES, in numbers. Never includes the tip.
        tip: The tip on this payment, in numbers. "0" when there was none.

    Returns:
        While money is still owed, {"remaining": str}. On the last payment, {"paid": true,
        "receipt": str} — send "receipt" as it came. Or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused

    canonical = _METHODS.get(fold(method or "").strip())
    if canonical is None:
        return {"error": "bad_method", "message": BAD_METHOD_MSG}
    try:
        paid = money.money(amount)
        gratuity = money.money(tip or "0")
    except ValueError:
        return {"error": "bad_amount", "message": BAD_AMOUNT_MSG}
    if paid <= ZERO or gratuity < ZERO:
        return {"error": "bad_amount", "message": BAD_AMOUNT_MSG}

    try:
        with queries.connect() as conn:
            sale = queries.open_sale(conn, session.specialist_id(tool_context))
            if sale is None:
                return {"error": "no_open_ticket", "message": NO_TICKET_MSG}
            lines = queries.sale_lines(conn, sale["id"])
            if not lines:
                return {"error": "empty_ticket", "message": EMPTY_TICKET_MSG}
            if not session.was_quoted(tool_context, sale["sale_ref"]):
                return {"error": "not_quoted", "message": NOT_QUOTED_MSG}

            # TODO: read-then-write with no row lock. The channel's turn lock serializes one
            # specialist, so only a second entry point could race this into an overpayment.
            settled = sum((p.amount for p in queries.sale_payments(conn, sale["id"])), ZERO)
            remaining = sale["services_total"] - settled
            if paid > remaining:
                # Refused rather than absorbed: a payment above the balance is either a typo or a
                # tip, and guessing which one writes the wrong commission either way.
                return {
                    "error": "overpayment",
                    "message": OVERPAYMENT_MSG,
                    "remaining": money.rd(remaining),
                }

            queries.add_payment(conn, sale["id"], canonical, paid, gratuity)
            remaining -= paid
            if remaining > ZERO:
                return {"paid": False, "remaining": money.rd(remaining)}

            queries.close_sale(conn, sale["id"], _today())
            payments = queries.sale_payments(conn, sale["id"])
            return {
                "paid": True,
                "receipt": receipts.render_receipt(
                    sale["client_name"], lines, sale["services_total"], payments
                ),
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def my_day(tool_context: ToolContext = None) -> dict:
    """What this specialist has made today so far: services, commission, tips and the total.

    The same figures and the same wording the end-of-day message uses, so the two can never
    disagree about a day.

    Returns:
        {"summary": str} — send it as it came — or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    who = session.specialist(tool_context)
    day = _today()
    try:
        with queries.connect() as conn:
            totals = queries.day_totals(conn, session.specialist_id(tool_context), day)
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)
    return {
        "summary": summary_text(
            who.get("full_name", ""), day, totals["services_total"], totals["tips"]
        )
    }


def summary_text(full_name: str, day: dt.date, services_total: Decimal, tips: Decimal) -> str:
    """One day's figures as the specialist reads them.

    Here rather than in `receipts` because the commission rate is configuration, and here rather
    than in each caller because `my_day` and the end-of-day job must not be able to disagree.
    """
    return receipts.render_day(
        full_name.split()[0] if full_name else "",
        day,
        services_total=services_total,
        commission_pct=config.COMMISSION_PCT,
        commission=money.commission(services_total, config.COMMISSION_PCT),
        tips=tips,
    )
