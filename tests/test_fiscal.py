"""The fiscal shapes, asserted from values alone.

No database, no model and no clock, which is what lets "refused because the date is next week" be
a value rather than an evening spent waiting — docs/PROJECT_DEFINITION.md §15.
"""

import datetime as dt
from decimal import Decimal

import pytest

from aziza_adk import fiscal

TODAY = dt.date(2026, 8, 31)


def _invoice(**over):
    """An invoice that passes every check, so each test breaks exactly one thing."""
    base = {
        "supplier": "Suplidora Nacional",
        "rnc": "131246813",
        "ncf": "B0100000001",
        "invoice_date": dt.date(2026, 8, 28),
        "bienes": Decimal("1000.00"),
        "servicios": Decimal("0.00"),
        "itbis": Decimal("180.00"),
        "total_paid": Decimal("1180.00"),
    }
    return fiscal.Invoice(**{**base, **over})


def _codes(invoice, today=TODAY):
    return [p.code for p in fiscal.check(invoice, today=today)]


def _blocking(invoice, today=TODAY):
    return [p.code for p in fiscal.check(invoice, today=today) if p.blocking]


# --- [1] An id is refused rather than repaired ---------------------------------------------


def test_nine_digits_is_a_company_and_eleven_is_a_person():
    """The 606 asks which kind, and the length already answers — so nothing asks her (§15)."""
    assert fiscal.rnc("131246813") == ("131246813", fiscal.TIPO_ID_RNC)
    assert fiscal.rnc("40212345678") == ("40212345678", fiscal.TIPO_ID_CEDULA)


def test_a_digit_short_is_refused_rather_than_padded():
    """Same rule as a client's telephone (§3): a digit short is a typo, and a padded one
    identifies somebody else entirely."""
    assert fiscal.rnc("13124681") is None
    assert fiscal.rnc("1312468134") is None


def test_punctuation_and_spaces_are_folded_away():
    """She reads it off paper, and the paper hyphenates it."""
    assert fiscal.rnc("1-31-24681-3")[0] == "131246813"


def test_nothing_is_not_an_error_because_an_informal_supplier_has_none():
    assert "bad_rnc" not in _codes(_invoice(rnc=""))


# --- [2] A comprobante is a shape ----------------------------------------------------------


@pytest.mark.parametrize("value", ["B0100000001", "E310000000001", "b0100000001"])
def test_every_live_shape_is_accepted(value):
    assert fiscal.ncf(value) == value.upper()


@pytest.mark.parametrize("value", ["B010012", "B01000000012", "X0100000001", "B01ABCDEFGH"])
def test_a_shape_the_norm_does_not_have_is_refused(value):
    """A malformed comprobante is a rejected 606 line discovered a month later, so it is refused
    at the photograph rather than at the filing."""
    assert fiscal.ncf(value) is None


def test_an_absent_comprobante_is_legal_and_puts_the_row_outside_the_606():
    """A colmado receipt has none, and the money still left the drawer (§15)."""
    invoice = _invoice(ncf="")
    assert "bad_ncf" not in _codes(invoice)
    assert fiscal.on_606(invoice) is False
    assert "outside_606" in _codes(invoice)


def test_a_consumidor_final_comprobante_earns_a_notice_rather_than_a_refusal():
    """It gives no ITBIS credit, and an owner has no reason to know that."""
    problems = fiscal.check(_invoice(ncf="B0200000001"), today=TODAY)
    consumer = next(p for p in problems if p.code == "consumer_ncf")
    assert consumer.blocking is False


# --- [3] The arithmetic that HOLDS ---------------------------------------------------------


def test_the_invoiced_amount_is_derived_and_is_never_a_field():
    """THE property this design rests on: `Monto Facturado` is DGII's own sum, so there is no
    argument in which a misread of it could arrive."""
    assert not hasattr(fiscal.Invoice(), "monto_facturado_field")
    assert _invoice().monto_facturado == Decimal("1000.00")


def test_a_total_that_does_not_add_up_is_refused():
    """Neither figure can be trusted over the other, so nothing is registered from either."""
    assert "total_mismatch" in _blocking(_invoice(total_paid=Decimal("1000.00")))


def test_the_legal_tip_is_part_of_what_she_paid_and_not_of_the_base():
    """A salon buys lunch. Omit the column and this check fails on every restaurant invoice."""
    invoice = _invoice(propina_legal=Decimal("100.00"), total_paid=Decimal("1280.00"))
    assert _blocking(invoice) == []
    assert invoice.monto_facturado == Decimal("1000.00")


def test_eighteen_percent_passes_in_silence():
    assert "odd_itbis_rate" not in _codes(_invoice())


def test_an_exempt_invoice_with_no_itbis_is_ordinary():
    """Zero is not an odd rate — plenty of what a salon buys is exempt."""
    invoice = _invoice(itbis=Decimal("0.00"), total_paid=Decimal("1000.00"))
    assert "odd_itbis_rate" not in _codes(invoice)


def test_a_rate_that_is_neither_eighteen_nor_zero_is_shown_rather_than_refused():
    """Partial exemptions and selective-consumption lines both break 18%, so a refusal here would
    refuse real invoices — `names.py`'s notice, applied to a rate (§15)."""
    invoice = _invoice(itbis=Decimal("90.00"), total_paid=Decimal("1090.00"))
    assert "odd_itbis_rate" in _codes(invoice)
    assert _blocking(invoice) == []


# --- [4] A date the salon could not have been handed ---------------------------------------


def test_a_date_in_the_future_is_refused():
    assert "future_invoice_date" in _blocking(_invoice(invoice_date=dt.date(2026, 9, 1)))


def test_a_date_that_was_never_read_is_refused_rather_than_guessed():
    assert "bad_invoice_date" in _blocking(_invoice(invoice_date=None))


def test_a_year_out_is_refused_because_that_period_can_no_longer_be_filed():
    assert "invoice_too_old" in _blocking(_invoice(invoice_date=dt.date(2025, 8, 1)))


def test_today_is_ordinary():
    assert _blocking(_invoice(invoice_date=TODAY)) == []


# --- [5] A figure implausible for a salon is shown, never refused --------------------------


def test_a_big_purchase_is_registered_because_a_salon_buys_chairs():
    invoice = _invoice(
        bienes=Decimal("180000.00"), itbis=Decimal("32400.00"), total_paid=Decimal("212400.00")
    )
    assert "large_amount" in _codes(invoice)
    assert _blocking(invoice) == []


def test_a_decimal_point_in_the_wrong_place_earns_the_notice():
    """The highest-cost misread there is: it lands in what the register should hold, and
    manufactures a variance nobody can explain (§7)."""
    invoice = _invoice(
        bienes=Decimal("150000.00"), itbis=Decimal("27000.00"), total_paid=Decimal("177000.00")
    )
    assert "large_amount" in _codes(invoice)


# --- [6] What the 606 takes from the salon rather than from the paper ----------------------


def test_the_category_list_is_the_606s_own():
    assert len(fiscal.CATEGORIES) == 11
    assert fiscal.CATEGORIES[0][0] == "01"
    assert [code for code, _ in fiscal.CATEGORIES] == sorted(c for c, _ in fiscal.CATEGORIES)


def test_the_way_she_paid_becomes_a_forma_de_pago():
    assert fiscal.FORMA_PAGO["cash"] == "01"
    assert set(fiscal.FORMA_PAGO) == {"cash", "banreservas", "bhd"}


def test_an_invoice_with_both_halves_can_be_a_line():
    assert fiscal.on_606(_invoice()) is True
    assert fiscal.on_606(_invoice(rnc="")) is False
    assert fiscal.on_606(_invoice(ncf="")) is False


def test_a_supplier_nobody_named_is_refused():
    """The one field she has to read to know the photograph was of an invoice at all (§15)."""
    assert "no_supplier" in _blocking(_invoice(supplier="  "))
