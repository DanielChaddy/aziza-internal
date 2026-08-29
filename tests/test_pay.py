"""When a pay period runs, and the day it is paid on.

Reaches no database, no model and no clock: every case is a date in and a date out. The salon
pays twice a month against these figures, so the arithmetic is asserted rather than watched.

docs/PROJECT_DEFINITION.md §7.
"""

from __future__ import annotations

import datetime as dt

import pytest

from aziza_adk import pay

# --- [1] The two periods cover every day ------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "start", "end"),
    [
        (dt.date(2026, 8, 1), dt.date(2026, 8, 1), dt.date(2026, 8, 15)),
        (dt.date(2026, 8, 15), dt.date(2026, 8, 1), dt.date(2026, 8, 15)),
        (dt.date(2026, 8, 16), dt.date(2026, 8, 16), dt.date(2026, 8, 31)),
        (dt.date(2026, 8, 31), dt.date(2026, 8, 16), dt.date(2026, 8, 31)),
        # The second period runs to the end of the month however long it is.
        (dt.date(2026, 9, 20), dt.date(2026, 9, 16), dt.date(2026, 9, 30)),
        (dt.date(2027, 2, 20), dt.date(2027, 2, 16), dt.date(2027, 2, 28)),
    ],
    ids=lambda v: v.isoformat(),
)
def test_which_period_a_day_belongs_to(day, start, end):
    assert pay.period_for(day) == (start, end)


def test_no_day_of_a_month_falls_outside_a_period():
    """THE property of the pair: a day nobody is paid for is a day nobody notices is missing."""
    for offset in range(31):
        day = dt.date(2026, 8, 1) + dt.timedelta(days=offset)
        start, end = pay.period_for(day)
        assert start <= day <= end


# --- [2] Nobody is paid on a day the salon is shut --------------------------------------------


@pytest.mark.parametrize(
    ("period_end", "payday", "why"),
    [
        (dt.date(2026, 8, 15), dt.date(2026, 8, 15), "the 15th is a Saturday, and the salon opens"),
        (dt.date(2026, 8, 31), dt.date(2026, 8, 29), "the 30th is a Sunday, so the Saturday"),
        (dt.date(2026, 11, 15), dt.date(2026, 11, 14), "the 15th is a Sunday, so the Saturday"),
        (dt.date(2026, 11, 30), dt.date(2026, 11, 28), "the 30th is a Monday, and Monday is shut"),
        (dt.date(2027, 2, 28), dt.date(2027, 2, 27), "no 30th; the 28th is a Sunday"),
        (dt.date(2026, 9, 30), dt.date(2026, 9, 30), "a Wednesday needs no walking back"),
    ],
    ids=lambda v: v.isoformat() if isinstance(v, dt.date) else "",
)
def test_a_payday_lands_on_a_day_the_salon_opens(period_end, payday, why):
    assert pay.payday_for(period_end) == payday, why


def test_every_payday_of_a_year_is_a_working_day():
    """Swept rather than sampled: the walk-back has one job and a month that broke it would be
    found by nobody until somebody was not paid."""
    from aziza_adk import hours

    for month in range(1, 13):
        for end in (dt.date(2026, month, 15), pay.period_for(dt.date(2026, month, 20))[1]):
            assert hours.is_workday(pay.payday_for(end)), end
