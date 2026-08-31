"""Who a specialist may take next, asserted from values.

No database and no model, which is what makes it the gate. THE property is [2]: a client passed
over while somebody had her is ahead again the moment she is free — because a line is arrival order
with the attended removed, and nothing is ever rewritten.

[3] is the same rule read from the other side, and it is what makes [2] cost nothing: being
attended takes her out of EVERY line, not only the one she is being attended in. Had the design
demoted her instead of removing her, [2] would be false and no test of [3] would have noticed.
"""

from __future__ import annotations

import datetime as dt

import pytest

from aziza_adk import arrivals

NAILS = "nails"
WAX = "wax"

_NINE = dt.datetime(2026, 8, 27, 9, 0, tzinfo=dt.UTC)


def _at(minutes: int) -> dt.datetime:
    return _NINE + dt.timedelta(minutes=minutes)


def _row(arrival_id: int, name: str, arrived: int, waiting_for, serving=None) -> dict:
    return {
        "id": arrival_id,
        "client_name": name,
        "arrived_at": _at(arrived),
        "waiting_for": list(waiting_for),
        "serving": serving,
    }


def _carmen_and_ana(carmen_waiting=(NAILS, WAX), carmen_serving=None) -> list[dict]:
    """Carmen wants both and got here first; Ana wants only wax and came in ten minutes later."""
    return [
        _row(1, "Carmen", 0, carmen_waiting, carmen_serving),
        _row(2, "Ana", 10, (WAX,)),
    ]


def _names(found) -> list[str]:
    return [one.client_name for one in found]


# --- [1] One arrival is one woman, however many lines she is in -----------------------------


def test_a_client_waiting_for_two_areas_is_one_person_in_the_salon():
    """Two places in two lines and ONE woman standing there. Counting her twice reports more
    people waiting than the salon can see."""
    found = arrivals.line(_carmen_and_ana())
    assert _names(found) == ["Carmen", "Ana"]
    assert found[0].waiting_for == frozenset({NAILS, WAX})


def test_a_line_she_never_joined_never_reaches_her():
    found = arrivals.line(_carmen_and_ana())
    assert _names(arrivals.waiting_in(found, NAILS)) == ["Carmen"]


# --- [2] She keeps the place her arrival gave her --------------------------------------------


def test_she_is_ahead_again_the_moment_she_is_free():
    """THE property. Somebody has Carmen for nails, so Ana goes ahead of her for wax — and the
    moment Carmen is free she is first for wax again, because nothing moved her."""
    while_attended = arrivals.line(_carmen_and_ana(carmen_waiting=(WAX,), carmen_serving=NAILS))
    assert _names(arrivals.waiting_in(while_attended, WAX)) == ["Ana"]

    released = arrivals.line(_carmen_and_ana(carmen_waiting=(WAX,)))
    assert _names(arrivals.waiting_in(released, WAX)) == ["Carmen", "Ana"]


def test_arrival_time_is_the_whole_order_and_not_the_order_the_rows_came_back():
    """The read joins four tables; a database returning rows in any order must still be one line.
    Reversed input, same answer."""
    rows = list(reversed(_carmen_and_ana()))
    assert _names(arrivals.waiting_in(arrivals.line(rows), WAX)) == ["Carmen", "Ana"]


def test_two_who_arrived_in_the_same_instant_have_one_order():
    """An unstable tie changes the line under a specialist between two questions about it."""
    rows = [_row(5, "Yaritza", 3, (NAILS,)), _row(4, "Laura", 3, (NAILS,))]
    once = _names(arrivals.waiting_in(arrivals.line(rows), NAILS))
    twice = _names(arrivals.waiting_in(arrivals.line(list(reversed(rows))), NAILS))
    assert once == twice == ["Laura", "Yaritza"]


# --- [3] A chair takes her out of every line, not only out of one ----------------------------


def test_being_attended_in_one_area_takes_her_out_of_the_other_line():
    found = arrivals.line(_carmen_and_ana(carmen_waiting=(WAX,), carmen_serving=NAILS))
    assert _names(arrivals.waiting_in(found, WAX)) == ["Ana"]
    assert arrivals.waiting_in(found, NAILS) == ()


def test_the_next_one_up_skips_the_client_somebody_already_has():
    found = arrivals.line(_carmen_and_ana(carmen_waiting=(WAX,), carmen_serving=NAILS))
    assert arrivals.next_up(found, WAX).client_name == "Ana"


def test_nobody_free_is_nobody_rather_than_the_one_in_a_chair():
    """Handing back a client who is already sitting with somebody else is how two specialists
    end up standing over one woman."""
    rows = [_row(1, "Carmen", 0, (WAX,), NAILS)]
    assert arrivals.next_up(arrivals.line(rows), WAX) is None


def test_next_up_is_the_head_of_the_line_and_never_a_second_opinion():
    found = arrivals.line(_carmen_and_ana())
    assert arrivals.next_up(found, WAX) is arrivals.waiting_in(found, WAX)[0]


def test_an_empty_line_is_none_rather_than_a_refusal():
    assert arrivals.next_up(arrivals.line([]), NAILS) is None


# --- [4] A position is a number only when there is an honest one -----------------------------


def test_her_position_counts_from_one():
    found = arrivals.line(_carmen_and_ana())
    assert arrivals.position(found, WAX, arrival_id=1) == 1
    assert arrivals.position(found, WAX, arrival_id=2) == 2


@pytest.mark.parametrize(
    "arrival_id,because",
    [(1, "somebody already has her"), (99, "she never joined")],
)
def test_there_is_no_position_for_a_woman_who_is_not_waiting(arrival_id, because):
    """Both are None on purpose: a number is something she would stand and wait on, and there
    is none to give her."""
    found = arrivals.line(_carmen_and_ana(carmen_waiting=(), carmen_serving=WAX))
    assert arrivals.position(found, WAX, arrival_id=arrival_id) is None, because
