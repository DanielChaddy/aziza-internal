"""Who may talk to this assistant, and whose work an entry belongs to.

A Telegram id is a credential rather than a label — an id the database does not hold ACTIVE
reaches nothing (docs/PROJECT_DEFINITION.md §3). So the two properties here are about access:
that the dataset says who exists, and that removing someone from it takes their access away.

The resolution half reaches no database and no model. The revocation half needs one.
"""

from __future__ import annotations

import pytest

from aziza_adk import catalog, queries, staff, staff_data

# --- [1] The salon's real people --------------------------------------------------------------


def test_the_salon_has_an_owner():
    """Naming another specialist's work is an owner's alone, so a dataset with none in it can
    record nothing for anybody who cannot type."""
    assert [p for p in staff_data.STAFF if "owner" in p["roles"]]


def test_every_role_a_person_holds_is_one_the_salon_defines():
    """A role code that no row in ROLES matches seeds nothing and grants nothing, silently."""
    defined = {r["code"] for r in staff_data.ROLES}
    for person in staff_data.STAFF:
        assert set(person["roles"]) <= defined, person["specialist_ref"]


@pytest.mark.parametrize("person", staff_data.STAFF, ids=lambda p: p["specialist_ref"])
def test_a_telegram_id_is_absent_or_usable_and_never_blank(person):
    """`None` is someone the salon records work for who cannot talk to the assistant. The empty
    string is neither, and would be matched by a sender who supplied nothing."""
    tg = person["telegram_user_id"]
    assert tg is None or (isinstance(tg, str) and tg.isdigit())
    assert person["full_name"].strip()


@pytest.mark.parametrize("person", staff_data.STAFF, ids=lambda p: p["specialist_ref"])
def test_someone_who_cannot_type_has_work_to_record(person):
    """Her only way in is an owner naming her, and a name resolves against the disciplines
    roster — so a row with neither an id nor a discipline can neither act nor be acted for."""
    if person["telegram_user_id"] is None:
        assert person["disciplines"], person["specialist_ref"]


def test_no_real_person_shares_a_ref_with_an_invented_one():
    from aziza_adk import demo_data

    real = {p["specialist_ref"] for p in staff_data.STAFF}
    invented = {p["specialist_ref"] for p in demo_data.SPECIALISTS}
    assert not real & invented


# --- [2] Resolving a spoken name --------------------------------------------------------------


def _rows(*names: str) -> list[dict]:
    return [
        {"id": i, "full_name": name, "disciplines": ["nails"]} for i, name in enumerate(names, 1)
    ]


def test_a_first_name_finds_her():
    people = staff.people(_rows("Zenaida Prueba", "Ubaldina Segunda"))
    assert catalog.resolve("Zenaida", people).match.name == "Zenaida Prueba"


def test_two_people_sharing_a_first_name_come_back_as_both():
    """Picking the first would book a commission to the wrong person, quietly."""
    people = staff.people(_rows("Zenaida Prueba", "Zenaida Segunda"))
    found = catalog.resolve("Zenaida", people)
    assert found.match is None
    assert len(found.candidates) == 2


def test_a_single_word_name_gets_no_alias():
    """An alias equal to the name would make the same row match twice for no gain."""
    assert staff.people(_rows("Zenaida"))[0].aliases == ()


def test_a_name_nobody_answers_to_resolves_to_nothing():
    assert catalog.resolve("Nadie", staff.people(_rows("Zenaida Prueba"))).match is None


# --- [3] Removing someone takes their access away ---------------------------------------------


def test_a_specialist_absent_from_the_dataset_is_stood_down(conn, make_specialist):
    """THE property: the dataset is the source of truth for who may talk to this assistant. A
    re-seed that left a deleted person active would keep a credential nobody meant to keep."""
    staying = make_specialist("nails", full_name="Zenaida Prueba")
    leaving = make_specialist("nails", full_name="Ubaldina Segunda")

    queries.stand_down_absent(conn, [staying["specialist_ref"]])

    assert queries.specialist_by_telegram_id(conn, staying["telegram_user_id"]) is not None
    assert queries.specialist_by_telegram_id(conn, leaving["telegram_user_id"]) is None


def test_standing_down_does_not_erase_her(conn, make_specialist):
    """Deactivated, not deleted — the salon's record of what she billed is not hers to remove."""
    leaving = make_specialist("nails", full_name="Ubaldina Segunda")
    queries.stand_down_absent(conn, [])
    row = queries.fetchone(
        conn, "SELECT active FROM specialists WHERE id = %(i)s", {"i": leaving["id"]}
    )
    assert row is not None and row["active"] is False
