"""Which price column a client's name selects.

No model and no database: this is the whole reason the derivation is a table rather than a
question put to the model. A wrong column is RD$550 on Piernas completas, so the rule that
decides it has to be one an assertion can hold still.
"""

from __future__ import annotations

import pytest

from aziza_adk import names


def test_the_tables_do_not_overlap():
    """A name in two tables would resolve by whichever is checked first, which is not a rule."""
    assert not names._FEMALE & names._MALE
    assert not (names._FEMALE | names._MALE) & names._AMBIGUOUS


@pytest.mark.parametrize("client", ["Laura", "laura", "LAURA", "Yamilé", "Rosa Almánzar"])
def test_a_recognized_woman_is_matched_rather_than_assumed(client):
    assert names.derive(client) == ("female", names.MATCHED)


@pytest.mark.parametrize("client", ["Luis", "José", "Ángel", "Pedro Martínez"])
def test_a_recognized_man_is_matched(client):
    assert names.derive(client) == ("male", names.MATCHED)


def test_a_compound_name_resolves_on_its_first_part():
    """ "María José" is a woman and "José María" is a man, and only the first token gets both."""
    assert names.derive("María José")[0] == "female"
    assert names.derive("José María")[0] == "male"


@pytest.mark.parametrize("client", ["Ariel", "Alexis", "Yuri", "Cruz", "Guadalupe"])
def test_a_name_that_goes_both_ways_is_defaulted_rather_than_matched(client):
    """Listed precisely so it DEFAULTS: the notice on the ticket is the point of knowing."""
    assert names.derive(client) == ("female", names.DEFAULTED)


@pytest.mark.parametrize("client", ["Zoraida", "Xanthe", "", "   ", "Ω"])
def test_an_unrecognized_name_is_priced_female_and_says_so(client):
    """The tables cannot be exhaustive. What stops that being silent is the provenance."""
    gender, source = names.derive(client)
    assert (gender, source) == ("female", names.DEFAULTED)


def test_the_accent_is_folded_before_the_lookup():
    assert names.derive("JOSE")[0] == "male"
    assert names.derive("josé")[0] == "male"
