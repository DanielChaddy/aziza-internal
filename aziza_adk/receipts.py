"""What the specialist reads: the ticket, the receipt and the end-of-day line.

Stdlib only, and rendered HERE rather than composed by the model — docs/PROJECT_DEFINITION.md
§4. Every figure on these templates came out of a tool as a Decimal and is written by `money.rd`;
nothing is retyped, and nothing is added up in a sentence.

The Spanish below is what a specialist actually reads, so it is product data. The register is
docs/BRAND_VOICE.md and this file does not restate it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from aziza_adk.money import ZERO, rd

#: How a payment method is said. The keys are the canonical values a column and a tool argument
#: carry; only the values are Spanish.
METHOD_LABELS = {"cash": "Efectivo", "banreservas": "Banreservas", "bhd": "BHD"}

#: How the ticket names which price column it read. Shown only when the ticket holds a service
#: whose two prices differ — on an acrylic-only ticket the client makes no difference to any
#: figure, and a label there is noise.
GENDER_LABELS = {"female": "femenino", "male": "masculino"}

#: Said only when the name was not recognized and the female column was applied anyway
#: (aziza_adk/names.py). A matched name gets no notice: it is not an assumption.
GENDER_ASSUMED_TEXT = (
    "No reconocí el nombre, así que usé precio femenino. Si es hombre, dime y lo corrijo."
)

_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


@dataclass(frozen=True)
class Line:
    """One service or product on a ticket, at the price frozen when it was added."""

    name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class Payment:
    method: str
    amount: Decimal
    tip: Decimal = ZERO
    #: Handed back out of the drawer. Neither a payment nor a tip — `amount` is what the ticket
    #: received, and this is what left with the client.
    change_given: Decimal = ZERO


def spanish_date(day: dt.date) -> str:
    """ "martes 27 de agosto de 2026" — the salon's own way of writing a day."""
    return f"{_WEEKDAYS[day.weekday()]} {day.day} de {_MONTHS[day.month - 1]} de {day.year}"


def render_ticket(
    client_name: str,
    lines: Sequence[Line],
    total: Decimal,
    *,
    product_lines: Sequence[Line] = (),
    products_total: Decimal = ZERO,
    gender_label: str | None = None,
    assumed: bool = False,
    worked_by: str | None = None,
) -> str:
    """The open ticket: who it is for, what was done, what was sold, and what it comes to.

    `gender_label` is passed only when a service on this ticket is priced differently for
    different clients, and `assumed` only when nobody recognized the name — so the specialist is
    told what to check exactly when checking it could change a figure.

    `worked_by` is passed only when somebody OTHER than the person who did the work entered it,
    which is the admin case. Naming her is the same idea as naming the client: the one thing that
    could be wrong is put where the person who knows will read it before money moves.
    """
    rows = [f"Cuenta de {client_name}"]
    if worked_by:
        rows.append(f"Trabajo de: {worked_by}")
    if gender_label:
        rows.append(f"Precio: {gender_label}")
    rows += ["", *_line_rows(lines)]
    if product_lines:
        rows += ["", "Productos:", *_line_rows(product_lines)]
    rows += ["", f"Total: {rd(total + products_total)}"]
    if assumed and gender_label:
        rows += ["", GENDER_ASSUMED_TEXT]
    return "\n".join(rows)


def render_receipt(
    client_name: str,
    lines: Sequence[Line],
    total: Decimal,
    payments: Sequence[Payment],
    *,
    product_lines: Sequence[Line] = (),
    products_total: Decimal = ZERO,
    outstanding: Decimal = ZERO,
) -> str:
    """The closed sale.

    Three figures sit BESIDE the total rather than inside it, and each for its own reason. A tip
    is not the salon's money and is not what commission is taken on. Change was handed back out
    of the drawer. What is still owed never arrived at all.
    """
    tips = sum((p.tip for p in payments), ZERO)
    change = sum((p.change_given for p in payments), ZERO)
    rows = [
        f"Cobrado — {client_name}",
        "",
        *_line_rows(lines),
    ]
    if product_lines:
        rows += ["", "Productos:", *_line_rows(product_lines)]
    rows += [
        "",
        f"Total: {rd(total + products_total)}",
        "",
        "Pagos:",
        *(f"• {METHOD_LABELS.get(p.method, p.method)} — {rd(p.amount)}" for p in payments),
    ]
    if tips > ZERO:
        rows.append(f"Propina: {rd(tips)}")
    if change > ZERO:
        rows.append(f"Vuelto: {rd(change)}")
    if outstanding > ZERO:
        rows += ["", f"QUEDA DEBIENDO: {rd(outstanding)}"]
    return "\n".join(rows)


def render_day(
    specialist_name: str,
    day: dt.date,
    *,
    services_total: Decimal,
    commission_pct: int,
    commission: Decimal,
    tips: Decimal,
    products_total: Decimal = ZERO,
    owed_products: Decimal = ZERO,
    owed_loans: Decimal = ZERO,
    period_commission: Decimal = ZERO,
    payday: dt.date | None = None,
) -> str:
    """What the specialist made, and the arithmetic laid out so they can check it themselves.

    A figure that appears from nowhere is exactly the kind people dispute later, so the
    percentage is shown beside the amount it produced.

    THREE separations, and none of them is cosmetic. Tips are hers in full and are handed over
    today, so they stand beside the commission rather than inside it. Products are reported and
    left out of the commission line — she sold them and they pay her nothing. What she owes is
    shown whole and NOT subtracted, because the salon lets her settle it whenever she likes and
    taking it off would state a deduction nobody has made — split in two, because owing for a
    drink and owing cash do not feel the same to be told you owe.
    """
    rows = [
        f"Hola {specialist_name}, así cerró tu día del {spanish_date(day)}.",
        "",
        f"Servicios: {rd(services_total)}",
        f"Tu comisión ({commission_pct}%): {rd(commission)}",
        f"Propinas (te las entregamos hoy): {rd(tips)}",
    ]
    if products_total > ZERO:
        rows.append(f"Productos vendidos: {rd(products_total)} (no generan comisión)")
    rows += ["", f"Total para ti hoy: {rd(commission + tips)}"]

    if owed_products > ZERO or owed_loans > ZERO:
        rows += ["", "Lo que debes al salón:"]
        if owed_products > ZERO:
            rows.append(f"• Consumo: {rd(owed_products)}")
        if owed_loans > ZERO:
            rows.append(f"• Préstamos: {rd(owed_loans)}")
        rows.append(f"• Total: {rd(owed_products + owed_loans)}")

    if payday is not None:
        rows += [
            "",
            f"Acumulado para el pago del {spanish_date(payday)}: {rd(period_commission)}",
        ]
    return "\n".join(rows)


def _line_rows(lines: Sequence[Line]) -> list[str]:
    """One row per line. The unit price is shown only when the quantity is more than one —
    otherwise it is the same number twice, and a receipt that repeats itself gets skimmed."""
    rows = []
    for line in lines:
        if line.quantity > 1:
            rows.append(
                f"• {line.name} ×{line.quantity} — {rd(line.unit_price)} c/u "
                f"= {rd(line.line_total)}"
            )
        else:
            rows.append(f"• {line.name} — {rd(line.line_total)}")
    return rows


def render_register_prompt(
    day: dt.date,
    expected: dict[str, Decimal],
    tips_owed: Sequence[tuple[str, Decimal]] = (),
) -> str:
    """What an owner is asked at closing: count these, and hand these over.

    The expected figures are shown rather than withheld. A count made blind catches a miscount
    and nothing else; a count made against a figure is a question about the difference, which is
    the only thing worth asking.
    """
    rows = [
        f"Cierre del {spanish_date(day)}. Cuadra la caja cuando puedas.",
        "",
        "Según lo registrado hoy debería haber:",
        f"• Efectivo: {rd(expected['cash'])}",
        f"• Banreservas: {rd(expected['banreservas'])}",
        f"• BHD: {rd(expected['bhd'])}",
    ]
    if tips_owed:
        rows += ["", "Propinas por entregar:"]
        rows += [f"• {name} — {rd(amount)}" for name, amount in tips_owed]
    return "\n".join(rows)
