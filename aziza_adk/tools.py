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
import re
from dataclasses import replace
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from conversation_core import dates, fold
from google.adk.tools import ToolContext

from aziza_adk import (
    arrivals,
    catalog,
    catalog_data,
    clients,
    config,
    fiscal,
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

#: The expense tools are absent from the set above ON PURPOSE: all of them are an owner's, and
#: an owner already records at any hour, so membership would be a set nothing could be refused by.
#: It is also right — she does the books after closing (docs/PROJECT_DEFINITION.md §15).
#:
#: What only an owner may do at all, at any hour. `guards.before_tool_guard` refuses these for
#: anyone else; the bodies re-check, as they do for `on_behalf_of`.
OWNER_TOOL_NAMES = frozenset(
    {
        "draft_expense",
        "register_expense",
        "amend_expense",
        "void_expense",
        "close_register",
        "record_loan",
        "salon_day",
        "client_history",
        "salon_clients",
        "lapsed_clients",
    }
)

#: Every tool needs a registered specialist behind it. `guards.before_tool_guard` refuses each of
#: them without one; the bodies re-check.
SPECIALIST_TOOL_NAMES = frozenset(
    {
        "draft_expense",
        "register_expense",
        "amend_expense",
        "void_expense",
        "start_ticket",
        "add_service",
        "set_client_gender",
        "sell_product",
        "show_ticket",
        "void_ticket",
        "record_payment",
        "close_ticket_with_debt",
        "settle_client_debt",
        "set_client_phone",
        "buy_product",
        "settle_debt",
        "my_day",
        "close_register",
        "record_loan",
        "salon_day",
        "client_history",
        "salon_clients",
        "lapsed_clients",
        "add_to_queue",
        "call_next",
        "who_is_waiting",
        "remove_from_queue",
    }
)

#: The writes. A ticket must have been quoted before any of the money ones runs.
WRITE_TOOL_NAMES = frozenset(
    {
        "draft_expense",
        "register_expense",
        "amend_expense",
        "void_expense",
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

#: How many visits a client's history lists. An owner between clients does not page, and the
#: render says how many older ones there are rather than truncating in silence.
MAX_HISTORY_VISITS = 6

#: How many names each ranking lists. The knob if an owner says the report is long: three makes
#: it fourteen lines.
TOP_N = 5
#: The window the salon-wide report reads, as (low, default, high). Clamped rather than refused:
#: it is a window, not money, and a bad value from the model should still produce a sane report —
#: the window it actually read goes on the message.
REPORT_DAYS = (7, 90, 365)
#: How long without a visit counts as having stopped. Roughly two missed acrylic fills: thirty
#: would flag half the book every week and the list would stop being read, ninety describes
#: somebody who has already gone rather than somebody who is going.
QUIET_DAYS = (14, 60, 365)
#: Two charged visits ever is what makes "used to come" mean anything. One is a walk-in who never
#: became a client, and reporting her as having stopped is noise.
LAPSED_MIN_VISITS = 2
#: Ordered most-recently-lapsed first, so the cap keeps the actionable half rather than a wall.
LAPSED_TOP = 10

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
CLIENT_OWES_NOTHING_MSG = "Esa clienta no debe nada."
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
NEED_CLIENT_PHONE_MSG = "No tengo a esa clienta registrada. ¿Cuál es su teléfono?"
AMBIGUOUS_CLIENT_MSG = "Hay más de una clienta con ese nombre. ¿Cuál es su teléfono?"
BAD_PHONE_MSG = "No entendí el teléfono. Dímelo con los diez dígitos, por ejemplo 8091234567."
ANOTHER_CLIENT_MSG = (
    "Ya tengo una clienta con ese nombre y otro teléfono. ¿Es otra clienta, o revisamos el número?"
)
UNKNOWN_CLIENT_MSG = "No tengo a esa clienta en el salón."
PHONE_TAKEN_MSG = "Ese teléfono ya es de otra clienta con ese mismo nombre. Revísamelo y lo cambio."
NO_CREDIT_WALK_IN_MSG = (
    "A esa clienta no le puedo fiar: no tengo su teléfono para buscarla en la próxima visita."
)

NEED_PHOTO_MSG = "Mándame la foto de la factura y la registro."
NO_DRAFT_MSG = "No tengo una factura pendiente. Mándame la foto otra vez."
EXPENSE_NOT_SHOWN_MSG = "Déjame mostrarte la factura antes de registrarla."
BAD_RNC_MSG = "Ese RNC no me cuadra. Tiene 9 dígitos, o 11 si es cédula."
BAD_NCF_MSG = "Ese NCF no tiene la forma correcta. Revísamelo en la factura."
BAD_INVOICE_DATE_MSG = "No entendí la fecha de la factura. Dímela otra vez."
FUTURE_INVOICE_DATE_MSG = "Esa fecha está en el futuro. Revísala en la factura."
INVOICE_TOO_OLD_MSG = "Esa factura tiene más de un año, así que ya no entra en ningún 606."
TOTAL_MISMATCH_MSG = (
    "Las partidas suman {parts} y el total pagado dice {total}. Revísame la factura."
)
NO_SUPPLIER_MSG = "¿De cuál suplidor es la factura?"
BAD_CATEGORY_MSG = "¿Qué tipo de gasto es? Dime materiales, alquiler, servicios o activos."
BAD_FIELD_MSG = "¿Cuál dato corrijo: el total, el ITBIS, el RNC, el NCF, la fecha o el suplidor?"
ALREADY_REGISTERED_MSG = "Esa factura ya está registrada."
DAY_ALREADY_CLOSED_MSG = "La caja de ese día ya está cerrada, así que no puedo moverla."
NOT_REGISTERED_EXPENSE_MSG = "No tengo esa factura registrada."
BAD_MONTH_MSG = "¿De cuál mes te saco el 606?"
NO_REPORT_LINK_MSG = "No puedo generar el enlace ahora mismo. Avísale a la administración."

QUEUE_EMPTY_MSG = "No hay nadie esperando por tu área ahora mismo."
WHICH_AREA_MSG = "¿De cuál de tus áreas la llamo?"
NOT_YOUR_AREA_MSG = "Esa área no es tuya, así que no puedo llamarte a nadie de esa fila."
NO_AREA_MSG = "No tienes un área asignada, así que no hay fila de dónde llamarte a nadie."
UNKNOWN_AREA_MSG = "No conozco esa área. El salón tiene uñas y depilación."
NEED_AREA_MSG = "¿Para qué área la pongo, uñas o depilación?"
ALREADY_SERVING_MSG = (
    "Todavía tienes a {client} contigo. Cóbrale o sácala de la fila, y llamo a la siguiente."
)
NOT_IN_LINE_MSG = "Esa clienta no está en la fila hoy."

#: What a specialist calls each of the salon's areas, folded. The values are `disciplines.code`.
#: A folded table rather than a resolve against the table itself: `disciplines` has no aliases
#: column, and "cera" is what she actually says. Bare "una" is absent — it is the article.
_AREAS = {
    "unas": "nails",
    "nails": "nails",
    "manicure": "nails",
    "manicura": "nails",
    "pedicure": "nails",
    "pedicura": "nails",
    "depilacion": "wax",
    "cera": "wax",
    "wax": "wax",
}

#: The Spanish name of each area, read from the dataset the seeder writes `disciplines` from, so
#: the options a specialist is offered cannot drift from the rows the line is grouped by.
_AREA_NAMES = {row["code"]: row["name"] for row in catalog_data.DISCIPLINES}

#: How she strings two areas together in one breath. "y" and "e" are words rather than
#: punctuation, so they match on a boundary or "depilacion" loses its middle.
_AREA_SEPARATORS = re.compile(r"\s*(?:,|/|\+|\by\b|\be\b)\s*")


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

#: What she calls each kind of gasto, folded. The values are `fiscal.CATEGORIES` codes. A folded
#: table rather than a resolve against the list itself: DGII's wording is not what she says out
#: loud, and "materiales" has to reach `02`.
_EXPENSE_CATEGORIES = {
    "materiales": "02",
    "material": "02",
    "insumos": "02",
    "suministros": "02",
    "servicios": "02",
    "trabajos": "02",
    "alquiler": "03",
    "renta": "03",
    "local": "03",
    "activo fijo": "04",
    "mantenimiento": "04",
    "reparacion": "04",
    "representacion": "05",
    "personal": "01",
    "nomina": "01",
    "financiero": "07",
    "banco": "07",
    "extraordinario": "08",
    "costo de venta": "09",
    "reventa": "09",
    "activos": "10",
    "equipo": "10",
    "mobiliario": "10",
    "seguro": "11",
    "seguros": "11",
}

#: Which column of a staged invoice she means. Named rather than inferred, and resolved against
#: this table rather than interpolated: the value reaches a SET clause.
_EXPENSE_FIELDS = {
    "total": "total_paid",
    "monto": "total_paid",
    "itbis": "itbis",
    "rnc": "rnc",
    "ncf": "ncf",
    "fecha": "invoice_date",
    "suplidor": "supplier",
    "proveedor": "supplier",
    "bienes": "bienes",
    "servicios": "servicios",
    "propina": "propina_legal",
    "tipo": "category",
    "categoria": "category",
}

#: What she means by an invoice nothing has paid yet. It moves no money, so no drawer is short of
#: it and the register never sees it (§15).
_ON_CREDIT = frozenset({"credito", "a credito", "fiado", "por pagar", "pendiente"})

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
    # Read on every render rather than carried from the open: she may settle it mid-visit, and
    # whoever charges is not always whoever opened the ticket (§7).
    owing = queries.client_balance(conn, sale["client_id"])
    walk_in = not queries.client_has_phone(conn, sale["client_id"])
    session.remember_quote(tool_context, sale["sale_ref"], total)
    return {
        "client_name": sale["client_name"],
        "total": money.rd(total),
        **({"owed_from_before": money.rd(owing)} if owing > ZERO else {}),
        "ticket": receipts.render_ticket(
            sale["client_name"],
            lines,
            sale["services_total"],
            product_lines=product_lines,
            products_total=sale["products_total"],
            gender_label=label,
            assumed=sale["gender_source"] == names.DEFAULTED,
            worked_by=worked_by,
            owed_from_before=owing,
            walk_in=walk_in,
        ),
    }


def _phone(said: str) -> tuple[str, dict | None]:
    """The number she gave as the salon stores it, or `(_, error)` for the caller to return.

    An empty answer is not an error — most turns carry no number at all. What is refused is
    something that was meant to be a number and is not one, and it is refused BEFORE a connection
    opens, so a typo can never fall through to matching on the name alone (§3).
    """
    said = (said or "").strip()
    if not said:
        return "", None
    key = clients.phone_key(said)
    if key is None:
        return "", {"error": "bad_phone", "message": BAD_PHONE_MSG}
    return key, None


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
    client_phone: str = "",
    client_gender: str = "",
    on_behalf_of: str = "",
    is_new_client: bool = False,
    walk_in: bool = False,
    tool_context: ToolContext = None,
) -> dict:
    """Open a new ticket for a client the specialist just worked on.

    Many services cost a different amount depending on the client, so the ticket carries which.
    Pass `client_gender` ONLY when the specialist actually said; do not infer it yourself and do
    not ask for it up front. Left empty, the client's name decides, and the ticket says so.

    The salon tells two clients apart by her phone number. Pass one ONLY when this tool has just
    asked for it; a client it already knows by name needs none.

    Args:
        client_name: The client's name, as the specialist said it.
        client_phone: Her number, ONLY when a previous call asked for it. Empty otherwise.
        client_gender: Only if she said so, in her own words. Empty otherwise.
        on_behalf_of: ONLY for the administration, and then it is REQUIRED: the specialist whose
            work this is, in her own words. An ordinary specialist leaves it empty.
        is_new_client: ONLY after "another_client_with_that_name" and the specialist saying in
            words that this is a different person. Never on your own.
        walk_in: ONLY after "client_phone_required" and the specialist saying the client would
            not give a number. She can then be charged but never fiada, and never found again.

    Returns:
        {"opened": true, "client_name": str, "priced_for": str}, or {"error", "message"}. Opening
        a second ticket while one is still open is an error, not a replacement.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    name = (client_name or "").strip()
    if not name:
        return {"error": "no_client_name", "message": NEED_CLIENT_NAME_MSG}

    key, refused = _phone(client_phone)
    if refused is not None:
        return refused

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
            roster = clients.roster(queries.clients_named(conn, name))
            found = clients.pick(roster, key)
            if found.candidates:
                return {"error": "ambiguous_client", "message": AMBIGUOUS_CLIENT_MSG}
            if found.match is not None:
                client_id = found.match.client_id
            elif not key:
                # Registering her under a name alone is what put two people on one balance. A
                # walk-in is the answer to that question, and it is a person's to give (§3).
                if not walk_in:
                    return {"error": "client_phone_required", "message": NEED_CLIENT_PHONE_MSG}
                client_id = queries.create_client(conn, name, None)["id"]
            elif roster and not is_new_client:
                return {
                    "error": "another_client_with_that_name",
                    "message": ANOTHER_CLIENT_MSG,
                }
            else:
                client_id = queries.create_client(conn, name, key)["id"]
            owing = queries.client_balance(conn, client_id)
            sale = queries.create_sale(
                conn,
                person.specialist_id,
                name,
                client_id=client_id,
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
            queries.lock_sale(conn, sale["id"])
            lines = queries.sale_lines(conn, sale["id"])
            product_lines = queries.sale_product_lines(conn, sale["id"])
            if not lines and not product_lines:
                return {"error": "empty_ticket", "message": EMPTY_TICKET_MSG}
            # What the client owes is the whole ticket. Commission is taken on the services half
            # alone, which is why the two totals are stored apart and only added up here (§7).
            owed = sale["services_total"] + sale["products_total"]
            if not session.was_quoted(tool_context, sale["sale_ref"], owed):
                return {"error": "not_quoted", "message": NOT_QUOTED_MSG}

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
            queries.lock_sale(conn, sale["id"])
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

            # Fiarle a quien el salón no puede volver a encontrar is a debt uncollectable by
            # construction: her row is never matched by name again (§3).
            if not queries.client_has_phone(conn, sale["client_id"]):
                return {"error": "no_credit_walk_in", "message": NO_CREDIT_WALK_IN_MSG}
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


def set_client_phone(
    phone: str,
    client: str = "",
    client_phone: str = "",
    on_behalf_of: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Change the number the salon has for a client, or give one to a client who arrived without.

    Naming nobody means the client on the open ticket, which is the only way to reach one who
    gave no number: she is not findable by name, deliberately (§3). Giving her one makes her
    findable from then on, and fiable.

    Args:
        phone: Her number now, in her own words.
        client: Her name. Leave empty for the client on the open ticket.
        client_phone: The number the salon has for her TODAY, only when two clients share her
            name and you were asked which.
        on_behalf_of: ONLY for an owner, and then it is REQUIRED.

    Returns:
        {"changed": true, "client": str} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    key, refused = _phone(phone)
    if refused is not None:
        return refused
    if not key:
        return {"error": "bad_phone", "message": BAD_PHONE_MSG}
    current, refused = _phone(client_phone)
    if refused is not None:
        return refused
    named = (client or "").strip()
    try:
        with queries.connect() as conn:
            person, refused = _acting(conn, tool_context, on_behalf_of)
            if refused is not None:
                return refused
            if named:
                picked = clients.pick(clients.roster(queries.clients_named(conn, named)), current)
                if picked.candidates:
                    return {"error": "ambiguous_client", "message": AMBIGUOUS_CLIENT_MSG}
                if picked.match is None:
                    return {"error": "unknown_client", "message": UNKNOWN_CLIENT_MSG}
                client_id, name = picked.match.client_id, picked.match.name
            else:
                sale = queries.open_sale(conn, person.specialist_id)
                if sale is None:
                    return {"error": "no_open_ticket", "message": NO_TICKET_MSG}
                client_id, name = sale["client_id"], sale["client_name"]
            # A number already on another row of that name is a MERGE, and two balances becoming
            # one is not a correction. Refused rather than resolved: nobody asked for it.
            if not queries.set_client_phone(conn, client_id, key):
                return {"error": "phone_taken", "message": PHONE_TAKEN_MSG}
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)
    return {"changed": True, "client": name}


def settle_client_debt(
    client: str,
    amount: str,
    method: str,
    client_phone: str = "",
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
        client_phone: Her number, ONLY when a previous call asked for it. Empty otherwise.
        on_behalf_of: ONLY for an owner, and then it is REQUIRED.

    Returns:
        {"paid": str, "still_owes": str} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    key, refused = _phone(client_phone)
    if refused is not None:
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
            picked = clients.pick(clients.roster(queries.clients_named(conn, client)), key)
            if picked.candidates:
                # NOT the one who happens to owe. It looks like the only reading that does
                # anything, and it credits money to a woman who may not have handed it over.
                return {"error": "ambiguous_client", "message": AMBIGUOUS_CLIENT_MSG}
            found = picked.match
            if found is None:
                return {"error": "unknown_client", "message": CLIENT_OWES_NOTHING_MSG}
            balance = queries.client_balance(conn, found.client_id)
            if balance <= ZERO:
                return {"error": "nothing_owed", "message": CLIENT_OWES_NOTHING_MSG}
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
                found.client_id,
                paid,
                _today(),
                recorded_by=session.specialist_id(tool_context),
                method=canonical,
            )
            return {
                "paid": money.rd(paid),
                "client": found.name,
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
            spent = queries.expenses_on(conn, day)
            return {
                "closed": True,
                "counted": {k: money.rd(v) for k, v in counted.items()},
                "expected": {k: money.rd(v) for k, v in expected.items()},
                "variance": {k: money.rd(counted[k] - expected[k]) for k in counted},
                # Hers in full, and paid out of the drawer that was just counted — so it is
                # reported beside the close rather than taken off it.
                "tips_to_pay": [f"{t['full_name']} — {money.rd(t['tips'])}" for t in tips],
                # Already OFF the expectation above. Named so a lower figure is explained rather
                # than appearing from nowhere (§7).
                "spent": [f"{e['supplier']} — {money.rd(e['total_paid'])}" for e in spent],
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


# --- what the salon buys ----------------------------------------------------


#: Which refusal each `fiscal.Problem` code becomes. A code with no sentence here is a KeyError in
#: `tests/test_tools.py` rather than a silence in a turn.
_EXPENSE_REFUSALS = {
    "bad_total": BAD_AMOUNT_MSG,
    "total_mismatch": TOTAL_MISMATCH_MSG,
    "bad_rnc": BAD_RNC_MSG,
    "bad_ncf": BAD_NCF_MSG,
    "bad_invoice_date": BAD_INVOICE_DATE_MSG,
    "future_invoice_date": FUTURE_INVOICE_DATE_MSG,
    "invoice_too_old": INVOICE_TOO_OLD_MSG,
    "no_supplier": NO_SUPPLIER_MSG,
}


def _amount(raw: str) -> Decimal | None:
    """One amount off a photograph, or None. "" is zero: most columns are simply absent."""
    if not str(raw or "").strip():
        return ZERO
    try:
        found = money.money(raw)
    except ValueError:
        return None
    return found if found >= ZERO else None


def _invoice_from(**args: str) -> tuple[fiscal.Invoice | None, dict | None]:
    """What the model read, as values — or the refusal for a figure that is not one."""
    amounts: dict[str, Decimal] = {}
    for name in ("bienes", "servicios", "itbis", "isc", "otros", "propina_legal", "total_paid"):
        found = _amount(args.get(name, ""))
        if found is None:
            return None, {"error": "bad_amount", "message": BAD_AMOUNT_MSG}
        amounts[name] = found
    return (
        fiscal.Invoice(
            supplier=str(args.get("supplier") or "").strip(),
            rnc=str(args.get("rnc") or "").strip(),
            ncf=str(args.get("ncf") or "").strip(),
            invoice_date=dates.parse_date(args.get("invoice_date")),
            **amounts,
        ),
        None,
    )


#: A mismatch is EXPECTED while she is correcting one field at a time: amending the ITBIS moves
#: what the parts come to, and the total she is about to correct has not moved yet. So it is a
#: notice on the block during an amendment and a refusal at the moment of writing (§15).
_MID_CORRECTION = frozenset({"total_mismatch"})


def _refused_invoice(
    invoice: fiscal.Invoice, problems, *, mid_correction: bool = False
) -> dict | None:
    """The first refusal among `problems`, worded. None when every one is a notice."""
    first = next(
        (p for p in problems if p.blocking and not (mid_correction and p.code in _MID_CORRECTION)),
        None,
    )
    if first is None:
        return None
    message = _EXPENSE_REFUSALS[first.code]
    if first.code == "total_mismatch":
        message = message.format(
            parts=money.rd(invoice.adds_up), total=money.rd(invoice.total_paid)
        )
    return {"error": first.code, "message": message}


def _shown(problems, *, mid_correction: bool = False) -> tuple:
    """Which problems the block says out loud: every notice, plus a refusal being tolerated."""
    return fiscal.notices(problems) + tuple(
        p for p in problems if p.blocking and mid_correction and p.code in _MID_CORRECTION
    )


def _draft_answer(row: dict, problems, tool_context: Any, *, mid_correction: bool = False) -> dict:
    """The rendered block, and the witness that she was shown it.

    Both happen HERE rather than in each caller, for `_ticket_answer`'s reason: a witness recorded
    without her actually being shown the figure would satisfy the gate on its own.
    """
    said = dict(fiscal.CATEGORIES).get(row["category"], row["category"])
    block = receipts.render_expense_draft(
        row["supplier"],
        row["total_paid"],
        ncf=row["ncf"],
        invoice_date=row["invoice_date"],
        category=said,
        bienes=row["bienes"],
        servicios=row["servicios"],
        itbis=row["itbis"],
        propina_legal=row["propina_legal"],
        notices=tuple(
            receipts.EXPENSE_NOTICE_TEXT[p.code]
            for p in _shown(problems, mid_correction=mid_correction)
        ),
    )
    session.remember_expense_shown(tool_context, row["expense_ref"], row["total_paid"])
    return {"confirmation": block, "on_606": row["on_606"]}


def draft_expense(
    supplier: str,
    total_paid: str,
    invoice_date: str,
    category: str = "",
    rnc: str = "",
    ncf: str = "",
    bienes: str = "",
    servicios: str = "",
    itbis: str = "",
    isc: str = "",
    otros: str = "",
    propina_legal: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Read a photographed supplier invoice back to the owner before anything is recorded.
    Owners only. Registers nothing.

    Needs a photo already in this conversation: there is no argument carrying one, so this cannot
    be called on a description of an invoice.

    Args:
        supplier: Who issued it, as printed.
        total_paid: What the salon actually paid, in numbers. Must equal the parts below.
        invoice_date: The date printed on it, as YYYY-MM-DD.
        category: What kind of gasto it is, in her words.
        rnc: The supplier's RNC or cédula. Empty when the invoice shows none.
        ncf: The comprobante fiscal. Empty when the invoice shows none.
        bienes: What was charged for goods, in numbers.
        servicios: What was charged for services, in numbers.
        itbis: The ITBIS charged, in numbers.
        isc: Impuesto selectivo al consumo, in numbers.
        otros: Other taxes or charges, in numbers.
        propina_legal: The legal 10% tip, in numbers.

    Returns:
        {"confirmation": str, "on_606": bool} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if (refused := _owner_only(tool_context)) is not None:
        return refused
    handle = session.photo(tool_context)
    if not handle:
        return {"error": "need_photo", "message": NEED_PHOTO_MSG}

    code = _EXPENSE_CATEGORIES.get(fold(category or "").strip())
    if code is None:
        return {"error": "bad_category", "message": BAD_CATEGORY_MSG}

    invoice, refused = _invoice_from(
        supplier=supplier,
        rnc=rnc,
        ncf=ncf,
        invoice_date=invoice_date,
        bienes=bienes,
        servicios=servicios,
        itbis=itbis,
        isc=isc,
        otros=otros,
        propina_legal=propina_legal,
        total_paid=total_paid,
    )
    if refused is not None:
        return refused
    problems = fiscal.check(invoice, today=_today())
    if (refused := _refused_invoice(invoice, problems)) is not None:
        return refused

    identified = fiscal.rnc(invoice.rnc) if invoice.rnc else None
    try:
        with queries.connect() as conn:
            row = queries.create_expense_draft(
                conn,
                session.specialist_id(tool_context),
                {
                    "supplier": invoice.supplier,
                    "rnc": identified[0] if identified else "",
                    "tipo_id": identified[1] if identified else "",
                    "ncf": fiscal.ncf(invoice.ncf) or "" if invoice.ncf else "",
                    "ncf_modificado": "",
                    "category": code,
                    "invoice_date": invoice.invoice_date,
                    "bienes": invoice.bienes,
                    "servicios": invoice.servicios,
                    "itbis": invoice.itbis,
                    "isc": invoice.isc,
                    "otros": invoice.otros,
                    "propina_legal": invoice.propina_legal,
                    "total_paid": invoice.total_paid,
                },
                photo_file_id=handle,
                on_606=fiscal.on_606(invoice),
            )
            return _draft_answer(row, problems, tool_context)
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def amend_expense(field: str, value: str, tool_context: ToolContext = None) -> dict:
    """Correct ONE field she says was read wrong, and show her the whole invoice again.
    Owners only.

    Re-showing is what re-arms the gate on the new total, so a figure amended after she confirmed
    the old one cannot be registered against that confirmation.

    Args:
        field: Which one — el total, el ITBIS, el RNC, el NCF, la fecha, el suplidor.
        value: What it should say.

    Returns:
        {"confirmation": str, "on_606": bool} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if (refused := _owner_only(tool_context)) is not None:
        return refused
    column = _EXPENSE_FIELDS.get(fold(field or "").strip())
    if column is None:
        return {"error": "bad_field", "message": BAD_FIELD_MSG}

    try:
        with queries.connect() as conn:
            row = queries.expense_draft(
                conn, session.specialist_id(tool_context), not_before=_draft_horizon()
            )
            if row is None:
                return {"error": "no_draft", "message": NO_DRAFT_MSG}

            corrected, refused = _corrected(row, column, value)
            if refused is not None:
                return refused
            problems = fiscal.check(corrected, today=_today())
            if (refused := _refused_invoice(corrected, problems, mid_correction=True)) is not None:
                return refused

            written = _column_value(column, corrected, value)
            row = queries.amend_expense_draft(
                conn, row["id"], column, written, on_606=fiscal.on_606(corrected)
            )
            return _draft_answer(row, problems, tool_context, mid_correction=True)
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def _staged(row: dict) -> fiscal.Invoice:
    """A staged row back as the value object the checks are written against."""
    return fiscal.Invoice(
        supplier=row["supplier"],
        rnc=row["rnc"],
        ncf=row["ncf"],
        invoice_date=row["invoice_date"],
        bienes=row["bienes"],
        servicios=row["servicios"],
        itbis=row["itbis"],
        isc=row["isc"],
        otros=row["otros"],
        propina_legal=row["propina_legal"],
        total_paid=row["total_paid"],
    )


def _corrected(row: dict, column: str, value: str) -> tuple[fiscal.Invoice, dict | None]:
    """The staged invoice with one column replaced, or the refusal for a value that is not one.

    `category` is not on the value object at all — it is a code the salon chose rather than
    anything printed on the paper, so nothing about it is checkable here.
    """
    staged = _staged(row)
    said = str(value or "").strip()
    if column == "category":
        if _EXPENSE_CATEGORIES.get(fold(said)) is None:
            return staged, {"error": "bad_category", "message": BAD_CATEGORY_MSG}
        return staged, None
    if column in ("supplier", "rnc", "ncf"):
        return replace(staged, **{column: said}), None
    if column == "invoice_date":
        return replace(staged, invoice_date=dates.parse_date(said)), None
    found = _amount(said)
    if found is None:
        return staged, {"error": "bad_amount", "message": BAD_AMOUNT_MSG}
    return replace(staged, **{column: found}), None


def _column_value(column: str, invoice: fiscal.Invoice, value: str):
    """What actually goes in the column, normalized the way the draft was."""
    if column == "invoice_date":
        return invoice.invoice_date
    if column == "rnc":
        return (fiscal.rnc(invoice.rnc) or ("", ""))[0]
    if column == "ncf":
        return fiscal.ncf(invoice.ncf) or "" if invoice.ncf else ""
    if column == "supplier":
        return invoice.supplier
    if column == "category":
        return _EXPENSE_CATEGORIES.get(fold(value or "").strip(), "")
    return getattr(invoice, column)


def _draft_horizon() -> dt.datetime:
    """The oldest a draft may be and still be the one she is answering about (§15)."""
    return now() - dt.timedelta(minutes=config.EXPENSE_DRAFT_TTL_MINUTES)


def register_expense(
    method: str,
    paid_on: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Record the invoice she was just shown, and take what it cost off the register.
    Owners only.

    Takes no amount: every figure comes off the row she was shown, so there is nothing here for a
    misreading to arrive in a second time.

    Args:
        method: How it was paid — efectivo, Banreservas, BHD, or a crédito when nothing has
            paid it yet.
        paid_on: The day the money left, as YYYY-MM-DD. Empty means today.

    Returns:
        {"registered": str, "on_606": bool} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if (refused := _owner_only(tool_context)) is not None:
        return refused

    said = fold(method or "").strip()
    on_credit = said in _ON_CREDIT
    canonical = None if on_credit else _METHODS.get(said)
    if canonical is None and not on_credit:
        return {"error": "bad_method", "message": BAD_METHOD_MSG}

    day = None
    if not on_credit:
        day = dates.parse_date(paid_on) if paid_on else _today()
        if day is None:
            return {"error": "bad_invoice_date", "message": BAD_INVOICE_DATE_MSG}

    try:
        with queries.connect() as conn:
            row = queries.expense_draft(
                conn, session.specialist_id(tool_context), not_before=_draft_horizon()
            )
            if row is None:
                return {"error": "no_draft", "message": NO_DRAFT_MSG}
            if not session.was_expense_shown(tool_context, row["expense_ref"], row["total_paid"]):
                return {"error": "not_shown", "message": EXPENSE_NOT_SHOWN_MSG}
            # Re-checked here rather than trusted from the draft: an amendment is allowed to leave
            # the parts and the total momentarily inconsistent, and this is where that stops.
            staged = _staged(row)
            if (
                refused := _refused_invoice(staged, fiscal.check(staged, today=_today()))
            ) is not None:
                return refused
            # A closed day's expectation is a frozen snapshot on purpose, so nothing may reach
            # back and lower it — §7.
            if day is not None and queries.register_close_for(conn, day) is not None:
                return {"error": "day_already_closed", "message": DAY_ALREADY_CLOSED_MSG}

            written, reason = queries.register_expense(
                conn,
                row["id"],
                method=canonical,
                business_date=day,
                forma_pago=fiscal.FORMA_PAGO.get(canonical or "", "04"),
            )
            if reason:
                return {"error": reason, "message": ALREADY_REGISTERED_MSG}
            if written is None:
                return {"error": "no_draft", "message": NO_DRAFT_MSG}
            return {
                "registered": receipts.render_expense_registered(
                    written["supplier"],
                    written["total_paid"],
                    method=written["method"],
                    on_606=written["on_606"],
                ),
                "on_606": written["on_606"],
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def void_expense(expense_ref: str, tool_context: ToolContext = None) -> dict:
    """Take a registered invoice back off the salon's record, and off the register with it.
    Owners only.

    Args:
        expense_ref: Which one, as it came back from `register_expense`.

    Returns:
        {"voided": str} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if (refused := _owner_only(tool_context)) is not None:
        return refused
    try:
        with queries.connect() as conn:
            row = queries.registered_expense(conn, str(expense_ref or "").strip())
            if row is None:
                return {"error": "unknown_expense", "message": NOT_REGISTERED_EXPENSE_MSG}
            if row["business_date"] and queries.register_close_for(conn, row["business_date"]):
                return {"error": "day_already_closed", "message": DAY_ALREADY_CLOSED_MSG}
            written = queries.void_expense(conn, row["id"])
            if written is None:
                return {"error": "unknown_expense", "message": NOT_REGISTERED_EXPENSE_MSG}
            return {"voided": f"{written['supplier']} — {money.rd(written['total_paid'])}"}
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
                # Already OFF `expected`, and listed for the same reason it is on the close (§7).
                "spent": [
                    f"{e['supplier']} — {money.rd(e['total_paid'])}"
                    for e in queries.expenses_on(conn, day)
                ],
            }
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)


def client_history(client: str, client_phone: str = "", tool_context: ToolContext = None) -> dict:
    """Everything the salon has charged one client, and what she still owes. Owners only.

    Args:
        client: Her name, as the owner said it.
        client_phone: Her number, ONLY when a previous call asked for it. Empty otherwise.

    Returns:
        {"summary": str} — send it as it came — or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if (refused := _owner_only(tool_context)) is not None:
        return refused
    name = (client or "").strip()
    if not name:
        return {"error": "no_client_name", "message": NEED_CLIENT_NAME_MSG}
    key, refused = _phone(client_phone)
    if refused is not None:
        return refused
    try:
        with queries.connect() as conn:
            picked = clients.pick(clients.roster(queries.clients_named(conn, name)), key)
            if picked.candidates:
                return {"error": "ambiguous_client", "message": AMBIGUOUS_CLIENT_MSG}
            if (who := picked.match) is None:
                return {"error": "unknown_client", "message": UNKNOWN_CLIENT_MSG}
            totals = queries.client_totals(conn, who.client_id)
            visits = queries.client_visits(conn, who.client_id, MAX_HISTORY_VISITS)
            balance = queries.client_balance(conn, who.client_id)
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)
    return {
        "summary": receipts.render_client_history(
            who.name,
            [
                receipts.Visit(
                    day=row["business_date"],
                    items=row["items"],
                    total=row["total"],
                    specialist=row["specialist"],
                    left_owing=row["left_owing"],
                )
                for row in visits
            ],
            total_visits=totals["visits"],
            billed=totals["billed"],
            balance=balance,
            first_visit=totals["first_visit"],
            phone=clients.formatted(who.phone),
        )
    }


def _clamped(value: Any, bounds: tuple[int, int, int]) -> int:
    """`value` pulled into `(low, default, high)`. A window is not money: a nonsense one from the
    model should still answer, and the message says which window it read."""
    low, default, high = bounds
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def salon_clients(days: int = 90, tool_context: ToolContext = None) -> dict:
    """Who comes most, who spends most and what the salon does most, over a stretch of days.
    Owners only.

    "Spends" is what she was BILLED, not what she handed over: a client who left owing was still
    worth the work, and the commission was taken on it (§7).

    Args:
        days: How far back to look. Defaults to the last 90 days.

    Returns:
        {"summary": str} — send it as it came — or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if (refused := _owner_only(tool_context)) is not None:
        return refused
    window = _clamped(days, REPORT_DAYS)
    end = _today()
    start = end - dt.timedelta(days=window - 1)
    try:
        with queries.connect() as conn:
            activity = queries.client_activity(conn, start, end)
            sold = queries.top_services(conn, start, end, TOP_N)
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)
    by_visits = sorted(activity, key=lambda r: (-r["visits"], r["name"]))[:TOP_N]
    by_spend = sorted(activity, key=lambda r: (-r["spent"], r["name"]))[:TOP_N]
    return {
        "summary": receipts.render_salon_clients(
            start,
            end,
            most_visits=[(r["name"], r["visits"]) for r in by_visits],
            most_spent=[(r["name"], r["spent"]) for r in by_spend],
            most_sold=[(r["name"], r["times"], r["billed"]) for r in sold],
        )
    }


def lapsed_clients(quiet_days: int = 60, tool_context: ToolContext = None) -> dict:
    """Clients who used to come and no longer do, and balances nobody has moved in as long.
    Owners only.

    Args:
        quiet_days: How long without a visit counts as having stopped. Defaults to 60.

    Returns:
        {"summary": str} — send it as it came — or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    if (refused := _owner_only(tool_context)) is not None:
        return refused
    quiet = _clamped(quiet_days, QUIET_DAYS)
    cutoff = _today() - dt.timedelta(days=quiet)
    try:
        with queries.connect() as conn:
            gone = queries.lapsed_clients(conn, cutoff, LAPSED_MIN_VISITS, LAPSED_TOP)
            owing = queries.stale_balances(conn, cutoff, LAPSED_TOP)
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        return _failed(exc)
    return {
        "summary": receipts.render_lapsed_clients(
            quiet,
            lapsed=[
                (r["name"], clients.formatted(r["phone"] or ""), r["last_visit"], r["visits"])
                for r in gone
            ],
            owing=[
                (r["name"], clients.formatted(r["phone"] or ""), r["balance"], r["last_move"])
                for r in owing
            ],
        )
    }


def my_day(on_behalf_of: str = "", tool_context: ToolContext = None) -> dict:
    """What this specialist has made today so far, and what she owes the salon. An owner who
    names somebody reads the same day told about her instead.

    The same figures and the same wording the end-of-day message uses, so the two can never
    disagree about a day.

    Args:
        on_behalf_of: ONLY for the administration: the specialist this day belongs to, in her own
            words. REQUIRED of an owner who does no salon work, since she has no day of her own.
            An ordinary specialist leaves it empty.

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
    # Naming somebody makes this a report rather than her own day — §7.
    hers = person.specialist_id == session.specialist_id(tool_context)
    return {"summary": summary_text(person.name, day, totals, reader_is_her=hers)}


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


def summary_text(full_name: str, day: dt.date, totals: dict, *, reader_is_her: bool = True) -> str:
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
        reader_is_her=reader_is_her,
    )


# --- the line ---------------------------------------------------------------


def _area_for(said: str, person: staff.Person) -> tuple[str, dict | None]:
    """Which one of her areas she means, or `(_, error)` for the caller to return.

    Never a guess when she holds two and named none: a client taken out of the wrong line is a
    woman sent to the wrong chair. Checked against HER areas and not the sender's, exactly as the
    discipline on a service is (§3).
    """
    held = tuple(person.disciplines)
    if not held:
        return "", {"error": "no_area", "message": NO_AREA_MSG}
    wanted = fold(said or "").strip()
    if not wanted:
        if len(held) == 1:
            return held[0], None
        return "", {
            "error": "which_area",
            "message": WHICH_AREA_MSG,
            "options": [_AREA_NAMES.get(code, code) for code in held],
        }
    code = _AREAS.get(wanted)
    if code is None:
        return "", {"error": "unknown_area", "message": UNKNOWN_AREA_MSG}
    if code not in held:
        return "", {"error": "not_your_area", "message": NOT_YOUR_AREA_MSG}
    return code, None


def _areas_said(said: str) -> tuple[list[str], dict | None]:
    """Every area named in one breath, in the order she said them and without repeats."""
    parts = [part for part in _AREA_SEPARATORS.split(fold(said or "").strip()) if part]
    if not parts:
        return [], {"error": "no_area_named", "message": NEED_AREA_MSG}
    codes: list[str] = []
    for part in parts:
        code = _AREAS.get(part)
        if code is None:
            return [], {"error": "unknown_area", "message": UNKNOWN_AREA_MSG}
        if code not in codes:
            codes.append(code)
    return codes, None


def _client_in_line(conn, name: str, client_phone: str) -> tuple[int | None, dict | None]:
    """The client this name and number mean, registering her if the salon does not know her.

    No number is DEMANDED here, unlike on a ticket: nothing in the line carries money, so there
    is no balance for the pair to protect and she is standing there to be called by name (§3).
    """
    key, refused = _phone(client_phone)
    if refused is not None:
        return None, refused
    picked = clients.pick(clients.roster(queries.clients_named(conn, name)), key)
    if picked.candidates:
        return None, {"error": "ambiguous_client", "message": AMBIGUOUS_CLIENT_MSG}
    if picked.match is not None:
        return picked.match.client_id, None
    return queries.create_client(conn, name, key or None)["id"], None


def add_to_queue(
    client: str,
    areas: str = "",
    client_phone: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Put a client in the salon's line, for one area or for two.

    For a client who cannot put herself in it. The line is one line for the whole salon, in the
    order people arrived.

    Args:
        client: Her name, as the specialist said it.
        areas: Which areas she came for — "uñas", "depilación", or both in one breath.
        client_phone: Her number, ONLY when a previous call asked for it. Empty otherwise.

    Returns:
        {"queued": true, "client": str, "areas": [str]} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    codes, refused = _areas_said(areas)
    if refused is not None:
        return refused
    with queries.connect() as conn:
        client_id, refused = _client_in_line(conn, client, client_phone)
        if refused is not None:
            return refused
        queries.record_arrival(conn, client_id, _today(), codes)
    return {
        "queued": True,
        "client": client.strip(),
        "areas": [_AREA_NAMES.get(code, code) for code in codes],
    }


def call_next(
    area: str = "",
    on_behalf_of: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Call the next client waiting in the salon's line for this specialist's area.

    A client waiting for two areas keeps her place in both and is passed over only while somebody
    else has her. This does NOT open a ticket — the work is recorded afterwards, as it always is.

    Args:
        area: Which of her areas, in her own words. Leave empty when she holds only one.
        on_behalf_of: ONLY for an owner, and then it is REQUIRED: the specialist this is for, in
            her own words. An ordinary specialist leaves it empty.

    Returns:
        {"called": true, "client": str, "still_waiting": int}, {"called": false, "message": str}
        when nobody is free, or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    with queries.connect() as conn:
        person, refused = _acting(conn, tool_context, on_behalf_of)
        if refused is not None:
            return refused
        code, refused = _area_for(area, person)
        if refused is not None:
            return refused
        # Refused rather than closed for her: nothing puts a want back, so a model calling this
        # unprompted would otherwise mark a woman mid-service as finished.
        if (busy := queries.serving_now(conn, person.specialist_id)) is not None:
            return {
                "error": "already_serving",
                "message": ALREADY_SERVING_MSG.format(client=busy["client_name"]),
            }
        # Walked rather than picked once: a False means another specialist won the race on the
        # index between the read and the write, and the next client is the answer.
        for one in arrivals.waiting_in(arrivals.line(queries.line_today(conn, _today())), code):
            if queries.take_next(conn, one.arrival_id, code, person.specialist_id):
                still = arrivals.waiting_in(arrivals.line(queries.line_today(conn, _today())), code)
                return {"called": True, "client": one.client_name, "still_waiting": len(still)}
        return {"called": False, "message": QUEUE_EMPTY_MSG}


def who_is_waiting(tool_context: ToolContext = None) -> dict:
    """Who is in the salon's line right now, in the order they will be called.

    Every area rather than only hers: she is often the one who has to tell a client how long it
    will be.

    Returns:
        {"lines": [{"area": str, "waiting": [str]}], "being_attended": [str]}, or
        {"lines": [], "message": str} when the salon is empty.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    with queries.connect() as conn:
        found = arrivals.line(queries.line_today(conn, _today()))
    if not found:
        return {"lines": [], "message": QUEUE_EMPTY_MSG}
    return {
        # Names only. Her number tells two clients apart and is not a thing a specialist ever
        # reads (docs/BRAND_VOICE.md §7).
        "lines": [
            {"area": name, "waiting": [one.client_name for one in arrivals.waiting_in(found, code)]}
            for code, name in _AREA_NAMES.items()
        ],
        "being_attended": [one.client_name for one in found if one.serving is not None],
    }


def remove_from_queue(
    client: str,
    client_phone: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Take a client out of the salon's line: she left, or she was not there when she was called.

    Out of EVERY line she was in, because a client who is not here is not here for the other one
    either. Anyone may do it — whoever noticed is who is standing there.

    Args:
        client: Her name, as the specialist said it.
        client_phone: Her number, ONLY when a previous call asked for it. Empty otherwise.

    Returns:
        {"removed": true, "client": str} or {"error", "message"}.
    """
    if (refused := _unauthorized(tool_context)) is not None:
        return refused
    with queries.connect() as conn:
        key, refused = _phone(client_phone)
        if refused is not None:
            return refused
        picked = clients.pick(clients.roster(queries.clients_named(conn, client)), key)
        if picked.candidates:
            return {"error": "ambiguous_client", "message": AMBIGUOUS_CLIENT_MSG}
        if picked.match is None:
            return {"error": "not_in_line", "message": NOT_IN_LINE_MSG}
        if not queries.leave_line(conn, picked.match.client_id, _today()):
            return {"error": "not_in_line", "message": NOT_IN_LINE_MSG}
    return {"removed": True, "client": picked.match.name}
