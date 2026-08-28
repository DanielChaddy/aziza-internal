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

from aziza_adk import catalog, config, money, names, queries, receipts, session, staff
from aziza_adk.money import ZERO

logger = logging.getLogger("aziza_adk.tools")

#: Every tool needs a registered specialist behind it. `guards.before_tool_guard` refuses each of
#: them without one; the bodies re-check.
SPECIALIST_TOOL_NAMES = frozenset(
    {
        "start_ticket",
        "add_service",
        "set_client_gender",
        "sell_product",
        "show_ticket",
        "void_ticket",
        "record_payment",
        "buy_product",
        "settle_debt",
        "my_day",
    }
)

#: The writes. A ticket must have been quoted before any of the money ones runs.
WRITE_TOOL_NAMES = frozenset(
    {
        "start_ticket",
        "add_service",
        "set_client_gender",
        "sell_product",
        "void_ticket",
        "record_payment",
        "buy_product",
        "settle_debt",
    }
)

#: Needs an open ticket to act on. `buy_product` and `settle_debt` are absent deliberately: what a
#: specialist owes is hers and has nothing to do with whichever client is in the chair.
TICKET_TOOL_NAMES = frozenset(
    {
        "add_service",
        "set_client_gender",
        "sell_product",
        "show_ticket",
        "void_ticket",
        "record_payment",
    }
)

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
UNKNOWN_PRODUCT_MSG = "Ese producto no está en la lista del salón."
AMBIGUOUS_PRODUCT_MSG = "Hay más de un producto con ese nombre. ¿Cuál de estos era?"
NOT_OFFERED_MSG = "El salón no ofrece ese servicio para ese cliente, así que no puedo cargarlo."
BAD_GENDER_MSG = "Dime si la cuenta es de una clienta o de un cliente y ajusto el precio."
LINES_NOT_OFFERED_MSG = (
    "No puedo cambiar el precio de la cuenta: hay servicios que el salón no ofrece para ese "
    "cliente. Quítalos primero y lo cambio."
)
NOTHING_OWED_MSG = "No tienes nada pendiente con el salón."
NOT_AN_ADMIN_MSG = "Solo la administración puede registrar el trabajo de otra especialista."
NEED_SPECIALIST_MSG = "Dime cuál especialista lo hizo y lo registro a su nombre."
UNKNOWN_SPECIALIST_MSG = "No tengo a esa especialista en el salón."
AMBIGUOUS_SPECIALIST_MSG = "Hay más de una especialista con ese nombre. ¿Cuál de estas fue?"
SPECIALIST_BUSY_MSG = "Esa especialista ya tiene una cuenta abierta. Hay que cerrarla primero."
MORE_THAN_OWED_MSG = "Ese monto pasa de lo que debes."
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


def _ticket_answer(conn, sale: dict, tool_context: Any, worked_by: str | None = None) -> dict:
    """The rendered ticket, and the record that this specialist has now seen this total.

    Both happen HERE rather than in each caller, because a quote recorded without the specialist
    actually being shown the figure would satisfy the confirm-first gate on its own.

    EVERY tool that changes what the ticket comes to returns this. The gate is keyed on the total
    as well as the ticket (session.was_quoted), so one that did not would simply fail closed
    rather than authorize a figure nobody was shown.
    """
    lines = queries.sale_lines(conn, sale["id"])
    product_lines = queries.sale_product_lines(conn, sale["id"])
    total = sale["services_total"] + sale["products_total"]
    # Named only when it could change a figure: both columns are equal on the whole acrylic block.
    label = (
        receipts.GENDER_LABELS[sale["client_gender"]]
        if queries.gender_affects_ticket(conn, sale["id"])
        else None
    )
    session.remember_quote(tool_context, sale["sale_ref"], total)
    return {
        "client_name": sale["client_name"],
        "total": money.rd(total),
        "ticket": receipts.render_ticket(
            sale["client_name"],
            lines,
            sale["services_total"],
            product_lines=product_lines,
            products_total=sale["products_total"],
            gender_label=label,
            assumed=sale["gender_source"] == names.DEFAULTED,
            worked_by=worked_by,
        ),
    }


def _acting(conn, tool_context: Any, on_behalf_of: str) -> tuple[staff.Person | None, dict | None]:
    """Whose work this is: `(person, None)`, or `(None, error)` for the caller to return.

    For an ordinary specialist it is herself and there is nothing to resolve. For an admin it is
    whoever she named, resolved against the salon's own list — and NAMING IS REQUIRED. Omitting it
    is refused rather than booked to the admin: she does no salon work, so a sale in her name is
    a commission paid to the wrong person, and that is the failure this whole design exists to
    make impossible (§3).
    """
    named = (on_behalf_of or "").strip()
    if not session.is_admin(tool_context):
        if named:
            # The guard refused this already; a tool reached another way must refuse too.
            return None, {"error": "not_an_admin", "message": NOT_AN_ADMIN_MSG}
        who = session.specialist(tool_context)
        return (
            staff.Person(
                specialist_id=session.specialist_id(tool_context),
                name=str(who.get("full_name") or ""),
                disciplines=session.disciplines(tool_context),
            ),
            None,
        )

    roster = staff.people(queries.working_specialists(conn))
    if not named:
        return None, {
            "error": "specialist_required",
            "message": NEED_SPECIALIST_MSG,
            "options": [person.name for person in roster],
        }
    found = catalog.resolve(named, roster)
    if found.candidates:
        return None, {
            "error": "ambiguous_specialist",
            "message": AMBIGUOUS_SPECIALIST_MSG,
            "options": [person.name for person in found.candidates],
        }
    if found.match is None:
        return None, {
            "error": "unknown_specialist",
            "message": UNKNOWN_SPECIALIST_MSG,
            "options": [person.name for person in roster],
        }
    return found.match, None


def _attributed(person: staff.Person, tool_context: Any) -> str | None:
    """The name to put on the ticket, or None when she is recording her own work.

    Shown exactly when it could be wrong: an admin naming the wrong specialist moves a commission,
    and the ticket is where she sees it before the money does.
    """
    if person.specialist_id == session.specialist_id(tool_context):
        return None
    return person.name


#: What a specialist calls each client. The keys are folded; the values are what the column holds.
_GENDERS = {
    "female": "female",
    "femenino": "female",
    "mujer": "female",
    "clienta": "female",
    "f": "female",
    "male": "male",
    "masculino": "male",
    "hombre": "male",
    "cliente": "male",
    "varon": "male",
    "m": "male",
}


# --- the ticket -------------------------------------------------------------


def start_ticket(
    client_name: str,
    client_gender: str = "",
    on_behalf_of: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Open a new ticket for a client the specialist just worked on.

    Many services cost a different amount depending on the client, so the ticket carries which.
    Pass `client_gender` ONLY when the specialist actually said; do not infer it yourself and do
    not ask for it up front. Left empty, the client's name decides, and the ticket says so.

    Args:
        client_name: The client's name, as the specialist said it.
        client_gender: Only if she said so, in her own words. Empty otherwise.
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

    Returns:
        {"opened": true, "client_name": str, "priced_for": str}, or {"error", "message"}. Opening
        a second ticket while one is still open is an error, not a replacement.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    name = (client_name or "").strip()
    if not name:
        return {"error": "no_client_name", "message": NEED_CLIENT_NAME_MSG}

    said = fold(client_gender or "").strip()
    if said:
        stated = _GENDERS.get(said)
        if stated is None:
            return {"error": "bad_gender", "message": BAD_GENDER_MSG}
        gender, source = stated, names.STATED
    else:
        # A table, never the model: choosing the column is choosing the price (§5).
        gender, source = names.derive(name)

    try:
        with queries.connect() as conn:
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            own = person.specialist_id == session.specialist_id(tool_context)
            if busy := queries.open_sale(conn, person.specialist_id):
                # Named rather than guessed at: her open ticket may be for a different client
                # entirely, and adding to it silently would rewrite someone else's sale.
                return {
                    "error": "ticket_already_open",
                    "message": TICKET_ALREADY_OPEN_MSG if own else SPECIALIST_BUSY_MSG,
                    "client_name": busy["client_name"],
                    "specialist": person.name,
                }
            sale = queries.create_sale(
                conn,
                person.specialist_id,
                name,
                client_gender=gender,
                gender_source=source,
                recorded_by=session.specialist_id(tool_context),
            )
    except Exception as exc:  # noqa: BLE001 - a failed turn leaves a specialist mid-sale
        return _failed(exc)
    return {
        "opened": True,
        "client_name": sale["client_name"],
        "priced_for": receipts.GENDER_LABELS[gender],
        "worked_by": person.name,
    }


def add_service(
    service: str,
    quantity: int = 1,
    on_behalf_of: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Add a service to the open ticket, at the price the salon charges for it.

    The price is NEVER an argument: this looks the service up in the salon's catalog and takes
    the price from there, in the column the ticket's client reads. A service the salon does not
    sell is refused rather than invented, and so is one it does not do for that client.

    Args:
        service: What the specialist called the service, in their own words.
        quantity: How many times it was done. Defaults to 1.
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

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
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            sale = queries.open_sale(conn, person.specialist_id)
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
            # HER areas, not the sender's: an admin recording a wax service for a nails
            # specialist is the same wrong booking as the specialist doing it herself.
            if found.match.discipline not in person.disciplines:
                return {
                    "error": "wrong_discipline",
                    "message": WRONG_DISCIPLINE_MSG,
                    "service": found.match.name,
                }

            unit_price = catalog.price_for(found.match, sale["client_gender"])
            if unit_price is None:
                # The salon does not do this for that client. Not a zero, and not the other
                # column — a refusal with a reason (§5).
                return {
                    "error": "not_offered_to_client",
                    "message": NOT_OFFERED_MSG,
                    "service": found.match.name,
                }

            queries.add_line(conn, sale["id"], found.match, quantity, unit_price)
            return _ticket_answer(
                conn,
                queries.open_sale(conn, person.specialist_id),
                tool_context,
                _attributed(person, tool_context),
            )
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def set_client_gender(
    gender: str, on_behalf_of: str = "", tool_context: ToolContext = None
) -> dict:
    """Correct which client the open ticket is priced for, and re-price everything on it.

    Use this when the specialist says the assistant got it wrong — the ticket is shown again with
    the corrected total, which is what she then confirms before charging.

    Args:
        gender: Who the client is, in the specialist's own words.
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

    Returns:
        The re-priced ticket — {"client_name", "total", "ticket"} — or {"error", "message"}. On
        "not_offered_to_client" the "services" list names the lines that stand in the way.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    canonical = _GENDERS.get(fold(gender or "").strip())
    if canonical is None:
        return {"error": "bad_gender", "message": BAD_GENDER_MSG}
    try:
        with queries.connect() as conn:
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            sale = queries.open_sale(conn, person.specialist_id)
            if sale is None:
                return {"error": "no_open_ticket", "message": NO_TICKET_MSG}

            # Asked before anything moves: a line the salon does not do for the new client has no
            # price to be re-priced to, and dropping it silently would rewrite a ticket she read.
            blocked = queries.unpriceable_lines(conn, sale["id"], canonical)
            if blocked:
                return {
                    "error": "not_offered_to_client",
                    "message": LINES_NOT_OFFERED_MSG,
                    "services": blocked,
                }

            queries.set_sale_gender(conn, sale["id"], canonical, names.STATED)
            return _ticket_answer(
                conn,
                queries.open_sale(conn, person.specialist_id),
                tool_context,
                _attributed(person, tool_context),
            )
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def sell_product(
    product: str,
    quantity: int = 1,
    on_behalf_of: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Add a product the client is buying to the open ticket, at the salon's price.

    Products pay the specialist NO commission. Say so if she asks; never imply otherwise.

    Args:
        product: What the specialist called the product, in their own words.
        quantity: How many. Defaults to 1.
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

    Returns:
        The updated ticket — {"client_name", "total", "ticket"} — or {"error", "message"}. On
        "ambiguous_product" the "options" list names what it might have been; ask which.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if not isinstance(quantity, int) or not 1 <= quantity <= MAX_QUANTITY:
        return {"error": "bad_quantity", "message": BAD_QUANTITY_MSG}
    try:
        with queries.connect() as conn:
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            sale = queries.open_sale(conn, person.specialist_id)
            if sale is None:
                return {"error": "no_open_ticket", "message": NO_TICKET_MSG}

            found = catalog.resolve(product, queries.product_catalog(conn))
            if found.candidates:
                return {
                    "error": "ambiguous_product",
                    "message": AMBIGUOUS_PRODUCT_MSG,
                    "options": [pr.name for pr in found.candidates],
                }
            if found.match is None:
                return {"error": "unknown_product", "message": UNKNOWN_PRODUCT_MSG}

            # No discipline check, and that is deliberate: anyone may sell a drink.
            queries.add_product_line(conn, sale["id"], found.match, quantity)
            return _ticket_answer(
                conn,
                queries.open_sale(conn, person.specialist_id),
                tool_context,
                _attributed(person, tool_context),
            )
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def show_ticket(on_behalf_of: str = "", tool_context: ToolContext = None) -> dict:
    """Show the open ticket: the client, each service with its price, and the total.

    Args:
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

    Returns:
        {"client_name", "total", "ticket"} — send "ticket" to the specialist as it came, without
        rewriting a figure — or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    try:
        with queries.connect() as conn:
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            sale = queries.open_sale(conn, person.specialist_id)
            if sale is None:
                return {"error": "no_open_ticket", "message": NO_TICKET_MSG}
            return _ticket_answer(conn, sale, tool_context, _attributed(person, tool_context))
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def void_ticket(on_behalf_of: str = "", tool_context: ToolContext = None) -> dict:
    """Cancel the open ticket without charging anything. Use it when a service was recorded
    wrong; the specialist then opens a new one.

    Args:
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

    Returns:
        {"voided": true} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    try:
        with queries.connect() as conn:
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            sale = queries.open_sale(conn, person.specialist_id)
            if sale is None:
                return {"error": "no_open_ticket", "message": NO_TICKET_MSG}
            queries.void_sale(conn, sale["id"])
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)
    return {"voided": True, "worked_by": person.name}


# --- the money --------------------------------------------------------------


def record_payment(
    method: str,
    amount: str,
    tip: str = "0",
    on_behalf_of: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Record one payment against the open ticket, and close it once the balance reaches zero.

    Call this once per payment method. A client paying part in cash and part by card is two
    calls, and the ticket stays open until the two add up to the total.

    Args:
        method: How they paid — cash, card or transfer, in the specialist's own words.
        amount: What was handed over for the ticket, in numbers. Never includes the tip.
        tip: The tip on this payment, in numbers. "0" when there was none.
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

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
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            sale = queries.open_sale(conn, person.specialist_id)
            if sale is None:
                return {"error": "no_open_ticket", "message": NO_TICKET_MSG}
            lines = queries.sale_lines(conn, sale["id"])
            product_lines = queries.sale_product_lines(conn, sale["id"])
            if not lines and not product_lines:
                return {"error": "empty_ticket", "message": EMPTY_TICKET_MSG}
            # What the client owes is the whole ticket. Commission is taken on the services half
            # alone, which is why the two totals are stored apart and only added up here (§7).
            owed = sale["services_total"] + sale["products_total"]
            if not session.was_quoted(tool_context, sale["sale_ref"], owed):
                return {"error": "not_quoted", "message": NOT_QUOTED_MSG}

            # TODO: read-then-write with no row lock. The channel's turn lock serializes one
            # specialist, so only a second entry point could race this into an overpayment.
            settled = sum((p.amount for p in queries.sale_payments(conn, sale["id"])), ZERO)
            remaining = owed - settled
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
                    sale["client_name"],
                    lines,
                    sale["services_total"],
                    payments,
                    product_lines=product_lines,
                    products_total=sale["products_total"],
                ),
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def buy_product(
    product: str,
    quantity: int = 1,
    on_behalf_of: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Record that the SPECIALIST took a product for herself, at her own price.

    This is not a sale and never touches a client's ticket: it is a debit against her, which she
    can settle whenever she likes and which shows on her end-of-day message until she does.

    Args:
        product: What she called the product, in her own words.
        quantity: How many. Defaults to 1.
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

    Returns:
        {"charged": str, "balance": str} — what this cost her and what she now owes in total —
        or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if not isinstance(quantity, int) or not 1 <= quantity <= MAX_QUANTITY:
        return {"error": "bad_quantity", "message": BAD_QUANTITY_MSG}
    try:
        with queries.connect() as conn:
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            found = catalog.resolve(product, queries.product_catalog(conn))
            if found.candidates:
                return {
                    "error": "ambiguous_product",
                    "message": AMBIGUOUS_PRODUCT_MSG,
                    "options": [pr.name for pr in found.candidates],
                }
            if found.match is None:
                return {"error": "unknown_product", "message": UNKNOWN_PRODUCT_MSG}

            charged = queries.record_purchase(
                conn,
                person.specialist_id,
                found.match,
                quantity,
                _today(),
                recorded_by=session.specialist_id(tool_context),
            )
            return {
                "charged": money.rd(charged),
                "product": found.match.name,
                "owed_by": person.name,
                "balance": money.rd(queries.debt_balance(conn, person.specialist_id)),
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def settle_debt(amount: str, on_behalf_of: str = "", tool_context: ToolContext = None) -> dict:
    """Record a payment the specialist made against what she owes the salon.

    Part of it is ordinary rather than an exception — she may pay some now and carry the rest.

    Args:
        amount: What she paid, in numbers.
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

    Returns:
        {"paid": str, "balance": str} — what she just paid and what is left — or
        {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    try:
        paid = money.money(amount)
    except ValueError:
        return {"error": "bad_amount", "message": BAD_AMOUNT_MSG}
    if paid <= ZERO:
        return {"error": "bad_amount", "message": BAD_AMOUNT_MSG}
    try:
        with queries.connect() as conn:
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            who = person.specialist_id
            owed = queries.debt_balance(conn, who)
            if owed <= ZERO:
                return {"error": "nothing_owed", "message": NOTHING_OWED_MSG}
            if paid > owed:
                # Refused rather than absorbed, as an overpayment on a ticket is: a credit larger
                # than the debt would leave the salon owing her money nobody decided to owe.
                return {
                    "error": "more_than_owed",
                    "message": MORE_THAN_OWED_MSG,
                    "balance": money.rd(owed),
                }
            queries.record_settlement(
                conn,
                who,
                paid,
                _today(),
                "Pago a cuenta",
                recorded_by=session.specialist_id(tool_context),
            )
            return {
                "paid": money.rd(paid),
                "owed_by": person.name,
                "balance": money.rd(queries.debt_balance(conn, who)),
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def my_day(on_behalf_of: str = "", tool_context: ToolContext = None) -> dict:
    """What this specialist has made today so far, and what she owes the salon.

    The same figures and the same wording the end-of-day message uses, so the two can never
    disagree about a day.

    Args:
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

    Returns:
        {"summary": str} — send it as it came — or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    day = _today()
    try:
        with queries.connect() as conn:
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            totals = queries.day_totals(conn, person.specialist_id, day)
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)
    return {
        "summary": summary_text(
            person.name,
            day,
            totals["services_total"],
            totals["tips"],
            totals["products_total"],
            totals["debt_balance"],
        )
    }


def summary_text(
    full_name: str,
    day: dt.date,
    services_total: Decimal,
    tips: Decimal,
    products_total: Decimal = ZERO,
    debt_balance: Decimal = ZERO,
) -> str:
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
        products_total=products_total,
        debt_balance=debt_balance,
    )
