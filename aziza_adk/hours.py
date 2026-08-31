"""When the salon is open, and how long after closing an entry may still be recorded.

Stdlib only, no database, no model — and **no clock of its own**. Every predicate is handed the
moment it judges, which is what lets the after-hours refusal be asserted without waiting for a
Tuesday evening. The single wall-clock read on the turn path is `tools.now`.

The salon's own hours in the salon's own timezone, so the caller supplies a datetime already in it
(docs/PROJECT_DEFINITION.md §8).
"""

from __future__ import annotations

import datetime as dt

#: Monday is 0, the way `date.weekday()` counts. A day absent from this map is one the salon does
#: not open at all, and no grace hour follows a closing that never happened.
SCHEDULE: dict[int, tuple[int, int]] = {
    1: (9, 19),  # Tuesday
    2: (9, 19),  # Wednesday
    3: (9, 19),  # Thursday
    4: (9, 19),  # Friday
    5: (9, 18),  # Saturday
}

#: How long past closing an entry is still that day's work. A specialist finishing her last client
#: at 19:20 is doing nothing unusual, and a window that refused her would be worked around.
GRACE = dt.timedelta(hours=1)


def within_recording_window(when: dt.datetime) -> bool:
    """Opening until closing plus the grace hour, on a day the salon opens. False otherwise.

    Closed at both ends rather than only the late one: an entry at 03:00 is as far outside the
    working day as one at 23:00, and the hour it lands on says nothing about which.
    """
    span = SCHEDULE.get(when.weekday())
    if span is None:
        return False
    opens, closes = span
    start = when.replace(hour=opens, minute=0, second=0, microsecond=0)
    return start <= when <= start.replace(hour=closes) + GRACE


def is_open(when: dt.datetime) -> bool:
    """Whether the salon is open at that moment. NO grace hour, unlike the recording window.

    The grace is for a specialist finishing the client already in her chair; a client asking to
    JOIN the line at 19:30 is asking to be started after closing (§13).
    """
    span = SCHEDULE.get(when.weekday())
    if span is None:
        return False
    opens, closes = span
    start = when.replace(hour=opens, minute=0, second=0, microsecond=0)
    return start <= when < start.replace(hour=closes)


def is_workday(day: dt.date) -> bool:
    """Whether the salon opens at all on `day`."""
    return day.weekday() in SCHEDULE


def previous_workday(day: dt.date) -> dt.date:
    """The last day the salon opened on or before `day`.

    Answers `day` itself when it is one. A pay-day that lands on a Sunday is paid on the Saturday,
    which is what "or the last previous work day" means (docs/PROJECT_DEFINITION.md §7).
    """
    while not is_workday(day):
        day -= dt.timedelta(days=1)
    return day
