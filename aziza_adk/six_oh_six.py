"""One month of purchases as the file DGII is sent: pipe-delimited, one line per invoice.

No database, no model and no clock. docs/PROJECT_DEFINITION.md §15 owns the column list, and owns
the warning that it is not verified against DGII's current instructivo.

NOTHING HERE USES `money.rd`. Every other rendered figure in this repository is written
"RD$1,500.00" because a person reads it; this file is read by a machine that would reject that.
For the same reason no constant here is named `*_TEXT`: `tests/test_voice.py` discovers strings by
that suffix and would hold a pipe character to the register a colleague is addressed in.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

SEPARATOR = "|"

#: How many fields a detail line carries. Asserted rather than assumed: a column inserted in the
#: middle produces a file DGII accepts and mis-reads, which is the failure that does not announce
#: itself.
FIELDS = 23


def _day(value: dt.date | None) -> str:
    return value.strftime("%Y%m%d") if value else ""


def _amount(value: Decimal | None) -> str:
    return f"{Decimal(value or 0):.2f}"


def period(month: dt.date) -> str:
    """The month as the header names it: AAAAMM."""
    return month.strftime("%Y%m")


def itbis_to_advance(row: Any) -> Decimal:
    """`ITBIS Facturado` less what was retained, apportioned or taken to cost.

    Derived rather than stored, so it cannot disagree with the columns it is made of — and NOT
    defaulted to zero, which would understate the credit the salon is owed (§15).
    """
    return (
        Decimal(row["itbis"])
        - Decimal(row["itbis_retenido"])
        - Decimal(row["itbis_proporcionalidad"])
        - Decimal(row["itbis_costo"])
    )


def line(row: Any) -> str:
    """One registered invoice as one detail line."""
    bienes = Decimal(row["bienes"])
    servicios = Decimal(row["servicios"])
    fields = (
        row["rnc"],
        row["tipo_id"],
        row["category"],
        row["ncf"],
        row["ncf_modificado"],
        _day(row["invoice_date"]),
        # The day the money left, which is this column and the register's both — one date rather
        # than two that could disagree (§15).
        _day(row["business_date"]),
        _amount(servicios),
        _amount(bienes),
        _amount(bienes + servicios),
        _amount(row["itbis"]),
        _amount(row["itbis_retenido"]),
        _amount(row["itbis_proporcionalidad"]),
        _amount(row["itbis_costo"]),
        _amount(itbis_to_advance(row)),
        _amount(row["itbis_percibido"]),
        row["isr_tipo_retencion"],
        _amount(row["isr_retencion"]),
        _amount(row["isr_percibido"]),
        _amount(row["isc"]),
        _amount(row["otros"]),
        _amount(row["propina_legal"]),
        row["forma_pago"],
    )
    return SEPARATOR.join(fields)


def render(filer_rnc: str, month: dt.date, rows: list[Any]) -> str:
    """The whole file: the header, then a line per invoice that can be one.

    Rows outside the 606 are EXCLUDED rather than emitted incomplete — a line missing its RNC is
    rejected, and a rejection is what a filing cannot afford. How many were left out is the
    caller's to say out loud (§15).
    """
    lines = [line(row) for row in rows if row["on_606"]]
    header = SEPARATOR.join((filer_rnc, period(month), str(len(lines))))
    return "\n".join([header, *lines]) + "\n"


def excluded(rows: list[Any]) -> int:
    return sum(1 for row in rows if not row["on_606"])
