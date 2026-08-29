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

from aziza_adk import (
    catalog,
    config,
    money,
    names,
    pay,
    queries,
    receipts,
    session,
    staff,
)
from aziza_adk.money import ZERO

logger = logging.getLogger("aziza_adk.tools")

#: What the salon's hours gate: everything that writes a ticket or moves money. Reading is left
#: open, so she can still look at her day after closing — see docs/PROJECT_DEFINITION.md §8.
AFTER_HOURS_TOOL_NAMES = frozenset(
    {
        "start_ticket",
        "add_service",
        "sell_product",
        "record_payment",
        "close_ticket_with_debt",
        "settle_client_debt",
        "buy_product",
        "record_loan",
    }
)

#: What only an owner may do at all, at any hour. `guards.before_tool_guard` refuses these for
#: anyone else; the bodies re-check, as they do for `on_behalf_of`.
OWNER_TOOL_NAMES = frozenset({"close_register", "record_loan", "salon_day"})

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
        "close_ticket_with_debt",
        "settle_client_debt",
        "buy_product",
        "settle_debt",
        "my_day",
        "close_register",
        "record_loan",
        "salon_day",
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
NAME_IS_THE_WORK_MSG = "Eso es lo que le hiciste, no su nombre. ¿Cómo se llama la clienta?"
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
NOT_AN_OWNER_MSG = "Solo una dueña puede registrar el trabajo de otra especialista."
AFTER_HOURS_MSG = "Fuera del horario del salón esto solo lo registra una dueña."
BAD_EXTRA_MSG = "¿Ese excedente es propina o hay que darle el vuelto?"
NOTHING_OWED_MSG = "Esa clienta no debe nada."
NOTHING_OUTSTANDING_MSG = "Esa cuenta ya está saldada. No queda nada por cobrar."
OWNER_ONLY_MSG = "Eso lo hace una dueña."
BAD_OWES_MSG = "¿Eso es de productos o del préstamo?"
REGISTER_CLOSED_MSG = "La caja de hoy ya está cerrada."
TICKETS_STILL_OPEN_MSG = "Todavía hay cuentas abiertas. Ciérralas antes de cuadrar la caja."
OVERPAID_DEBT_MSG = "Eso es más de lo que debe. Cóbrale {balance} y quedan en cero."
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
BAD_METHOD_MSG = "¿Pagó en efectivo, por Banreservas o por BHD?"
BAD_AMOUNT_MSG = "No entendí el monto. Dímelo en números, por ejemplo 1500."
OVERPAYMENT_MSG = (
    "Ese monto pasa de lo que falta por cobrar. Si la diferencia es propina, dímelo así."
)
BACKEND_DOWN_MSG = "No pude guardar eso ahora mismo. ¿Lo intentamos de nuevo en un momento?"

#: What a specialist calls each way of paying. The values are the salon's three accounts, and
#: nothing outside them can be recorded — a payment nobody can attribute to an account is one the
#: register cannot be reconciled against.
#:
#: Bare "transferencia" is deliberately absent: it names no account, and guessing which bank
#: received the money is the same error as guessing a price.
_METHODS = {
    "efectivo": "cash",
    "cash": "cash",
    "cheles": "cash",
    "banreservas": "banreservas",
    "reservas": "banreservas",
    "banco de reservas": "banreservas",
    "bhd": "bhd",
    "banco bhd": "bhd",
}

#: Which of the two balances a payment pays down. Named rather than inferred: paying part of
#: what she owes has to say which part, or the two figures on her message stop meaning anything.
_OWES = {
    "productos": "purchase",
    "producto": "purchase",
    "consumo": "purchase",
    "prestamo": "loan",
    "prestamos": "loan",
    "dinero": "loan",
    "efectivo prestado": "loan",
}

#: What she means by "keep it" or "give it back", when the amount handed over is more than the
#: ticket. Empty falls through to the method — see `record_payment`.
_EXTRA = {
    "propina": "tip",
    "tip": "tip",
    "quedate con el vuelto": "tip",
    "vuelto": "change",
    "cambio": "change",
    "change": "change",
    "devolver": "change",
}


def _extra_for(extra: str, method: str) -> str | None:
    """What to do with money handed over above the ticket: "tip", "change", or None to ask.

    The default is the method's. Cash left her hand as notes and the difference is expected back;
    a transfer is an exact instruction nobody sends by accident, so the difference was meant.
    """
    said = fold(extra or "").strip()
    if not said:
        return "change" if method == "cash" else "tip"
    return _EXTRA.get(said)


def now() -> dt.datetime:
    """The salon's own clock, and the ONE place the turn path reads it.

    Public because `guards.py` judges the working day against it: a second reader would be a
    second thing a test has to hold still, and the one it missed is the one that fires.
    """
    return dt.datetime.now(_TZ)


def _today() -> dt.date:
    """The salon's own date. A night that runs past midnight still belongs to the day it began;
    rolling this on `hours.SCHEDULE` rather than on midnight is its own change."""
    return now().date()


def _owner_only(tool_context: Any) -> dict | None:
    """Defense in depth, exactly as `_unauthorized` is: the guard already refused."""
    if not session.is_owner(tool_context):
        return {"error": "owner_only", "message": OWNER_ONLY_MSG}
    return None


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

    Naming somebody is an owner's alone. Omitting one means her own work — which an owner who
    holds no disciplines cannot have, so she is asked whose it is rather than having a commission
    booked to a person who did nothing (§3).
    """
    named = (on_behalf_of or "").strip()
    if named and not session.is_owner(tool_context):
        # The guard refused this already; a tool reached another way must refuse too.
        return None, {"error": "not_an_owner", "message": NOT_AN_OWNER_MSG}

    if not named:
        if session.is_owner(tool_context) and not session.disciplines(tool_context):
            return None, {
                "error": "specialist_required",
                "message": NEED_SPECIALIST_MSG,
                "options": [p.name for p in staff.people(queries.working_specialists(conn))],
            }
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

    Shown exactly when it could be wrong: an owner naming the wrong specialist moves a commission,
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
            # A ticket named after the work prices the wrong client and prints the wrong receipt,
            # and nothing downstream can tell it from a real name — so it is refused here.
            sold = catalog.mentions(name, queries.service_catalog(conn)) or catalog.mentions(
                name, queries.product_catalog(conn)
            )
            if sold is not None:
                return {
                    "error": "name_is_the_work",
                    "message": NAME_IS_THE_WORK_MSG,
                    "matched": sold.name,
                }
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
            client = queries.client_for(conn, name)
            owing = queries.client_balance(conn, client["id"])
            sale = queries.create_sale(
                conn,
                person.specialist_id,
                name,
                client_id=client["id"],
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
        # Surfaced the moment she opens the ticket, which is the only time anybody is standing in
        # front of the client who owes it.
        **({"owed_from_before": money.rd(owing)} if owing > ZERO else {}),
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
            # HER areas, not the sender's: an owner recording a wax service for a nails
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
    extra: str = "",
    on_behalf_of: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Record one payment against the open ticket, and close it once the balance reaches zero.

    Call this once per payment method. A client paying part in cash and part by card is two
    calls, and the ticket stays open until the two add up to the total.

    Args:
        method: How they paid — efectivo, Banreservas or BHD, in the specialist's own words.
        amount: What was handed over, in numbers. More than the ticket is allowed; see `extra`.
        tip: The tip on this payment, in numbers. "0" when there was none.
        extra: ONLY when more was handed over than the ticket comes to, and only if she said
            which: "propina" to keep it, "vuelto" to give it back. Leave empty and cash is given
            back while a transfer is kept.
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
            # Only what the TICKET can absorb is a payment. Anything above it left the client's
            # hand but is not money the ticket received, so it never reaches `amount`.
            applied = min(paid, remaining)
            change = ZERO
            if (excess := paid - applied) > ZERO:
                choice = _extra_for(extra, canonical)
                if choice is None:
                    return {
                        "error": "bad_extra",
                        "message": BAD_EXTRA_MSG,
                        "extra": money.rd(excess),
                    }
                if choice == "tip":
                    gratuity += excess
                else:
                    change = excess

            queries.add_payment(conn, sale["id"], canonical, applied, gratuity, change)
            remaining -= applied
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


def close_ticket_with_debt(on_behalf_of: str = "", tool_context: ToolContext = None) -> dict:
    """Close the open ticket with the client still owing the rest, so the next one can be opened.

    Use this when she is leaving without paying it all. What is left is recorded against HER and
    shown the next time somebody opens a ticket in her name — the ticket cannot simply stay open,
    because one open ticket per specialist is what makes "my current ticket" mean anything.

    Args:
        on_behalf_of: ONLY for an owner, and then it is REQUIRED: the specialist whose work this
            is, in her own words. Anyone else leaves it empty.

    Returns:
        {"owes": str, "receipt": str} — send "receipt" as it came — or {"error", "message"}.
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
            lines = queries.sale_lines(conn, sale["id"])
            product_lines = queries.sale_product_lines(conn, sale["id"])
            if not lines and not product_lines:
                return {"error": "empty_ticket", "message": EMPTY_TICKET_MSG}
            owed = sale["services_total"] + sale["products_total"]
            # The same gate a payment passes: a balance is money, and it is only ever recorded
            # against a ticket she has actually been shown.
            if not session.was_quoted(tool_context, sale["sale_ref"], owed):
                return {"error": "not_quoted", "message": NOT_QUOTED_MSG}

            payments = queries.sale_payments(conn, sale["id"])
            outstanding = owed - sum((p.amount for p in payments), ZERO)
            if outstanding <= ZERO:
                return {"error": "nothing_outstanding", "message": NOTHING_OUTSTANDING_MSG}

            queries.record_client_debt(
                conn,
                sale["client_id"],
                sale["id"],
                outstanding,
                _today(),
                recorded_by=session.specialist_id(tool_context),
            )
            queries.close_sale(conn, sale["id"], _today(), status="partial")
            return {
                "owes": money.rd(outstanding),
                "receipt": receipts.render_receipt(
                    sale["client_name"],
                    lines,
                    sale["services_total"],
                    payments,
                    product_lines=product_lines,
                    products_total=sale["products_total"],
                    outstanding=outstanding,
                ),
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def settle_client_debt(
    client: str,
    amount: str,
    method: str,
    on_behalf_of: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Take money from a client against what she owed from a previous visit.

    Not a ticket and not a sale: it pays down a balance, so it earns no commission and appears on
    no receipt of work. Anyone may take it — the client is standing there.

    Args:
        client: Her name, as the specialist said it.
        amount: What she handed over, in numbers.
        method: efectivo, Banreservas or BHD, in the specialist's own words.
        on_behalf_of: ONLY for an owner, and then it is REQUIRED.

    Returns:
        {"paid": str, "still_owes": str} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    canonical = _METHODS.get(fold(method or "").strip())
    if canonical is None:
        return {"error": "bad_method", "message": BAD_METHOD_MSG}
    try:
        paid = money.money(amount)
    except ValueError:
        return {"error": "bad_amount", "message": BAD_AMOUNT_MSG}
    if paid <= ZERO:
        return {"error": "bad_amount", "message": BAD_AMOUNT_MSG}

    try:
        with queries.connect() as conn:
            _, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            found = queries.find_client(conn, client)
            if found is None:
                return {"error": "unknown_client", "message": NOTHING_OWED_MSG}
            balance = queries.client_balance(conn, found["id"])
            if balance <= ZERO:
                return {"error": "nothing_owed", "message": NOTHING_OWED_MSG}
            if paid > balance:
                # Refused rather than turned into a credit: the salon has no way to hold money
                # FOR a client, so an overpayment here would simply go missing.
                return {
                    "error": "more_than_owed",
                    "message": OVERPAID_DEBT_MSG.format(balance=money.rd(balance)),
                    "balance": money.rd(balance),
                }
            queries.record_client_payment(
                conn,
                found["id"],
                paid,
                _today(),
                recorded_by=session.specialist_id(tool_context),
                method=canonical,
            )
            return {
                "paid": money.rd(paid),
                "client": found["name"],
                "still_owes": money.rd(balance - paid),
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


def settle_debt(
    amount: str,
    owes: str,
    method: str,
    on_behalf_of: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Record a payment the specialist made against what she owes the salon.

    Part of it is ordinary rather than an exception — she may pay some now and carry the rest.

    Args:
        amount: What she paid, in numbers.
        owes: Which of the two she is paying: "productos" or "préstamo". She owes them
            separately and a payment has to name one.
        method: efectivo, Banreservas or BHD, in her own words.
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.

    Returns:
        {"paid": str, "balance": str} — what she just paid and what is left — or
        {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    kind = _OWES.get(fold(owes or "").strip())
    if kind is None:
        return {"error": "bad_owes", "message": BAD_OWES_MSG}
    canonical = _METHODS.get(fold(method or "").strip())
    if canonical is None:
        return {"error": "bad_method", "message": BAD_METHOD_MSG}
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
            owed = queries.debt_balances(conn, who)[kind]
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
                settles=kind,
                method=canonical,
                recorded_by=session.specialist_id(tool_context),
            )
            return {
                "paid": money.rd(paid),
                "owed_by": person.name,
                "balance": money.rd(queries.debt_balance(conn, who)),
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def record_loan(
    specialist: str,
    amount: str,
    method: str,
    tool_context: ToolContext = None,
) -> dict:
    """Record money taken out of the register and handed to a specialist. Owners only.

    A debit against her like a product she took, and kept apart from one: owing for a drink and
    owing cash are not the same thing to be told you owe.

    Args:
        specialist: Whose it is, in the owner's own words.
        amount: How much, in numbers.
        method: How it left — efectivo, Banreservas or BHD.

    Returns:
        {"lent": str, "owed_by": str, "loans": str} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if (refused := _owner_only(tool_context)) is not None:
        return refused
    canonical = _METHODS.get(fold(method or "").strip())
    if canonical is None:
        return {"error": "bad_method", "message": BAD_METHOD_MSG}
    try:
        lent = money.money(amount)
    except ValueError:
        return {"error": "bad_amount", "message": BAD_AMOUNT_MSG}
    if lent <= ZERO:
        return {"error": "bad_amount", "message": BAD_AMOUNT_MSG}
    try:
        with queries.connect() as conn:
            # Named rather than defaulted, exactly as work is: a loan booked to the wrong person
            # is money the salon will ask the wrong person for.
            person, refused = _acting(conn, tool_context, specialist)
            if refused is not None:
                return refused
            queries.record_loan(
                conn,
                person.specialist_id,
                lent,
                _today(),
                "Préstamo",
                recorded_by=session.specialist_id(tool_context),
                method=canonical,
            )
            return {
                "lent": money.rd(lent),
                "owed_by": person.name,
                "loans": money.rd(queries.debt_balances(conn, person.specialist_id)["loan"]),
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def close_register(
    cash: str,
    banreservas: str,
    bhd: str,
    tool_context: ToolContext = None,
) -> dict:
    """Record what each account actually holds at the end of the day, against what it should.
    Owners only.

    Counted and expected are both kept and the difference is not: recomputing the expectation
    later would absorb anything entered afterwards, which is the one thing this exists to catch.

    Args:
        cash: What is in the drawer, counted, in numbers.
        banreservas: What Banreservas received today, in numbers.
        bhd: What BHD received today, in numbers.

    Returns:
        {"closed": true, "counted": {...}, "expected": {...}, "variance": {...},
        "tips_to_pay": [...]} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if (refused := _owner_only(tool_context)) is not None:
        return refused
    counted: dict[str, Decimal] = {}
    for account, raw in (("cash", cash), ("banreservas", banreservas), ("bhd", bhd)):
        try:
            counted[account] = money.money(raw)
        except ValueError:
            return {"error": "bad_amount", "message": BAD_AMOUNT_MSG}
        if counted[account] < ZERO:
            return {"error": "bad_amount", "message": BAD_AMOUNT_MSG}

    day = _today()
    try:
        with queries.connect() as conn:
            if queries.register_close_for(conn, day) is not None:
                return {"error": "already_closed", "message": REGISTER_CLOSED_MSG}
            # A ticket still open is money not yet taken, so the count would be measured against
            # an expectation that is not finished. Named, so it can be acted on.
            if still_open := queries.open_tickets(conn):
                return {
                    "error": "tickets_open",
                    "message": TICKETS_STILL_OPEN_MSG,
                    "open": [f"{t['full_name']} — {t['client_name']}" for t in still_open],
                }
            expected = queries.expected_register(conn, day)
            queries.record_register_close(
                conn, day, session.specialist_id(tool_context), counted, expected
            )
            tips = queries.tips_owed(conn, day)
            return {
                "closed": True,
                "counted": {k: money.rd(v) for k, v in counted.items()},
                "expected": {k: money.rd(v) for k, v in expected.items()},
                "variance": {k: money.rd(counted[k] - expected[k]) for k in counted},
                # Hers in full, and paid out of the drawer that was just counted — so it is
                # reported beside the close rather than taken off it.
                "tips_to_pay": [f"{t['full_name']} — {money.rd(t['tips'])}" for t in tips],
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def salon_day(tool_context: ToolContext = None) -> dict:
    """What the whole salon did today, specialist by specialist. Owners only.

    Args:
        None.

    Returns:
        {"day": str, "by_specialist": [...], "services_total": str, "expected": {...}} or
        {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if (refused := _owner_only(tool_context)) is not None:
        return refused
    day = _today()
    try:
        with queries.connect() as conn:
            rows = []
            total = ZERO
            for who in queries.working_specialists(conn):
                figures = queries.day_totals(conn, who["id"], day)
                if figures["services_total"] <= ZERO and figures["tips"] <= ZERO:
                    continue
                total += figures["services_total"]
                rows.append(
                    f"{who['full_name']} — {money.rd(figures['services_total'])} "
                    f"(comisión {
                        money.rd(money.commission(figures['services_total'], config.COMMISSION_PCT))
                    }, propinas {money.rd(figures['tips'])})"
                )
            return {
                "day": receipts.spanish_date(day),
                "by_specialist": rows,
                "services_total": money.rd(total),
                "expected": {
                    k: money.rd(v) for k, v in queries.expected_register(conn, day).items()
                },
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
            totals = day_figures(conn, person.specialist_id, day)
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)
    return {"summary": summary_text(person.name, day, totals)}


def day_figures(conn, specialist_id: int, day: dt.date) -> dict:
    """One day's totals, plus what has accrued toward the next pay-day.

    One function rather than two callers assembling the same dict: `my_day` and the end-of-day
    job must not be able to disagree about a day, and the pay-period half is the easiest half to
    assemble differently.
    """
    start, end = pay.period_for(day)
    accrued = queries.period_services(conn, specialist_id, start, end)
    return {
        **queries.day_totals(conn, specialist_id, day),
        "period_commission": money.commission(accrued, config.COMMISSION_PCT),
        "payday": pay.payday_for(end),
    }


def summary_text(full_name: str, day: dt.date, totals: dict) -> str:
    """One day's figures as the specialist reads them.

    Takes the whole `day_totals` row rather than six positional amounts: the two callers must not
    be able to disagree, and six figures in an order is exactly how they would.

    Here rather than in `receipts` because the commission rate and the pay calendar are this
    application's, and `receipts` renders what it is handed.
    """
    services_total = totals["services_total"]
    return receipts.render_day(
        full_name.split()[0] if full_name else "",
        day,
        services_total=services_total,
        commission_pct=config.COMMISSION_PCT,
        commission=money.commission(services_total, config.COMMISSION_PCT),
        tips=totals["tips"],
        products_total=totals["products_total"],
        owed_products=totals["owed_products"],
        owed_loans=totals["owed_loans"],
        period_commission=totals.get("period_commission", ZERO),
        payday=totals.get("payday"),
    )
