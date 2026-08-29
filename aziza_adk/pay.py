"""When a pay period starts and ends, and the day it is paid on.

Stdlib plus `hours`, no database and no model and no clock: every function takes the day it is
asked about. The salon pays twice a month and the arithmetic is small, but it is the arithmetic
behind a figure people are handed — so it is asserted from values rather than watched.

docs/PROJECT_DEFINITION.md §7.
"""

from __future__ import annotations

import calendar
import datetime as dt

from aziza_adk import hours

#: The day the first period ends and the second begins after.
_MIDPOINT = 15

#: The nominal second pay-day. A month with 31 days still pays on the 30th; a February pays on
#: whatever its last day is, because there is no 30th to pay on.
_SECOND_PAYDAY = 30


def period_for(day: dt.date) -> tuple[dt.date, dt.date]:
    """The pay period `day` falls in, as (first day, last day). The two cover every date."""
    last = calendar.monthrange(day.year, day.month)[1]
    if day.day <= _MIDPOINT:
        return day.replace(day=1), day.replace(day=_MIDPOINT)
    return day.replace(day=_MIDPOINT + 1), day.replace(day=last)


def payday_for(period_end: dt.date) -> dt.date:
    """When the period ending on `period_end` is paid: the 15th or the 30th, walked back to the
    last day the salon opened, since nobody is there to be paid on a day it is shut."""
    if period_end.day <= _MIDPOINT:
        nominal = period_end
    else:
        last = calendar.monthrange(period_end.year, period_end.month)[1]
        nominal = period_end.replace(day=min(_SECOND_PAYDAY, last))
    return hours.previous_workday(nominal)
