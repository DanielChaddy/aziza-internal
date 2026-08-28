"""Money: how it is held, how it is rounded, and how it is written.

Stdlib only, and that is load-bearing rather than tidy — a commission is what a person is paid,
so the arithmetic behind it is held by an assertion that reaches neither a model nor a database
or it is not held at all. See docs/PROJECT_DEFINITION.md §6.

Decimal throughout. A float cannot hold RD$1,500.10 exactly, and a cent lost per sale is a
discrepancy nobody can reconstruct at the end of the month.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def money(raw: object) -> Decimal:
    """`raw` as an amount, rounded to cents. Raises ValueError on anything that is not one.

    Rounds HALF UP rather than Decimal's default half-even: half-even is correct for statistics
    and wrong for a receipt, where a person expects 0.005 to go up and can check it by hand.
    """
    try:
        # str() first: Decimal(0.1) is the float's real value, which is not 0.1.
        value = Decimal(str(raw).strip().replace(",", ""))
    except (InvalidOperation, AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"not an amount: {raw!r}") from exc
    if not value.is_finite():
        raise ValueError(f"not an amount: {raw!r}")
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def commission(subtotal: Decimal, pct: int) -> Decimal:
    """The specialist's share of a services subtotal, in cents.

    Taken on services BEFORE any tip — docs/PROJECT_DEFINITION.md §7.
    """
    return (subtotal * Decimal(pct) / Decimal(100)).quantize(CENTS, rounding=ROUND_HALF_UP)


def rd(amount: Decimal) -> str:
    """An amount as the salon writes it: RD$1,500.00."""
    return f"RD${amount:,.2f}"
