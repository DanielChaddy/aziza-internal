"""Resolving what a specialist said to something the salon actually sells.

THE property of this file: a service that is not in the catalog resolves to nothing, and a price
is only ever read off a catalog row. Asserted from values alone — no database behind it.
"""

from decimal import Decimal

import pytest

from aziza_adk import catalog_data
from aziza_adk.catalog import MALE, Product, Service, mentions, names, price_for, resolve

#: A SYNTHETIC catalog, small enough that each rule can be seen firing on its own. The salon's
#: real one is exercised at the bottom of this file, where the names overlap far more.
MANI = Service(
    "svc-1",
    "Manicure clásico",
    "nails",
    Decimal("800.00"),
    Decimal("900.00"),
    ("manicure", "mani"),
)
GEL = Service("svc-2", "Manicure en gel", "nails", Decimal("1400.00"), Decimal("1500.00"), ("gel",))
LEGS = Service(
    "svc-3", "Depilación de piernas", "wax", Decimal("1500.00"), Decimal("2000.00"), ("piernas",)
)
CATALOG = (MANI, GEL, LEGS)


def _real_services() -> tuple[Service, ...]:
    """The salon's own catalog, built from the dataset the seeder reads."""
    return tuple(
        Service(
            service_ref=s["service_ref"],
            name=s["name"],
            discipline=s["discipline"],
            price_female=None if s["price_female"] is None else Decimal(s["price_female"]),
            price_male=None if s["price_male"] is None else Decimal(s["price_male"]),
            aliases=tuple(a for a in s["aliases"].split("|") if a),
        )
        for s in catalog_data.SERVICES
    )


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
        Service("a", "Manicure clásico", "nails", Decimal("800.00"), Decimal("900.00")),
        Service("b", "Manicure en gel", "nails", Decimal("1400.00"), Decimal("1500.00")),
    )
    found = resolve("manicure", catalog)
    assert found.match is None
    assert {s.name for s in found.candidates} == {"Manicure clásico", "Manicure en gel"}


def test_an_exact_alias_beats_an_ambiguous_overlap():
    """The alias is the salon saying which one it meant, so it settles the question."""
    assert resolve("manicure", CATALOG).match is MANI


# --- [4] The price comes off the row, and only off the row --------------------------------


def test_the_resolved_row_carries_the_salons_price():
    assert resolve("gel", CATALOG).match.price_female == Decimal("1400.00")


def test_the_resolved_row_carries_the_discipline_the_guard_reads():
    assert resolve("piernas", CATALOG).match.discipline == "wax"


def test_what_exists_is_the_catalogs_own_names():
    assert names(CATALOG) == ("Manicure clásico", "Manicure en gel", "Depilación de piernas")


@pytest.mark.parametrize("said", ["corte", "botox", "masaje", "uñas de porcelana"])
def test_nothing_outside_the_catalog_is_ever_invented(said):
    assert resolve(said, CATALOG).match is None


# --- [4] The salon's own catalog, where the names really do overlap -------------------------


def test_a_word_that_names_three_prices_comes_back_ambiguous():
    """ "manicura" begins three services at three prices. Resolving it to the cheapest would be a
    wrong receipt, which is the one outcome worse than another question."""
    found = resolve("manicura", _real_services())
    assert found.match is None
    assert len(found.candidates) == 3


def test_every_retoque_is_offered_rather_than_one_being_picked():
    """The salon's list writes "Retoque" eight times, each meaning the row above it."""
    found = resolve("retoque", _real_services())
    assert found.match is None
    assert len(found.candidates) == 8


def test_naming_the_parent_narrows_the_retoque():
    assert (
        resolve("retoque de acrilico vip", _real_services()).match.name == "Retoque de Acrílico VIP"
    )


def test_a_longer_name_does_not_swallow_a_shorter_one():
    """ "piernas" must not come back ambiguous against "Media pierna", and "pecho" must resolve
    even though "Pecho y Abdomen" exists."""
    real = _real_services()
    assert resolve("piernas", real).match.name == "Piernas completas"
    assert resolve("pecho", real).match.name == "Pecho"


def test_nothing_outside_the_real_catalog_resolves():
    assert resolve("corte de pelo", _real_services()).match is None


@pytest.mark.parametrize(
    "service_name,gender",
    [("Brasilero completo", MALE), ("Barba", "female"), ("Espalda Completa", "female")],
)
def test_a_service_the_salon_does_not_offer_that_client_has_no_price(service_name, gender):
    """None, and NOT the other column: reading across would charge a price the salon never set."""
    row = next(s for s in _real_services() if s.name == service_name)
    assert price_for(row, gender) is None


def test_the_two_columns_differ_where_the_salon_says_they_do():
    row = next(s for s in _real_services() if s.name == "Piernas completas")
    assert price_for(row, "female") == Decimal("850.00")
    assert price_for(row, MALE) == Decimal("1400.00")


def test_an_unrecognized_client_is_refused_rather_than_priced_female():
    with pytest.raises(ValueError):
        price_for(MANI, "señora")


# --- [5] One resolver, two kinds of row -----------------------------------------------------


def _real_products() -> tuple[Product, ...]:
    return tuple(
        Product(
            product_ref=p["product_ref"],
            name=p["name"],
            price_client=Decimal(p["price_client"]),
            price_specialist=Decimal(p["price_specialist"]),
            aliases=tuple(a for a in p["aliases"].split("|") if a),
        )
        for p in catalog_data.PRODUCTS
    )


def _real_services() -> tuple[Service, ...]:
    return tuple(
        Service(
            service_ref=s["service_ref"],
            name=s["name"],
            discipline=s["discipline"],
            price_female=Decimal(s["price_female"]) if s["price_female"] else None,
            price_male=Decimal(s["price_male"]) if s["price_male"] else None,
            aliases=tuple(a for a in s["aliases"].split("|") if a),
        )
        for s in catalog_data.SERVICES
    )


def test_the_same_resolver_serves_products():
    """Products reuse the service resolver rather than a second copy of it, so ambiguity and
    aliasing behave identically for both."""
    assert resolve("coca", _real_products()).match.name == "Coca-Cola"
    assert resolve("agua", _real_products()).match.price_client == Decimal("25.00")


def test_no_two_products_share_a_name():
    """A name the catalog holds twice cannot resolve: `_by_name` returns both and the specialist
    is asked a question whose answer cannot change the total."""
    names = [p["name"] for p in catalog_data.PRODUCTS]
    assert len(names) == len(set(names))


def test_a_bare_brand_resolves_to_the_row_that_bears_it():
    """`resolve` matches the full name before it matches a fragment, so "doritos" is the Doritos
    row rather than an ambiguity with Doritos Dinamita."""
    assert resolve("ritz", _real_products()).match.name == "Ritz"
    assert resolve("doritos", _real_products()).match.name == "Doritos"


# --- [6] Is this phrase a client's name, or the work? ------------------------------------------


def test_a_phrase_that_names_the_work_is_recognized():
    """The failure this catches: a ticket opened as "Axilas y bc" prices whoever that is by the
    name table and prints it on the receipt, and nothing downstream can tell it from a client."""
    assert mentions("Axilas y bc", _real_services()).name == "Axilas"
    assert mentions("Doritos", _real_products()).name == "Doritos"


def test_a_client_keeps_her_name_when_it_merely_contains_one():
    """Word boundaries, not substrings: "Yaritza" contains "ritz" and "Pestañas" contains "ana".
    Refusing a client for her own name is worse than the mistake this guard catches."""
    for real in ("Ana", "Yaritza", "Rosa María", "Carmen", "Altagracia", "Mercedes"):
        assert mentions(real, _real_services()) is None, real
        assert mentions(real, _real_products()) is None, real


def test_a_phrase_naming_nothing_the_salon_sells_is_left_alone():
    """`mentions` answers only for terms the catalog actually holds. Bare "manicura" is an alias
    of nothing by design, so this is a bound on the guard rather than a gap in it."""
    assert mentions("Carmen", _real_services()) is None
