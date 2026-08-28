"""Turning what a specialist said into something the salon actually sells.

Stdlib plus the accent fold, and no database: the catalog arrives as an argument. That is what
lets the refusal of an unknown service be asserted without a model or a driver behind it —
docs/PROJECT_DEFINITION.md §5.

**A price is never an argument and never a model output.** Resolution answers with the catalog
row, and the caller reads the price off it. That holds for WHICH price too: `price_for` takes the
client the ticket already names, so choosing the column is never the model's to do.

One resolver serves services and products. Matching reads only a name and its aliases, so the
two share it rather than drifting apart in two implementations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Generic, Protocol, TypeVar

from conversation_core import fold

#: The client a ticket is for. What it selects is a price column, never an amount.
Gender = str

FEMALE: Gender = "female"
MALE: Gender = "male"


class Sellable(Protocol):
    """What the resolver needs of a row: a name, and what a specialist calls it out loud."""

    name: str
    aliases: tuple[str, ...]


T = TypeVar("T", bound=Sellable)


@dataclass(frozen=True)
class Service:
    """One thing the salon does, at the two prices the salon charges for it.

    A price of None means the salon does not offer this to that client. It is not a zero and it is
    not a reason to read the other column — the caller refuses and says why.
    """

    service_ref: str
    name: str
    discipline: str
    price_female: Decimal | None
    price_male: Decimal | None
    #: What a specialist calls it out loud, in their own words. Never shown, only matched on.
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Product:
    """One thing the salon sells over the counter, at two prices for two different buyers.

    `price_specialist` is not a discount the client can be given: it applies when a specialist
    takes one for herself, which is a debit against her rather than a sale — §7.
    """

    product_ref: str
    name: str
    price_client: Decimal
    price_specialist: Decimal
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Resolution(Generic[T]):
    """What one spoken phrase resolved to.

    Exactly one of these is meaningful: `match` when the phrase named one row, `candidates` when
    it named several. Both empty means the salon does not sell it — which is a value the caller
    says out loud, not an error.
    """

    match: T | None = None
    candidates: tuple[T, ...] = ()


def price_for(service: Service, gender: Gender) -> Decimal | None:
    """What this service costs that client, or None when the salon does not offer it to them.

    Raises on an unrecognized client rather than falling through to the female column: the two
    differ by as much as RD$550, so a typo that defaulted would under-charge in silence.
    """
    if gender == MALE:
        return service.price_male
    if gender == FEMALE:
        return service.price_female
    raise ValueError(f"not a client the salon prices for: {gender!r}")


def resolve(spoken: str, catalog: Sequence[T]) -> Resolution[T]:
    """The row `spoken` names, or what it might have named.

    Three passes, narrowest first, and each stops the moment it finds ONE answer: the full name,
    then an alias, then containment either way. Ambiguity is returned rather than guessed at —
    picking the first of two rows with different prices is a wrong receipt, which is worse than
    one more question.
    """
    said = fold(spoken or "").strip()
    if not said:
        return Resolution()

    for candidates in (
        _by_name(said, catalog),
        _by_alias(said, catalog),
        _by_overlap(said, catalog),
    ):
        if len(candidates) == 1:
            return Resolution(match=candidates[0])
        if candidates:
            return Resolution(candidates=tuple(candidates))
    return Resolution()


def _by_name(said: str, catalog: Sequence[T]) -> list[T]:
    return [s for s in catalog if fold(s.name) == said]


def _by_alias(said: str, catalog: Sequence[T]) -> list[T]:
    return [s for s in catalog if any(fold(a) == said for a in s.aliases)]


def _by_overlap(said: str, catalog: Sequence[T]) -> list[T]:
    """Either direction: "piernas" finds "Piernas completas", and "le hice piernas" finds it too.

    Guarded at three characters, because a two-letter fragment matches most of a catalog and an
    ambiguity that wide is indistinguishable from no answer at all.

    THE TWO DIRECTIONS ARE NOT SYMMETRIC, and treating them as one is what makes "manicura + gel"
    resolve while bare "manicura" stays ambiguous across the three that begin with it. A term
    CONTAINED IN what she said was said in full, so the longest such term is the most specific and
    wins outright. A term she said only a FRAGMENT of is a guess, and every row sharing that
    fragment is equally a candidate.
    """
    if len(said) < 3:
        return []
    spoken = [(width, row) for row in catalog if (width := _widest(said, row, contained=True))]
    if spoken:
        best = max(width for width, _ in spoken)
        return [row for width, row in spoken if width == best]
    return [row for row in catalog if _widest(said, row, contained=False)]


def _widest(said: str, row: T, *, contained: bool) -> int:
    """The longest of this row's terms matching in the asked-for direction, or 0 for none."""
    widths = [
        len(term)
        for raw in (row.name, *row.aliases)
        if len(term := fold(raw)) >= 3 and (term in said if contained else said in term)
    ]
    return max(widths, default=0)


def names(catalog: Sequence[T]) -> tuple[str, ...]:
    """What exists, for a prompt block or a refusal to name. Nothing outside this is sold."""
    return tuple(s.name for s in catalog)
