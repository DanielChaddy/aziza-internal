"""Which specialist a spoken name means, when an owner says whose work it was.

Stdlib plus the accent fold, and no database: the list arrives as an argument, so the refusal of
an unknown name and the ambiguity between two people who share one are both assertable without a
driver behind them — docs/PROJECT_DEFINITION.md §3.

**This is the one place a specialist is named rather than resolved from the sender.** Nothing here
decides whether the caller is allowed to do that; `guards.before_tool_guard` does, off a column.
What this does is make the naming DETERMINISTIC: two people called Yamilé come back as two
candidates and the admin says which, because a commission booked to the wrong person is money and
picking the first is how that happens quietly.

The resolver is `catalog.resolve`, unchanged and reused. A person is a row with a name and the
words someone calls it by, which is all that resolver ever reads.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Person:
    """One specialist whose work can be recorded, and what she is allowed to record."""

    specialist_id: int
    name: str
    disciplines: frozenset[str]
    #: What an owner calls her out loud. Never shown, only matched on.
    aliases: tuple[str, ...] = field(default_factory=tuple)


def people(rows: Iterable[dict]) -> tuple[Person, ...]:
    """The list a spoken name is matched against, built from `queries.working_specialists`.

    The first name goes in as an alias so "Yamilé" finds "Yamilé Reyes" — and so two specialists
    who share it produce two candidates rather than a silent pick.
    """
    return tuple(
        Person(
            specialist_id=row["id"],
            name=row["full_name"],
            disciplines=frozenset(row["disciplines"] or ()),
            aliases=_aliases(row["full_name"]),
        )
        for row in rows
    )


def _aliases(full_name: str) -> tuple[str, ...]:
    parts = (full_name or "").split()
    return (parts[0],) if len(parts) > 1 else ()
