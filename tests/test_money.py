"""The arithmetic a commission is paid on. No model, no database, no network.

This is the file that matters most in the suite: every other number in this service is either
read out of a column or produced here, and a cent lost per sale is a discrepancy nobody can
reconstruct at the end of the month.
"""

from decimal import Decimal

import pytest

from aziza_adk.money import ZERO, commission, money, rd

# --- [1] An amount is held exactly ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1500", "1500.00"),
        ("1500.1", "1500.10"),
        ("1,500.10", "1500.10"),
        (" 800 ", "800.00"),
        (0, "0.00"),
        (Decimal("2.5"), "2.50"),
    ],
)
def test_an_amount_becomes_a_decimal_in_cents(raw, expected):
    assert money(raw) == Decimal(expected)


def test_a_float_does_not_bring_its_own_error():
    """Decimal(0.1) is the float's real value, which is not 0.1 — hence the str() first."""
    assert money(0.1) == Decimal("0.10")


def test_rounding_goes_half_up_the_way_a_person_checking_by_hand_expects():
    """Half-even is correct for statistics and wrong for a receipt."""
    assert money("1250.005") == Decimal("1250.01")
    assert money("1250.015") == Decimal("1250.02")


@pytest.mark.parametrize(
    "raw", ["", "  ", "mil quinientos", None, "abc", "1500pesos", "nan", "inf", "-inf"]
)
def test_anything_that_is_not_an_amount_is_refused(raw):
    """Returned to the caller as a refusal rather than a zero: a silent zero would write a sale
    for nothing and a commission to match."""
    with pytest.raises(ValueError):
        money(raw)


# --- [2] The commission -------------------------------------------------------------------


def test_the_commission_is_the_configured_share_of_the_services_subtotal():
    assert commission(Decimal("8400.00"), 40) == Decimal("3360.00")


def test_a_commission_is_rounded_to_cents_half_up():
    # 40% of 1234.57 is 493.828 — a third decimal that must not survive into a payment.
    assert commission(Decimal("1234.57"), 40) == Decimal("493.83")


def test_nothing_billed_is_nothing_earned():
    assert commission(ZERO, 40) == ZERO


def test_the_rate_is_a_parameter_rather_than_a_constant_in_the_arithmetic():
    """So a salon that renegotiates changes one value and not this function."""
    assert commission(Decimal("1000.00"), 50) == Decimal("500.00")
    assert commission(Decimal("1000.00"), 0) == ZERO


# --- [3] How money is written -------------------------------------------------------------


@pytest.mark.parametrize(
    "amount,written",
    [
        ("1500.00", "RD$1,500.00"),
        ("800.00", "RD$800.00"),
        ("0.00", "RD$0.00"),
        ("1234567.89", "RD$1,234,567.89"),
    ],
)
def test_an_amount_is_written_the_way_the_salon_writes_it(amount, written):
    assert rd(Decimal(amount)) == written


def test_cents_are_always_shown():
    """A total that sometimes has decimals and sometimes does not reads as two different numbers."""
    assert rd(money("1500")) == "RD$1,500.00"
