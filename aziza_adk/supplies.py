"""What the salon has run out of, grouped without a database and without a clock.

Stdlib plus the accent fold, and the reports arrive as an argument — the same shape as
`arrivals.py` and for the same reason: which line two people saying "acetona" fall into is a value
a test asserts rather than a query it has to run. docs/PROJECT_DEFINITION.md §16.

The moment is a parameter as it is in `hours.py`, so "waiting five days" is a value rather than
five days spent waiting for it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from conversation_core import fold

# These reach a specialist with NO model in the path, so the register is fixed at the literal —
# docs/BRAND_VOICE.md.
WAITED_TODAY_TEXT = "hoy"
WAITED_YESTERDAY_TEXT = "ayer"
WAITED_DAYS_TEXT = "hace {days} días"


@dataclass(frozen=True)
class Supply:
    """One thing the salon buys for itself, as against the things it sells.

    No price and no discipline: a supply is matched on and never charged for, which is the whole
    of what `catalog.resolve` reads — so it resolves through the same function a service does.
    """

    supply_ref: str
    name: str
    #: What a specialist calls it out loud, in her own words. Never shown, only matched on.
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Report:
    """One time somebody said something is running out."""

    request_id: int
    #: Her own words, kept whether or not they resolved. For an unlisted supply it is the only
    #: name there is.
    said: str
    reported_by: str
    reported_at: dt.datetime
    note: str = ""
    has_photo: bool = False


@dataclass(frozen=True)
class Needed:
    """One thing to buy, however many people asked for it."""

    label: str
    #: False is a supply the salon has never listed. Said out loud rather than hidden: the label
    #: is then one specialist's words rather than a name the salon chose, and the difference is
    #: what tells an owner she is reading a guess (§16).
    listed: bool
    #: Oldest first, so the first of them is the one that has been waiting longest.
    reports: tuple[Report, ...]

    @property
    def since(self) -> dt.datetime:
        """When the FIRST person asked. What the list is ordered by, because a shortage nobody
        has bought is measured from when it was noticed rather than from the last reminder."""
        return self.reports[0].reported_at

    @property
    def request_ids(self) -> tuple[int, ...]:
        """Every row a tick marks bought. Reports that arrive after this was read stay pending,
        which is the truth about them: they were not in her hand at the shop."""
        return tuple(one.request_id for one in self.reports)


def needed(rows: Iterable[dict]) -> tuple[Needed, ...]:
    """Every pending report, as `queries.pending_supplies` returns it, as a list to buy.

    Two reports are one line when they name the same catalog row, or — with no catalog row behind
    either — when the words fold to EXACTLY the same string. Never the catalog's overlap pass:
    it reads "cera" out of "cera caliente", and two different things on one line is an owner
    coming back without one of them. Same reasoning as client names (§3).
    """
    groups: dict[str, list[Report]] = {}
    labels: dict[str, tuple[str, bool]] = {}
    for row in rows:
        listed = bool(row.get("supply_ref"))
        key = f"ref:{row['supply_ref']}" if listed else f"said:{fold(row['said'] or '')}"
        groups.setdefault(key, []).append(_report(row))
        # The first report to arrive names an unlisted line, because it is the one whose words
        # the owner is being asked to recognize.
        labels.setdefault(key, (row["supply_name"] if listed else row["said"], listed))
    lines = [
        Needed(label=labels[key][0], listed=labels[key][1], reports=tuple(reports))
        for key, reports in groups.items()
    ]
    return tuple(sorted(lines, key=lambda one: (one.since, one.label)))


def waited(since: dt.datetime, now: dt.datetime) -> str:
    """How long this has been on the list, in her own register.

    Whole days apart rather than elapsed hours: something noticed last night and not bought is
    "ayer" to the woman reading it, whatever the clock makes of twelve hours.
    """
    days = (now.date() - since.date()).days
    if days <= 0:
        return WAITED_TODAY_TEXT
    if days == 1:
        return WAITED_YESTERDAY_TEXT
    return WAITED_DAYS_TEXT.format(days=days)


def first_name(full_name: str) -> str:
    """What a colleague is called on a line that has no room for more."""
    parts = (full_name or "").split()
    return parts[0] if parts else ""


def catalog(rows: Iterable[dict]) -> tuple[Supply, ...]:
    """The list a spoken phrase is matched against, built from `queries.supply_catalog`."""
    return tuple(
        Supply(
            supply_ref=row["supply_ref"],
            name=row["name"],
            aliases=tuple(a for a in (row["aliases"] or "").split("|") if a),
        )
        for row in rows
    )


def names(found: Sequence[Supply]) -> tuple[str, ...]:
    """What the salon has listed, for a question naming a few of them."""
    return tuple(one.name for one in found)


def _report(row: dict) -> Report:
    return Report(
        request_id=row["id"],
        said=row["said"],
        reported_by=row["reported_by_name"],
        reported_at=row["reported_at"],
        note=row.get("note") or "",
        has_photo=bool(row.get("photo_file_id")),
    )
