"""The file DGII is sent, asserted byte for byte.

No database and no model. The column list itself is NOT verified against DGII's current
instructivo — docs/PROJECT_DEFINITION.md §15 says so, and these vectors hold what this repository
believes rather than what the norm guarantees.
"""

import datetime as dt
from decimal import Decimal

from aziza_adk import six_oh_six

AUGUST = dt.date(2026, 8, 1)
FILER = "131999888"


def _row(**over):
    base = {
        "rnc": "131246813",
        "tipo_id": "1",
        "category": "02",
        "ncf": "B0100000001",
        "ncf_modificado": "",
        "invoice_date": dt.date(2026, 8, 28),
        "business_date": dt.date(2026, 8, 28),
        "bienes": Decimal("1000.00"),
        "servicios": Decimal("0.00"),
        "itbis": Decimal("180.00"),
        "itbis_retenido": Decimal("0.00"),
        "itbis_proporcionalidad": Decimal("0.00"),
        "itbis_costo": Decimal("0.00"),
        "itbis_percibido": Decimal("0.00"),
        "isr_tipo_retencion": "",
        "isr_retencion": Decimal("0.00"),
        "isr_percibido": Decimal("0.00"),
        "isc": Decimal("0.00"),
        "otros": Decimal("0.00"),
        "propina_legal": Decimal("0.00"),
        "forma_pago": "01",
        "on_606": True,
    }
    base.update(over)
    return base


# --- [1] One invoice, one line -------------------------------------------------------------


def test_a_line_is_the_columns_in_order():
    assert six_oh_six.line(_row()) == (
        "131246813|1|02|B0100000001||20260828|20260828|"
        "0.00|1000.00|1000.00|180.00|0.00|0.00|0.00|180.00|0.00||0.00|0.00|0.00|0.00|0.00|01"
    )


def test_a_line_carries_exactly_twenty_three_fields():
    """The assertion that catches a column inserted in the MIDDLE, which produces a file DGII
    accepts and mis-reads — the failure that does not announce itself."""
    assert len(six_oh_six.line(_row()).split("|")) == six_oh_six.FIELDS == 23


def test_the_invoiced_amount_is_the_two_halves_added():
    line = six_oh_six.line(_row(bienes=Decimal("600.00"), servicios=Decimal("400.00")))
    assert line.split("|")[7:10] == ["400.00", "600.00", "1000.00"]


def test_nothing_is_written_the_way_a_person_reads_it():
    """Every other render in this repository writes RD$1,000.00 because somebody reads it. This
    one is read by a machine that would reject that — see the module docstring."""
    assert "RD$" not in six_oh_six.line(_row())
    assert "," not in six_oh_six.line(_row(bienes=Decimal("1500000.00")))


def test_the_itbis_to_advance_is_derived_and_not_a_stored_zero():
    """A zero here understates the credit the salon is owed, and that is money (§15)."""
    row = _row(itbis=Decimal("180.00"), itbis_retenido=Decimal("30.00"))
    assert six_oh_six.itbis_to_advance(row) == Decimal("150.00")
    assert six_oh_six.line(row).split("|")[14] == "150.00"


def test_an_invoice_nothing_has_paid_carries_no_payment_date():
    """Thirty-day terms: it belongs on the report and no money has moved (§15)."""
    assert six_oh_six.line(_row(business_date=None)).split("|")[6] == ""


# --- [2] The whole file --------------------------------------------------------------------


def test_the_header_names_the_filer_the_period_and_the_count():
    out = six_oh_six.render(FILER, AUGUST, [_row(), _row(ncf="B0100000002")])
    assert out.splitlines()[0] == "131999888|202608|2"


def test_a_row_outside_the_606_is_excluded_and_counted_rather_than_emitted():
    """A line missing its RNC is rejected, and a rejection is what a filing cannot afford. How
    many were left out is what stops her filing a report she thinks is complete (§15)."""
    rows = [_row(), _row(rnc="", ncf="", on_606=False)]
    out = six_oh_six.render(FILER, AUGUST, rows)
    assert out.splitlines()[0].endswith("|1")
    assert len(out.splitlines()) == 2
    assert six_oh_six.excluded(rows) == 1


def test_a_period_with_nothing_in_it_is_a_header_and_no_lines():
    assert six_oh_six.render(FILER, AUGUST, []) == "131999888|202608|0\n"


def test_the_count_in_the_header_equals_the_lines_under_it():
    """DGII validates the two against each other, so they cannot be produced separately."""
    out = six_oh_six.render(FILER, AUGUST, [_row(ncf=f"B010000000{n}") for n in range(1, 5)])
    lines = out.splitlines()
    assert lines[0].split("|")[2] == str(len(lines) - 1)


def test_the_file_ends_in_a_newline():
    assert six_oh_six.render(FILER, AUGUST, [_row()]).endswith("\n")
