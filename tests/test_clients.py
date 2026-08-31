"""Which client a name and a number mean, asserted from values.

No database and no model, which is what makes it the gate. THE property is [3]: two people who
share a name are a question rather than a pick, because charging the first of two Marías is how
one of them pays the other's balance.

The shape rules are [1] and [2], and they earn their keep in opposite directions — a number
written two ways must not become two clients, and a number that is not one of the salon's must
not become a client at all.
"""

from __future__ import annotations

import pytest

from aziza_adk import clients

_ROWS = [
    {"id": 7, "name": "María Fernández", "phone": "8095550101"},
    {"id": 9, "name": "María Peña", "phone": "8295550202"},
]


def _roster(*rows: dict) -> tuple[clients.Client, ...]:
    return clients.roster(rows or _ROWS)


# --- [1] One number, however she wrote it ---------------------------------------------------


@pytest.mark.parametrize(
    "written",
    [
        "8095550101",
        "809-555-0101",
        "809 555 0101",
        "(809) 555-0101",
        "+1 809 555 0101",
        "1-809-555-0101",
        " 809.555.0101 ",
    ],
)
def test_however_she_wrote_it_is_one_stored_number(written):
    """Formatting is the one thing both sides disagree about by construction, and a number that
    keyed two ways would be one client entered twice."""
    assert clients.phone_key(written) == "8095550101"


def test_the_country_code_is_stripped_rather_than_stored():
    """Stored, it would make the same woman two rows the first time somebody typed the short
    form — the exact split this module exists to prevent."""
    assert clients.phone_key("18095550101") == clients.phone_key("8095550101")


# --- [2] A number that is not one, refused rather than repaired ------------------------------


@pytest.mark.parametrize(
    "written",
    ["809555010", "80955501012", "", "   ", "ocho cero nueve", "no me lo sé"],
)
def test_a_number_the_salon_cannot_read_is_refused(written):
    """None rather than a best effort. A digit short is a typo, and a typo resolved to whoever it
    happens to match is a stranger's balance."""
    assert clients.phone_key(written) is None


def test_everything_that_is_not_a_digit_is_dropped_and_the_count_is_the_whole_rule():
    """`conversation_core.normalize_phone` strips non-digits wholesale and this module adds only a
    length. So a stray letter is discarded like a dash, and ten digits is the entire test — worth
    pinning, because a stricter rule here would be a second normalizer four repositories do not
    have."""
    assert clients.phone_key("809-555-010x1") == "8095550101"


def test_a_cedula_is_not_a_long_telephone():
    """Eleven digits is `conversation_core.identity`'s shape, and it is refused here rather than
    trimmed to ten — trimming would file her under a number that is not hers."""
    assert clients.phone_key("40212345678") is None


# --- [3] Which of them she is -----------------------------------------------------------------


def test_two_who_share_a_name_come_back_as_both():
    """THE property. Picking the first would charge one María for the other's work, quietly."""
    found = clients.pick(_roster())
    assert found.match is None
    assert len(found.candidates) == 2


def test_the_number_chooses_between_them():
    found = clients.pick(_roster(), "8295550202")
    assert found.match.client_id == 9


def test_one_client_of_that_name_needs_no_number():
    """A returning client the salon already knows is never asked again — "always" is about a
    client it does not know."""
    assert clients.pick(_roster(_ROWS[0])).match.client_id == 7


def test_a_number_none_of_them_holds_resolves_to_nothing():
    """Never to the nearest one. That is a different woman."""
    found = clients.pick(_roster(), "8495559999")
    assert found.match is None
    assert found.candidates == ()


@pytest.mark.parametrize("phone", ["", "8095550101"])
def test_a_name_nobody_answers_to_resolves_to_nothing(phone):
    found = clients.pick((), phone)
    assert found.match is None
    assert found.candidates == ()


# --- [4] The adapter --------------------------------------------------------------------------


def test_the_roster_carries_what_the_query_returns():
    who = _roster(_ROWS[0])[0]
    assert (who.client_id, who.name, who.phone) == (7, "María Fernández", "8095550101")
