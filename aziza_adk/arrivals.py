"""Who a specialist may take next, decided without a database and without a clock.

Stdlib only, and the line arrives as an argument — so the two rules the salon actually runs on are
values a test asserts rather than a driver it needs, the way `clients.py` makes naming a client
assertable. docs/PROJECT_DEFINITION.md §12.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Waiting:
    """One arrival in the salon's line, and everything an order turns on."""

    arrival_id: int
    client_name: str
    arrived_at: dt.datetime
    #: Every discipline she is still waiting on.
    waiting_for: frozenset[str]
    #: The discipline somebody is attending her in, or None. WHY she can be passed over, and the
    #: only thing that ever takes her out of a line she is in.
    serving: str | None = None


def line(rows: Iterable[dict]) -> tuple[Waiting, ...]:
    """The salon's line as `queries.line_today` returns it, one entry per arrival.

    A client waiting for both nails and wax is one woman standing there, not two.
    """
    return tuple(
        Waiting(
            arrival_id=row["id"],
            client_name=row["client_name"],
            arrived_at=row["arrived_at"],
            waiting_for=frozenset(row["waiting_for"] or ()),
            serving=row["serving"],
        )
        for row in rows
    )


def waiting_in(found: Sequence[Waiting], discipline: str) -> tuple[Waiting, ...]:
    """Everybody a specialist in `discipline` may take, in the order she must take them.

    Somebody already with a specialist is ABSENT from this rather than behind it. Demoting her
    instead would spend the place her arrival gave her, which is the one thing §12 forbids.
    """
    return tuple(
        sorted(
            (one for one in found if discipline in one.waiting_for and one.serving is None),
            # The arrival breaks a tie: two clients who arrived in the same second must still
            # order the same way on every read, or the line changes under a specialist between
            # two questions about it.
            key=lambda one: (one.arrived_at, one.arrival_id),
        )
    )


def next_up(found: Sequence[Waiting], discipline: str) -> Waiting | None:
    """Who a specialist in `discipline` takes now, or None when nobody is free to be taken.

    The head of `waiting_in` rather than its own scan, so the two cannot disagree about who is
    first.
    """
    found_here = waiting_in(found, discipline)
    return found_here[0] if found_here else None


def position(found: Sequence[Waiting], discipline: str, arrival_id: int) -> int | None:
    """Her place in one line, counting from one, or None when she is not in it.

    None covers both "never joined" and "somebody has her right now": there is no honest number
    for a woman who is not waiting, and one given anyway is a number she would stand and wait on.
    """
    for index, one in enumerate(waiting_in(found, discipline), start=1):
        if one.arrival_id == arrival_id:
            return index
    return None
