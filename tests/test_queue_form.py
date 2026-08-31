"""What a client submitted, asserted from bytes.

No HTTP, no database. THE property is that nothing arriving from a public form is trusted: an area
the salon does not have is DROPPED rather than carried to a query, and a `client_id` is a number
the caller typed rather than a permission — this module carries it and the router checks it against
the candidates the number actually reaches.
"""

from __future__ import annotations

import pytest

from aziza_adk import queue_form


def _body(**fields) -> bytes:
    parts = []
    for key, value in fields.items():
        for one in value if isinstance(value, (list, tuple)) else [value]:
            parts.append(f"{key}={one}")
    return "&".join(parts).encode()


# --- [1] The number is keyed on the way in, or refused ---------------------------------------


@pytest.mark.parametrize(
    "written", ["8095550101", "809-555-0101", "18095550101", "%2B1+809+555+0101"]
)
def test_however_she_typed_it_keys_to_the_ten_digits(written):
    assert queue_form.read(_body(phone=written)).phone == "8095550101"


@pytest.mark.parametrize("written", ["80955501", "", "abcdefghij", "80955501012"])
def test_a_number_that_is_not_one_of_the_salons_is_none_rather_than_repaired(written):
    """None rather than a best effort, the same refusal `clients.phone_key` makes: a digit missing
    is a typo, and a typo resolved to whoever it matches is a stranger's place in the line."""
    assert queue_form.read(_body(phone=written)).phone is None


# --- [2] Nothing from a public form is trusted -----------------------------------------------


def test_an_area_the_salon_does_not_have_is_dropped():
    """Dropped on the way in, so the codes a page offers and the codes it accepts are one list and
    a hand-posted body cannot reach a query with a code that means nothing."""
    assert queue_form.read(_body(areas=["nails", "massage"])).areas == ("nails",)


def test_the_same_area_ticked_twice_is_one_place():
    assert queue_form.read(_body(areas=["wax", "wax"])).areas == ("wax",)


def test_the_order_she_ticked_them_in_is_kept():
    assert queue_form.read(_body(areas=["wax", "nails"])).areas == ("wax", "nails")


def test_no_areas_is_an_empty_tuple_rather_than_every_area():
    assert queue_form.read(_body(phone="8095550101")).areas == ()


@pytest.mark.parametrize("written", ["", "abc", "-4", "1.5"])
def test_a_client_id_that_is_not_a_number_is_zero_rather_than_an_error(written):
    """Zero is "she was not choosing between candidates". The router checks whatever this carries
    against the clients that number reaches, so a value here authorizes nothing."""
    assert queue_form.read(_body(client_id=written)).client_id == 0


def test_a_client_id_that_is_a_number_is_carried_for_the_router_to_check():
    assert queue_form.read(_body(client_id="41")).client_id == 41


# --- [3] A malformed body is an absent field, never an exception -----------------------------


@pytest.mark.parametrize(
    "raw",
    [b"", b"=", b"&&&", b"phone", b"\xff\xfe not utf-8", b"areas=nails&areas", b"%%%=%%%"],
)
def test_a_body_nobody_could_have_meant_parses_to_nothing(raw):
    """This runs on a public path, so a body that raises is a 500 anybody can produce at will."""
    submitted = queue_form.read(raw)
    assert submitted.phone is None
    assert submitted.client_id == 0


def test_her_name_is_stripped_but_otherwise_left_alone():
    """Not title-cased and not folded: the salon stores the name she gave, and `clients.py` folds
    it when it needs to compare (§3)."""
    assert queue_form.read(_body(name="++MARÍA+de+los+Santos++")).name == "MARÍA de los Santos"
