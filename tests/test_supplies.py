"""The list to buy, asserted from values.

No database and no model, which is what makes it the gate. THE property is [1]: three people
noticing the same shortage are ONE line an owner buys once, and the grouping that does it is
exact — [2] is the other half, because a grouping that read "cera" out of "cera caliente" would
send her home with the wrong tin.

The clock is a parameter throughout, so "waiting five days" is a value rather than five days
spent waiting for it.
"""

from __future__ import annotations

import datetime as dt

import pytest

from aziza_adk import supplies

_NINE = dt.datetime(2026, 9, 7, 9, 0, tzinfo=dt.UTC)


def _at(hours: int) -> dt.datetime:
    return _NINE + dt.timedelta(hours=hours)


def _row(
    request_id: int,
    said: str,
    *,
    at: int = 0,
    ref: str = "",
    name: str = "",
    who: str = "Mariana Pernía",
    note: str = "",
    photo: str = "",
) -> dict:
    return {
        "id": request_id,
        "said": said,
        "note": note,
        "photo_file_id": photo,
        "reported_at": _at(at),
        "supply_ref": ref or None,
        "supply_name": name or None,
        "reported_by_name": who,
    }


# --- [1] Everybody who asked for one thing is one line ----------------------


def test_three_people_asking_for_the_same_thing_are_one_line():
    """THE property. An owner reading three "acetona" buys three, and two of them come back."""
    found = supplies.needed(
        [
            _row(1, "acetona", ref="sup-1", name="Acetona"),
            _row(2, "el acetona", at=2, ref="sup-1", name="Acetona"),
            _row(3, "acetona pura", at=5, ref="sup-1", name="Acetona"),
        ]
    )
    assert [one.label for one in found] == ["Acetona"]
    assert len(found[0].reports) == 3


def test_the_line_is_labelled_by_the_salons_name_rather_than_by_what_she_said():
    """Three people said three things. The label is the one the salon chose, or a list reads as
    three different shortages to whoever is holding it."""
    found = supplies.needed(
        [
            _row(1, "el acetona ese", ref="sup-1", name="Acetona"),
            _row(2, "quitaesmalte", at=1, ref="sup-1", name="Acetona"),
        ]
    )
    assert found[0].label == "Acetona"
    assert found[0].listed is True


def test_a_tick_names_every_row_on_the_line():
    """She bought it once; everybody who asked is answered. A line ticking off only the row that
    happened to be on top leaves the same thing on the list tomorrow."""
    found = supplies.needed(
        [
            _row(4, "acetona", ref="sup-1", name="Acetona"),
            _row(9, "acetona", at=3, ref="sup-1", name="Acetona"),
        ]
    )
    assert found[0].request_ids == (4, 9)


# --- [2] What does NOT group ------------------------------------------------


def test_two_unlisted_things_group_only_on_exactly_the_same_words():
    """Exact on folded, never the catalog's overlap pass: it reads "cera" out of "cera caliente",
    and two different things on one line is an owner coming back without one of them (§3)."""
    found = supplies.needed(
        [
            _row(1, "cera"),
            _row(2, "cera caliente", at=1),
            _row(3, "CERA", at=2),
        ]
    )
    assert [(one.label, len(one.reports)) for one in found] == [("cera", 2), ("cera caliente", 1)]


def test_an_unlisted_thing_never_joins_a_listed_one():
    """They are different claims: one names a row the salon keeps, the other is somebody's words
    for something it does not. Merging them would put a name on a line nobody chose."""
    found = supplies.needed(
        [
            _row(1, "acetona", ref="sup-1", name="Acetona"),
            _row(2, "acetona", at=1),
        ]
    )
    assert len(found) == 2
    assert [one.listed for one in found] == [True, False]


def test_an_unlisted_line_carries_the_first_words_anybody_used():
    """It is the name she is being asked to recognize, so it is the one somebody actually said —
    and the first of them, because that is the report the list is dated by."""
    found = supplies.needed([_row(1, "papel de camilla"), _row(2, "PAPEL DE CAMILLA", at=4)])
    assert found[0].label == "papel de camilla"
    assert found[0].listed is False


# --- [3] What order she reads it in -----------------------------------------


def test_the_longest_wait_is_at_the_top():
    found = supplies.needed(
        [
            _row(1, "guantes", at=10),
            _row(2, "algodón", at=1),
            _row(3, "guantes", at=12),
        ]
    )
    assert [one.label for one in found] == ["algodón", "guantes"]


def test_a_line_is_dated_by_the_first_person_to_ask_not_the_last():
    """A shortage is measured from when it was noticed. Dated by the latest reminder, the thing
    nobody has bought for a week would sink every time somebody mentioned it again."""
    found = supplies.needed([_row(1, "algodón", at=0), _row(2, "algodón", at=30)])
    assert found[0].since == _at(0)


# --- [4] What one line says -------------------------------------------------


def test_a_report_carries_who_said_it_and_whether_there_is_a_picture():
    found = supplies.needed(
        [_row(1, "cera", who="Kathy Santos", note="queda medio pote", photo="AgAC")]
    )
    report = found[0].reports[0]
    assert (report.reported_by, report.note, report.has_photo) == (
        "Kathy Santos",
        "queda medio pote",
        True,
    )


def test_a_report_with_no_picture_says_so():
    found = supplies.needed([_row(1, "cera")])
    assert found[0].reports[0].has_photo is False


def test_nothing_pending_is_an_empty_list_rather_than_a_line_saying_so():
    assert supplies.needed([]) == ()


# --- [5] How long it has been waiting ---------------------------------------


@pytest.mark.parametrize(
    "hours,expected",
    [
        (0, supplies.WAITED_TODAY_TEXT),
        (2, supplies.WAITED_TODAY_TEXT),
        (-20, supplies.WAITED_YESTERDAY_TEXT),
        (-60, "hace 3 días"),
    ],
)
def test_how_long_it_has_been_waiting_counts_days_and_not_hours(hours, expected):
    """Whole days apart, because something noticed last night and not bought is "ayer" to the
    woman reading it, whatever the clock makes of twelve hours."""
    assert supplies.waited(_at(hours), _NINE) == expected


def test_a_report_somehow_dated_ahead_reads_as_today():
    """Fails soft rather than saying "hace -1 días". A clock skew is not worth a broken line."""
    assert supplies.waited(_at(5), _NINE) == supplies.WAITED_TODAY_TEXT


# --- [6] The catalog it resolves against ------------------------------------


def test_the_catalog_splits_the_words_she_says_it_by():
    found = supplies.catalog(
        [{"supply_ref": "sup-1", "name": "Acetona", "aliases": "quitaesmalte|removedor"}]
    )
    assert found[0].aliases == ("quitaesmalte", "removedor")
    assert supplies.names(found) == ("Acetona",)


def test_a_catalog_row_with_no_aliases_has_none_rather_than_one_empty_one():
    """An empty alias folds to "" and would match anything she said that folded to nothing."""
    found = supplies.catalog([{"supply_ref": "sup-1", "name": "Acetona", "aliases": ""}])
    assert found[0].aliases == ()


def test_a_supply_resolves_through_the_catalogs_own_resolver():
    """The same function a service resolves through, unchanged — a supply is a name and the words
    she calls it by, which is all that resolver ever reads."""
    from aziza_adk import catalog

    found = supplies.catalog(
        [{"supply_ref": "sup-1", "name": "Acetona", "aliases": "quitaesmalte"}]
    )
    assert catalog.resolve("quitaesmalte", found).match.supply_ref == "sup-1"
    assert catalog.resolve("papel de camilla", found).match is None


def test_a_first_name_is_what_fits_on_a_line():
    assert supplies.first_name("Mariana Pernía") == "Mariana"
    assert supplies.first_name("") == ""
