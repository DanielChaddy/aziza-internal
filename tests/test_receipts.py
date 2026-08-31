"""The templates a specialist actually reads. No model composed any of this.

Every figure on them came out of a tool as a Decimal and is written by `money.rd`. What these
assert is that nothing is retyped, nothing is added up in a sentence, and the tip never lands
inside the total.
"""

import datetime as dt
from decimal import Decimal

import pytest

from aziza_adk.receipts import (
    GENDER_ASSUMED_TEXT,
    WALK_IN_TEXT,
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


def test_what_she_owed_before_is_beside_the_total_and_not_in_it():
    """It is not this sale's money — adding it would charge her twice for the same work once the
    balance is settled, and would take commission on a debt."""
    out = render_ticket("Carmen", [MANI], Decimal("800.00"), owed_from_before=Decimal("200.00"))
    assert "Total: RD$800.00" in out
    assert "DEUDA ANTERIOR: RD$200.00 (aparte de este total)" in out


def test_a_client_who_owes_nothing_gets_no_line_about_it():
    """A zero there reads as a debt of zero, which is a thing to ask about."""
    assert "DEUDA" not in render_ticket("Laura", [MANI], Decimal("800.00"))


def test_a_client_who_gave_no_number_is_marked_where_the_charge_is_read():
    """She is served like anybody else and cannot be fiada. Said at the close instead, the
    refusal would arrive with the client already walking out."""
    out = render_ticket("Laura", [MANI], Decimal("800.00"), walk_in=True)
    assert "Cuenta de Laura (de paso)" in out
    assert WALK_IN_TEXT in out
    assert "Total: RD$800.00" in out, "she is charged the same"


def test_a_client_the_salon_can_find_gets_no_such_notice():
    assert "de paso" not in render_ticket("Laura", [MANI], Decimal("800.00"))


# --- [2] The receipt ----------------------------------------------------------------------


def test_the_receipt_lists_every_payment_method_in_spanish():
    out = render_receipt(
        "Laura",
        [MANI, LEGS],
        TOTAL,
        [Payment("cash", Decimal("2000.00")), Payment("bhd", Decimal("1800.00"))],
    )
    assert "Efectivo — RD$2,000.00" in out
    assert "BHD — RD$1,800.00" in out


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
            Payment("banreservas", Decimal("400.00"), Decimal("50.00")),
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
    assert "Propinas (te las entregamos hoy): RD$650.00" in out
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
    assert "Total para ti hoy: RD$4,010.00" in out


def test_a_day_told_about_somebody_addresses_nobody_as_her():
    """An owner reading about her gets the same figures, and not one of them said to be the
    reader's own. In the second person this greets the owner by another woman's name."""
    out = render_day(
        "Zenaida",
        dt.date(2026, 8, 27),
        services_total=Decimal("8400.00"),
        commission_pct=40,
        commission=Decimal("3360.00"),
        tips=Decimal("650.00"),
        owed_products=Decimal("15.00"),
        reader_is_her=False,
    )
    assert "Así cerró el día de Zenaida, jueves 27 de agosto de 2026." in out
    assert "Comisión (40%): RD$3,360.00" in out
    assert "Propinas (se las entregamos hoy): RD$650.00" in out
    assert "Total para ella hoy: RD$4,010.00" in out
    assert "Lo que debe al salón:" in out
    for said_to_the_reader in ("Hola ", "tu día", "Tu comisión", "te las", "para ti", "debes"):
        assert said_to_the_reader not in out, said_to_the_reader


def test_a_day_with_no_tips_still_says_so():
    out = render_day(
        "Rosa",
        dt.date(2026, 8, 27),
        services_total=Decimal("1000.00"),
        commission_pct=40,
        commission=Decimal("400.00"),
        tips=Decimal("0.00"),
    )
    assert "Propinas (te las entregamos hoy): RD$0.00" in out
    assert "Total para ti hoy: RD$400.00" in out


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


# --- Which client, and only where it could change a figure ----------------------------------

_MANI = Line(
    name="Manicura + pintura normal",
    quantity=1,
    unit_price=Decimal("300.00"),
    line_total=Decimal("300.00"),
)
_AGUA = Line(name="Agua", quantity=1, unit_price=Decimal("25.00"), line_total=Decimal("25.00"))


def test_the_ticket_names_the_client_when_asked_to():
    out = render_ticket("Laura", [_MANI], Decimal("300.00"), gender_label="femenino")
    assert "Precio: femenino" in out


def test_a_matched_name_gets_no_notice():
    """It is not an assumption, so saying so would train her to skim past the ones that are."""
    out = render_ticket("Laura", [_MANI], Decimal("300.00"), gender_label="femenino")
    assert GENDER_ASSUMED_TEXT not in out


def test_a_defaulted_name_is_told_about():
    out = render_ticket("Ariel", [_MANI], Decimal("300.00"), gender_label="femenino", assumed=True)
    assert GENDER_ASSUMED_TEXT in out


def test_nothing_is_said_where_no_figure_could_change():
    """No label passed means no service on the ticket is priced per client."""
    out = render_ticket("Ariel", [_MANI], Decimal("300.00"), assumed=True)
    assert "Precio:" not in out
    assert GENDER_ASSUMED_TEXT not in out


# --- Products, and what she owes ------------------------------------------------------------


def test_a_product_is_listed_apart_and_counted_in_the_total():
    out = render_ticket(
        "Laura",
        [_MANI],
        Decimal("300.00"),
        product_lines=[_AGUA],
        products_total=Decimal("25.00"),
    )
    assert "Productos:" in out
    assert "Total: RD$325.00" in out


def test_a_receipt_carries_the_products_too():
    out = render_receipt(
        "Laura",
        [_MANI],
        Decimal("300.00"),
        [Payment(method="cash", amount=Decimal("325.00"))],
        product_lines=[_AGUA],
        products_total=Decimal("25.00"),
    )
    assert "Productos:" in out and "Total: RD$325.00" in out


def test_the_day_reports_products_without_commissioning_them():
    out = render_day(
        "Yamilé",
        dt.date(2026, 8, 28),
        services_total=Decimal("300.00"),
        commission_pct=40,
        commission=Decimal("120.00"),
        tips=Decimal("200.00"),
        products_total=Decimal("25.00"),
    )
    assert "Productos vendidos: RD$25.00 (no generan comisión)" in out
    assert "Tu comisión (40%): RD$120.00" in out
    assert "Total para ti hoy: RD$320.00" in out  # commission + tips, and nothing from the product


def test_what_she_owes_is_shown_and_not_subtracted():
    """The salon lets her settle whenever; taking it off today would state a deduction nobody
    has made."""
    out = render_day(
        "Yamilé",
        dt.date(2026, 8, 28),
        services_total=Decimal("300.00"),
        commission_pct=40,
        commission=Decimal("120.00"),
        tips=Decimal("0.00"),
        owed_products=Decimal("15.00"),
    )
    assert "• Consumo: RD$15.00" in out
    assert "Total para ti hoy: RD$120.00" in out


def test_a_clean_slate_says_nothing_about_debt():
    out = render_day(
        "Yamilé",
        dt.date(2026, 8, 28),
        services_total=Decimal("300.00"),
        commission_pct=40,
        commission=Decimal("120.00"),
        tips=Decimal("0.00"),
    )
    assert "debes" not in out
    assert "Productos" not in out


# --- [6] What she owes, and what is accruing --------------------------------------------------


def _day(**kwargs) -> str:
    base = {
        "specialist_name": "Yamilé",
        "day": dt.date(2026, 8, 27),
        "services_total": Decimal("800.00"),
        "commission_pct": 40,
        "commission": Decimal("320.00"),
        "tips": Decimal("50.00"),
    }
    return render_day(**{**base, **kwargs})


def test_the_two_debts_are_told_apart_and_still_add_up():
    """Owing for a drink and owing cash do not feel the same to be told you owe."""
    out = _day(owed_products=Decimal("15.00"), owed_loans=Decimal("500.00"))
    assert "• Consumo: RD$15.00" in out
    assert "• Préstamos: RD$500.00" in out
    assert "• Total: RD$515.00" in out


def test_a_debt_of_only_one_kind_does_not_name_the_other():
    """A zero beside a real figure reads as a second thing owed."""
    out = _day(owed_loans=Decimal("500.00"))
    assert "• Préstamos: RD$500.00" in out and "Consumo" not in out


def test_neither_debt_is_taken_off_what_she_made():
    """The salon lets her settle whenever she likes, so subtracting would state a deduction
    nobody has made."""
    out = _day(owed_products=Decimal("15.00"), owed_loans=Decimal("500.00"))
    assert "Total para ti hoy: RD$370.00" in out  # 320 commission + 50 tips, untouched


def test_the_accumulated_figure_names_the_day_it_is_paid():
    out = _day(period_commission=Decimal("2400.00"), payday=dt.date(2026, 8, 29))
    assert "Acumulado para el pago del sábado 29 de agosto de 2026: RD$2,400.00" in out


def test_tips_are_not_in_what_accumulates():
    """They are handed over the same evening, so there is nothing of them left to accumulate."""
    out = _day(
        tips=Decimal("900.00"), period_commission=Decimal("320.00"), payday=dt.date(2026, 8, 29)
    )
    assert "Acumulado para el pago del sábado 29 de agosto de 2026: RD$320.00" in out


def test_a_day_with_no_payday_named_says_nothing_about_one():
    assert "Acumulado" not in _day()
