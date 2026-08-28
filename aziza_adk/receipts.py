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
METHOD_LABELS = {"cash": "Efectivo", "card": "Tarjeta", "transfer": "Transferencia"}

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
    """One service on a ticket, at the price frozen when it was added."""

    name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class Payment:
    method: str
    amount: Decimal
    tip: Decimal = ZERO


def spanish_date(day: dt.date) -> str:
    """ "martes 27 de agosto de 2026" — the salon's own way of writing a day."""
    return f"{_WEEKDAYS[day.weekday()]} {day.day} de {_MONTHS[day.month - 1]} de {day.year}"


def render_ticket(client_name: str, lines: Sequence[Line], total: Decimal) -> str:
    """The open ticket: who it is for, what was done, and what it comes to."""
    return "\n".join(
        [f"Cuenta de {client_name}", "", *_line_rows(lines), "", f"Total: {rd(total)}"]
    )


def render_receipt(
    client_name: str, lines: Sequence[Line], total: Decimal, payments: Sequence[Payment]
) -> str:
    """The closed sale. The tip is its own line and is never folded into the total: it is not
    the salon's money and it is not part of what commission is taken on."""
    tips = sum((p.tip for p in payments), ZERO)
    rows = [
        f"Cobrado — {client_name}",
        "",
        *_line_rows(lines),
        "",
        f"Total: {rd(total)}",
        "",
        "Pagos:",
        *(f"• {METHOD_LABELS.get(p.method, p.method)} — {rd(p.amount)}" for p in payments),
    ]
    if tips > ZERO:
        rows.append(f"Propina: {rd(tips)}")
    return "\n".join(rows)


def render_day(
    specialist_name: str,
    day: dt.date,
    *,
    services_total: Decimal,
    commission_pct: int,
    commission: Decimal,
    tips: Decimal,
) -> str:
    """What the specialist made, and the arithmetic laid out so they can check it themselves.

    A figure that appears from nowhere is exactly the kind people dispute later, so the
    percentage is shown beside the amount it produced.
    """
    return "\n".join(
        [
            f"Hola {specialist_name}, así cerró tu día del {spanish_date(day)}.",
            "",
            f"Servicios: {rd(services_total)}",
            f"Tu comisión ({commission_pct}%): {rd(commission)}",
            f"Propinas: {rd(tips)}",
            "",
            f"Total para ti: {rd(commission + tips)}",
        ]
    )


def _line_rows(lines: Sequence[Line]) -> list[str]:
    """One row per service. The unit price is shown only when the quantity is more than one —
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
