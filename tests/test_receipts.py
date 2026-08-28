"""The templates a specialist actually reads. No model composed any of this.

Every figure on them came out of a tool as a Decimal and is written by `money.rd`. What these
assert is that nothing is retyped, nothing is added up in a sentence, and the tip never lands
inside the total.
"""

import datetime as dt
from decimal import Decimal

import pytest

from aziza_adk.receipts import (
    Line,
    Payment,
    render_day,
    render_receipt,
    render_ticket,
    spanish_date,
)

MANI = Line("Manicure clásico", 1, Decimal("800.00"), Decimal("800.00"))
LEGS = Line("Depilación de piernas", 2, Decimal("1500.00"), Decimal("3000.00"))
TOTAL = Decimal("3800.00")


# --- [1] The ticket -----------------------------------------------------------------------


def test_the_ticket_names_the_client():
    assert "Cuenta de Laura" in render_ticket("Laura", [MANI], Decimal("800.00"))


def test_every_service_is_listed_with_its_price():
    out = render_ticket("Laura", [MANI, LEGS], TOTAL)
    assert "Manicure clásico" in out and "RD$800.00" in out
    assert "Depilación de piernas" in out and "RD$3,000.00" in out


def test_the_total_is_shown():
    assert "Total: RD$3,800.00" in render_ticket("Laura", [MANI, LEGS], TOTAL)


def test_a_quantity_above_one_shows_the_unit_price_and_the_arithmetic():
    """A specialist should be able to check the multiplication; a line total that appears from
    nowhere is the kind of number people dispute later."""
    out = render_ticket("Laura", [LEGS], Decimal("3000.00"))
    assert "×2" in out and "RD$1,500.00 c/u" in out and "= RD$3,000.00" in out


def test_a_single_service_does_not_print_the_same_number_twice():
    out = render_ticket("Laura", [MANI], Decimal("800.00"))
    assert out.count("RD$800.00") == 2, "once on the line, once in the total"
    assert "c/u" not in out


def test_an_empty_ticket_still_renders_rather_than_raising():
    """A ticket with no services yet is a real state — the tool refuses the charge, not the
    rendering."""
    assert "Total: RD$0.00" in render_ticket("Laura", [], Decimal("0.00"))


# --- [2] The receipt ----------------------------------------------------------------------


def test_the_receipt_lists_every_payment_method_in_spanish():
    out = render_receipt(
        "Laura",
        [MANI, LEGS],
        TOTAL,
        [Payment("cash", Decimal("2000.00")), Payment("card", Decimal("1800.00"))],
    )
    assert "Efectivo — RD$2,000.00" in out
    assert "Tarjeta — RD$1,800.00" in out


def test_the_tip_is_its_own_line_and_never_inside_the_total():
    """THE property. Commission is taken on services alone; a tip folded into the total would be
    taxed at the commission rate."""
    out = render_receipt(
        "Laura", [MANI], Decimal("800.00"), [Payment("cash", Decimal("800.00"), Decimal("200.00"))]
    )
    assert "Total: RD$800.00" in out
    assert "Propina: RD$200.00" in out
    assert "RD$1,000.00" not in out


def test_tips_across_split_payments_are_added_up_once():
    out = render_receipt(
        "Laura",
        [MANI],
        Decimal("800.00"),
        [
            Payment("cash", Decimal("400.00"), Decimal("100.00")),
            Payment("card", Decimal("400.00"), Decimal("50.00")),
        ],
    )
    assert "Propina: RD$150.00" in out


def test_no_tip_means_no_tip_line():
    out = render_receipt("Laura", [MANI], Decimal("800.00"), [Payment("cash", Decimal("800.00"))])
    assert "Propina" not in out


def test_an_unknown_method_is_shown_rather_than_swallowed():
    """A column value nobody planned for still has to appear, or the receipt silently loses a
    payment that is really there."""
    assert "cheque" in render_receipt(
        "L", [MANI], Decimal("800.00"), [Payment("cheque", Decimal("800.00"))]
    )


# --- [3] The end-of-day line --------------------------------------------------------------


def test_the_day_shows_all_four_figures_and_the_rate_beside_the_commission():
    out = render_day(
        "Yamilé",
        dt.date(2026, 8, 27),
        services_total=Decimal("8400.00"),
        commission_pct=40,
        commission=Decimal("3360.00"),
        tips=Decimal("650.00"),
    )
    assert "Servicios: RD$8,400.00" in out
    assert "Tu comisión (40%): RD$3,360.00" in out
    assert "Propinas: RD$650.00" in out
    assert "jueves 27 de agosto de 2026" in out


def test_what_they_made_is_the_commission_plus_the_tips():
    """Tips are theirs in full — docs/PROJECT_DEFINITION.md §7."""
    out = render_day(
        "Yamilé",
        dt.date(2026, 8, 27),
        services_total=Decimal("8400.00"),
        commission_pct=40,
        commission=Decimal("3360.00"),
        tips=Decimal("650.00"),
    )
    assert "Total para ti: RD$4,010.00" in out


def test_a_day_with_no_tips_still_says_so():
    out = render_day(
        "Rosa",
        dt.date(2026, 8, 27),
        services_total=Decimal("1000.00"),
        commission_pct=40,
        commission=Decimal("400.00"),
        tips=Decimal("0.00"),
    )
    assert "Propinas: RD$0.00" in out and "Total para ti: RD$400.00" in out


@pytest.mark.parametrize(
    "day,written",
    [
        (dt.date(2026, 1, 5), "lunes 5 de enero de 2026"),
        (dt.date(2026, 12, 31), "jueves 31 de diciembre de 2026"),
        (dt.date(2026, 8, 30), "domingo 30 de agosto de 2026"),
    ],
)
def test_a_date_is_written_the_way_the_salon_writes_it(day, written):
    assert spanish_date(day) == written
