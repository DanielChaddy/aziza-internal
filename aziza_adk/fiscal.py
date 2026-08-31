"""Dominican fiscal shapes: what an invoice must look like to reach a 606.

No database, no model and no clock — the moment a date is judged against is a parameter, as in
`hours.py`. docs/PROJECT_DEFINITION.md §15 owns the reasoning, including why these shapes live
here rather than beside `conversation_core.identity`, and what in them is not yet verified.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from conversation_core import identity

from aziza_adk.money import ZERO

#: A company's tax id. A person's is `identity.DIGITS`, which is the cédula the salon already
#: knows how to read — so only this length is new.
RNC_DIGITS = 9

#: What the 606 calls each, derived from the digit count and therefore never asked about (§15).
TIPO_ID_RNC = "1"
TIPO_ID_CEDULA = "2"

#: The national rate, and NOT `money.py`'s: that module holds what is the SALON's — its commission
#: rate and when it is taken. Two rates in one module is how a commission ends up taxed at 18%.
ITBIS_RATE = Decimal("0.18")

#: More than an ordinary day's takings, which is what makes it worth a second look rather than a
#: refusal: a salon really does buy a chair, and a ceiling that refused one would be raised until
#: it refused nothing (§15).
LARGE_EXPENSE_THRESHOLD = Decimal("25000.00")

#: A 606 is a monthly filing, so an invoice older than this cannot go on any period still open to
#: her. Fiscal rather than a matter of taste.
MAX_INVOICE_AGE_DAYS = 365

#: `Tipo de Bienes y Servicios Comprados`. The Spanish is what an owner reads and what DGII
#: publishes, so it is product data rather than prose (agent-platform CLAUDE.md).
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("01", "Gastos de personal"),
    ("02", "Gastos por trabajos, suministros y servicios"),
    ("03", "Arrendamientos"),
    ("04", "Gastos de activos fijos"),
    ("05", "Gastos de representación"),
    ("06", "Otras deducciones admitidas"),
    ("07", "Gastos financieros"),
    ("08", "Gastos extraordinarios"),
    ("09", "Compras y gastos que formarán parte del costo de venta"),
    ("10", "Adquisiciones de activos"),
    ("11", "Gastos de seguros"),
)

#: Which `Forma de Pago` each of the salon's accounts becomes. LOSSY, and deliberately stored on
#: the row rather than derived at render time: a bank name cannot say whether the money moved as a
#: transfer or on a card, and the 606 distinguishes them (§15).
FORMA_PAGO = {"cash": "01", "banreservas": "02", "bhd": "02"}

#: (prefix, digits after the two-digit type). The SHAPE is checked and the type code is not: the
#: published list of type codes is not verified here, and a refusal built on a guessed list would
#: refuse real invoices — §15.
NCF_SHAPES = (("B", 8), ("E", 10))

#: A comprobante that gives no ITBIS credit. An owner will not know that, so it is worth saying.
CONSUMER_NCF_TYPES = frozenset({"02", "32"})


@dataclass(frozen=True)
class Problem:
    """One thing wrong with an invoice. `blocking` is what separates a refusal from a notice.

    Returned as DATA rather than raised or rendered, so the tool body is a translation layer and
    every rule is asserted from values alone — `tests/test_fiscal.py`.
    """

    code: str
    blocking: bool


@dataclass(frozen=True)
class Invoice:
    """What was read off one photograph. Amounts are `Decimal`; `Monto Facturado` is absent
    because the 606 derives it, so there is no field in which a misread could arrive."""

    supplier: str = ""
    rnc: str = ""
    ncf: str = ""
    invoice_date: dt.date | None = None
    bienes: Decimal = ZERO
    servicios: Decimal = ZERO
    itbis: Decimal = ZERO
    isc: Decimal = ZERO
    otros: Decimal = ZERO
    propina_legal: Decimal = ZERO
    total_paid: Decimal = ZERO

    @property
    def monto_facturado(self) -> Decimal:
        """`Bienes + Servicios`, which is DGII's own definition of the column."""
        return self.bienes + self.servicios

    @property
    def adds_up(self) -> Decimal:
        """What the parts come to, against which `total_paid` is reconciled."""
        return self.monto_facturado + self.itbis + self.isc + self.otros + self.propina_legal


def digits(said: str) -> str:
    return identity.digits_only(said or "")


def rnc(said: str) -> tuple[str, str] | None:
    """The supplier's id and which kind it is, or None when it is neither length.

    Refused rather than repaired, exactly as a client's telephone is (§3): a digit short is a typo,
    and a padded one identifies somebody else. "" is not an error — an informal supplier has none.
    """
    found = digits(said)
    if len(found) == RNC_DIGITS:
        return found, TIPO_ID_RNC
    if len(found) == identity.DIGITS:
        return found, TIPO_ID_CEDULA
    return None


def ncf(said: str) -> str | None:
    """The comprobante as the 606 wants it, or None when it is not one of the shapes."""
    seen = "".join((said or "").split()).upper()
    for prefix, tail in NCF_SHAPES:
        if len(seen) == 1 + 2 + tail and seen.startswith(prefix) and seen[1:].isdigit():
            return seen
    return None


def ncf_type(value: str) -> str:
    return value[1:3] if len(value) > 2 else ""


def implied_itbis_rate(base: Decimal, itbis: Decimal) -> Decimal | None:
    """What rate this invoice actually charged, or None when there is no base to divide by."""
    if base <= ZERO:
        return None
    return itbis / base


def check(invoice: Invoice, *, today: dt.date) -> tuple[Problem, ...]:
    """Everything decidable about this invoice from its own values.

    `today` is a parameter for `hours.py`'s reason: "refused because the date is next week" is then
    a value a test asserts rather than a day it waits for.
    """
    found: list[Problem] = []

    if invoice.total_paid <= ZERO:
        found.append(Problem("bad_total", True))
    elif invoice.total_paid != invoice.adds_up:
        # Neither figure can be trusted over the other, so the refusal names both and she looks at
        # the paper. Deriving `total_paid` instead would let a misread ITBIS silently change what
        # comes off the register.
        found.append(Problem("total_mismatch", True))

    if invoice.rnc and rnc(invoice.rnc) is None:
        found.append(Problem("bad_rnc", True))
    if invoice.ncf and ncf(invoice.ncf) is None:
        found.append(Problem("bad_ncf", True))

    if invoice.invoice_date is None:
        found.append(Problem("bad_invoice_date", True))
    elif invoice.invoice_date > today:
        found.append(Problem("future_invoice_date", True))
    elif (today - invoice.invoice_date).days > MAX_INVOICE_AGE_DAYS:
        found.append(Problem("invoice_too_old", True))

    if not invoice.supplier.strip():
        found.append(Problem("no_supplier", True))

    rate = implied_itbis_rate(invoice.monto_facturado, invoice.itbis)
    if rate is not None and rate != ITBIS_RATE and invoice.itbis != ZERO:
        found.append(Problem("odd_itbis_rate", False))
    if invoice.total_paid >= LARGE_EXPENSE_THRESHOLD:
        found.append(Problem("large_amount", False))
    if invoice.ncf and ncf_type(invoice.ncf) in CONSUMER_NCF_TYPES:
        found.append(Problem("consumer_ncf", False))
    if not on_606(invoice):
        found.append(Problem("outside_606", False))

    return tuple(found)


def on_606(invoice: Invoice) -> bool:
    """Whether this invoice can be a line on a 606 at all.

    Both halves, because a line needs the supplier's id AND its comprobante. Money that moved is
    recorded either way — the register has to know about it (§15).
    """
    return bool(invoice.rnc and invoice.ncf)


def blocking(problems: tuple[Problem, ...]) -> Problem | None:
    """The first refusal among them, or None when every one is a notice."""
    return next((p for p in problems if p.blocking), None)


def notices(problems: tuple[Problem, ...]) -> tuple[Problem, ...]:
    return tuple(p for p in problems if not p.blocking)
