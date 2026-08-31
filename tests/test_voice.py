"""The salon's voice, gated.

Two halves, and the second is the one that earns its keep. The first checks only what is this
repository's: which direction it gates, and the nouns and figure shape it supplies. The
conjugation and the markup are asserted beside `conversation_core`. The second half turns the
whole thing on THIS REPOSITORY'S OWN STRINGS — every literal a specialist can read with no model
in the path.

Those strings are DISCOVERED rather than listed: any module-level constant named `*_MSG` or
`*_TEXT` in `aziza_adk` is collected and checked. That naming convention is the contract — a
string added under it is gated the moment it is written, and one added outside it is invisible
here, which is why the convention is stated in docs/BRAND_VOICE.md rather than inferred.
"""

from __future__ import annotations

import datetime
import decimal
import importlib
import pathlib
import pkgutil
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "eval"))

import voice_checks  # noqa: E402

_SUFFIXES = ("_MSG", "_TEXT")


def _specialist_facing() -> list[tuple[str, str]]:
    """Every `(where, text)` a specialist can read without a model having composed it."""
    import aziza_adk

    found: list[tuple[str, str]] = []
    for info in pkgutil.walk_packages(aziza_adk.__path__, prefix="aziza_adk."):
        module = importlib.import_module(info.name)
        for name in dir(module):
            if name.startswith("_") or not name.endswith(_SUFFIXES):
                continue
            value = getattr(module, name)
            if isinstance(value, str) and value.strip():
                found.append((f"{info.name}.{name}", value))
    return sorted(set(found))


SPECIALIST_FACING = _specialist_facing()

each_string = pytest.mark.parametrize(
    "where,text", SPECIALIST_FACING, ids=[where for where, _ in SPECIALIST_FACING]
)


# --- the checks themselves --------------------------------------------------


def test_this_repository_gates_the_formal_direction():
    """A salon addresses a colleague, so the reasons wanted here are the FORMAL ones. The shared
    check runs both ways and picking the wrong one would pass every string this repository ships."""
    assert voice_checks.usted_reasons("Por favor confirme su cuenta")


def test_the_formal_possessive_over_a_salon_noun_is_caught():
    """The noun list is this salon's and travels as a parameter, so it is asserted here."""
    assert voice_checks.usted_reasons("Su comisión de hoy es RD$400.00")


def test_an_amount_the_assistant_wrote_itself_is_caught():
    """Every figure it sends came from a tool already formatted; a space after the mark means it
    was retyped, and a retyped figure is one the tools cannot vouch for."""
    assert voice_checks.amount_reasons("El total es RD$ 100")
    assert voice_checks.amount_reasons("Son RD$1,500.00") == []


def test_two_questions_in_one_reply_are_reported():
    """A specialist between clients answers the last one, and the first is lost."""
    assert "more than one question" in voice_checks.reply_reasons("¿Cuál? ¿La de gel?")


# --- this repository's own strings ------------------------------------------


def test_there_are_strings_to_check():
    # A discovery walk that finds nothing passes every test below it in silence.
    assert len(SPECIALIST_FACING) >= 10


@each_string
def test_every_fixed_string_speaks_to_the_specialist_as_tu(where, text):
    assert voice_checks.usted_reasons(text) == [], where


@each_string
def test_no_fixed_string_carries_markup_the_transport_drops(where, text):
    assert voice_checks.markdown_reasons(text) == [], where


@each_string
def test_no_fixed_string_asks_two_questions_at_once(where, text):
    assert voice_checks.question_reasons(text) == [], where


@pytest.mark.parametrize("reader_is_her", [True, False])
def test_both_voices_of_the_end_of_day_line_read_as_tu(reader_is_her):
    """A rendered template carries no `*_MSG` name, so the discovery above cannot see it — and
    the third person is one "su" away from usted over the very nouns §1 lists."""
    from aziza_adk import receipts

    out = receipts.render_day(
        "Zenaida",
        datetime.date(2026, 8, 27),
        services_total=decimal.Decimal("8400.00"),
        commission_pct=40,
        commission=decimal.Decimal("3360.00"),
        tips=decimal.Decimal("650.00"),
        owed_products=decimal.Decimal("15.00"),
        payday=datetime.date(2026, 8, 29),
        reader_is_her=reader_is_her,
    )
    assert voice_checks.usted_reasons(out) == []


def test_a_clients_history_reads_as_tu():
    """A report ABOUT a client is where "su" gets written — and `_POSSESSIVE_NOUNS` holds
    `clienta`, `total` and `día`. No `*_MSG` name, so nothing else can see this one."""
    from aziza_adk import receipts

    out = receipts.render_client_history(
        "Carmen",
        [
            receipts.Visit(
                day=datetime.date(2026, 8, 22),
                items="Manicura normal",
                total=decimal.Decimal("300.00"),
                specialist="Yamilé",
                left_owing=decimal.Decimal("100.00"),
            )
        ],
        total_visits=8,
        billed=decimal.Decimal("4350.00"),
        balance=decimal.Decimal("100.00"),
        first_visit=datetime.date(2026, 3, 14),
        phone="809-555-0101",
    )
    assert voice_checks.usted_reasons(out) == []
    assert voice_checks.markdown_reasons(out) == []


@pytest.mark.parametrize("walk_in", [False, True])
def test_a_ticket_that_says_more_than_the_work_reads_as_tu(walk_in):
    """The other template this repository renders without a constant to discover. Both extras
    speak ABOUT the client rather than to the reader, which is where "su" gets written."""
    from aziza_adk import receipts

    line = receipts.Line("Manicura", 1, decimal.Decimal("300.00"), decimal.Decimal("300.00"))
    out = receipts.render_ticket(
        "Carmen",
        [line],
        decimal.Decimal("300.00"),
        owed_from_before=decimal.Decimal("200.00"),
        walk_in=walk_in,
    )
    assert voice_checks.usted_reasons(out) == []
