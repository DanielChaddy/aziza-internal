"""Resolving what a specialist said to something the salon actually sells.

THE property of this file: a service that is not in the catalog resolves to nothing, and a price
is only ever read off a catalog row. Asserted from values alone — no database behind it.
"""

from decimal import Decimal

import pytest

from aziza_adk.catalog import Service, names, resolve

MANI = Service("svc-1", "Manicure clásico", "nails", Decimal("800.00"), ("manicure", "mani"))
GEL = Service("svc-2", "Manicure en gel", "nails", Decimal("1400.00"), ("gel",))
LEGS = Service("svc-3", "Depilación de piernas", "wax", Decimal("1500.00"), ("piernas",))
CATALOG = (MANI, GEL, LEGS)


# --- [1] What resolves --------------------------------------------------------------------


def test_the_full_name_resolves():
    assert resolve("Manicure clásico", CATALOG).match is MANI


def test_missing_accents_do_not_hide_a_service():
    """A specialist typing on a phone between clients does not reach for the accent key."""
    assert resolve("manicure clasico", CATALOG).match is MANI
    assert resolve("depilacion de piernas", CATALOG).match is LEGS


def test_an_alias_resolves():
    """What she calls it out loud, which is rarely the catalog's own wording."""
    assert resolve("mani", CATALOG).match is MANI
    assert resolve("piernas", CATALOG).match is LEGS


def test_a_whole_sentence_resolves_to_the_service_inside_it():
    assert resolve("le hice un manicure en gel", CATALOG).match is GEL


def test_case_does_not_matter():
    assert resolve("MANICURE EN GEL", CATALOG).match is GEL


# --- [2] What does NOT resolve — the property the whole design rests on --------------------


def test_a_service_the_salon_does_not_sell_resolves_to_nothing():
    found = resolve("corte de pelo", CATALOG)
    assert found.match is None and found.candidates == ()


def test_an_empty_phrase_resolves_to_nothing():
    for said in ("", "   ", None):
        assert resolve(said, CATALOG).match is None


def test_a_fragment_too_short_to_mean_anything_resolves_to_nothing():
    """Two letters match most of a catalog, and an ambiguity that wide is indistinguishable from
    no answer at all."""
    assert resolve("ma", CATALOG).match is None


# --- [3] Ambiguity is returned rather than guessed at --------------------------------------


def test_a_phrase_naming_two_services_returns_both_and_picks_neither():
    """Picking the first of two services with different prices is a wrong receipt, which is worse
    than one more question."""
    catalog = (
        Service("a", "Manicure clásico", "nails", Decimal("800.00")),
        Service("b", "Manicure en gel", "nails", Decimal("1400.00")),
    )
    found = resolve("manicure", catalog)
    assert found.match is None
    assert {s.name for s in found.candidates} == {"Manicure clásico", "Manicure en gel"}


def test_an_exact_alias_beats_an_ambiguous_overlap():
    """The alias is the salon saying which one it meant, so it settles the question."""
    assert resolve("manicure", CATALOG).match is MANI


# --- [4] The price comes off the row, and only off the row --------------------------------


def test_the_resolved_row_carries_the_salons_price():
    assert resolve("gel", CATALOG).match.price == Decimal("1400.00")


def test_the_resolved_row_carries_the_discipline_the_guard_reads():
    assert resolve("piernas", CATALOG).match.discipline == "wax"


def test_what_exists_is_the_catalogs_own_names():
    assert names(CATALOG) == ("Manicure clásico", "Manicure en gel", "Depilación de piernas")


@pytest.mark.parametrize("said", ["corte", "botox", "masaje", "uñas de porcelana"])
def test_nothing_outside_the_catalog_is_ever_invented(said):
    assert resolve(said, CATALOG).match is None
