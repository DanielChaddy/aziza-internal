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
