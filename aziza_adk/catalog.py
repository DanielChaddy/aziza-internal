"""Turning what a specialist said into a service the salon actually sells.

Stdlib plus the accent fold, and no database: the catalog arrives as an argument. That is what
lets the refusal of an unknown service be asserted without a model or a driver behind it —
docs/PROJECT_DEFINITION.md §5.

**A price is never an argument and never a model output.** Resolution answers with the catalog
row, and the caller reads the price off it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from conversation_core import fold


@dataclass(frozen=True)
class Service:
    """One thing the salon sells, at the price the salon charges for it."""

    service_ref: str
    name: str
    discipline: str
    price: Decimal
    #: What a specialist calls it out loud, in their own words. Never shown, only matched on.
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Resolution:
    """What one spoken phrase resolved to.

    Exactly one of these is meaningful: `match` when the phrase named one service, `candidates`
    when it named several. Both empty means the salon does not sell it — which is a value the
    caller says out loud, not an error.
    """

    match: Service | None = None
    candidates: tuple[Service, ...] = ()


def resolve(spoken: str, catalog: Sequence[Service]) -> Resolution:
    """The service `spoken` names, or what it might have named.

    Three passes, narrowest first, and each stops the moment it finds ONE answer: the full name,
    then an alias, then containment either way. Ambiguity is returned rather than guessed at —
    picking the first of two services with different prices is a wrong receipt, which is worse
    than one more question.
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


def _by_name(said: str, catalog: Sequence[Service]) -> list[Service]:
    return [s for s in catalog if fold(s.name) == said]


def _by_alias(said: str, catalog: Sequence[Service]) -> list[Service]:
    return [s for s in catalog if any(fold(a) == said for a in s.aliases)]


def _by_overlap(said: str, catalog: Sequence[Service]) -> list[Service]:
    """Either direction: "manicure" finds "Manicure clásico", and "hazme un manicure" finds it too.

    Guarded at three characters, because a two-letter fragment matches most of a catalog and an
    ambiguity that wide is indistinguishable from no answer at all.

    THE TWO DIRECTIONS ARE NOT SYMMETRIC, and treating them as one is what makes "un manicure en
    gel" come back ambiguous. A term CONTAINED IN what she said was said in full, so the longest
    such term is the most specific and wins outright. A term she said only a FRAGMENT of is a
    guess, and every service sharing that fragment is equally a candidate.
    """
    if len(said) < 3:
        return []
    spoken = [
        (width, service) for service in catalog if (width := _widest(said, service, contained=True))
    ]
    if spoken:
        best = max(width for width, _ in spoken)
        return [service for width, service in spoken if width == best]
    return [service for service in catalog if _widest(said, service, contained=False)]


def _widest(said: str, service: Service, *, contained: bool) -> int:
    """The longest of this service's terms matching in the asked-for direction, or 0 for none."""
    widths = [
        len(term)
        for raw in (service.name, *service.aliases)
        if len(term := fold(raw)) >= 3 and (term in said if contained else said in term)
    ]
    return max(widths, default=0)


def names(catalog: Sequence[Service]) -> tuple[str, ...]:
    """What exists, for a prompt block or a refusal to name. Nothing outside this is sold."""
    return tuple(s.name for s in catalog)
