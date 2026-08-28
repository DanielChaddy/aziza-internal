"""docs/BRAND_VOICE.md as regexes, run over every reply the assistant produces.

Two consumers, and the second is what makes this worth having: `eval/eval_runner.py` scores live
replies with it, and `tests/test_voice.py` runs it over every fixed string this repository ships.
Pure — no model, no database, no framework — so its own logic can be gated by the deterministic
suite while the checks themselves run against real conversations.

The Spanish here is the SUBJECT of the checks rather than their medium.
"""

from __future__ import annotations

import re
import unicodedata

#: The formal register this assistant must never use. Specialists are colleagues — §1.
_USTED_PRONOUNS = re.compile(r"\b(usted|ustedes)\b", re.IGNORECASE)
_USTED_POSSESSIVE = re.compile(
    r"\bsu (cuenta|clienta|comisi[óo]n|propina|d[íi]a|total)\b", re.IGNORECASE
)

#: Formal imperatives, UNFOLDED and accent-sensitive on purpose: "envié" is an ordinary
#: first-person past and "envíe" is the usted imperative, and they differ by one accent. A folded
#: check calls the correct sentence formal on nearly every conversation, which is how a gate
#: stops being read.
_USTED_IMPERATIVES = (
    "envíe",
    "llame",
    "revise",
    "confirme",
    "verifique",
    "dígame",
    "escriba",
    "espere",
    "comuníquese",
    "indíqueme",
    "disculpe",
)

#: Figures this assistant must never write itself — §3. A bare number beside a currency mark that
#: no tool produced is the failure this catches; the tools always emit the grouped form.
_LOOSE_AMOUNT = re.compile(r"RD\$\s")

#: Formatting the transport cannot render. The channel sends plain text with no parse mode, so
#: markup arrives as literal characters — §5.
_MARKDOWN = (
    (re.compile(r"\*\*"), "double-asterisk bold, which arrives as literal asterisks"),
    (re.compile(r"^#{1,6}\s", re.MULTILINE), "a markdown header, which arrives literally"),
    (re.compile(r"^\s*\|.*\|", re.MULTILINE), "a table, which is unreadable on a phone"),
)


def fold(text: str) -> str:
    """Lowercase and accent-stripped, for the checks that must survive missing accents."""
    stripped = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn").lower()


def usted_reasons(text: str) -> list[str]:
    """Every way `text` addresses a specialist formally. Empty means it reads as "tú"."""
    reasons = []
    if _USTED_PRONOUNS.search(text or ""):
        reasons.append("says 'usted'")
    if _USTED_POSSESSIVE.search(text or ""):
        reasons.append("uses the formal possessive 'su'")
    for verb in _USTED_IMPERATIVES:
        if re.search(rf"\b{verb}\b", text or "", re.IGNORECASE):
            reasons.append(f"formal imperative '{verb}'")
    return reasons


def is_tu(text: str) -> bool:
    return not usted_reasons(text)


def markdown_reasons(text: str) -> list[str]:
    return [why for pattern, why in _MARKDOWN if pattern.search(text or "")]


def amount_reasons(text: str) -> list[str]:
    """An amount written loosely. Every figure the assistant sends came from a tool already
    formatted, so a space after the currency mark means it was retyped."""
    return ["an amount the assistant wrote itself"] if _LOOSE_AMOUNT.search(text or "") else []


def question_reasons(text: str) -> list[str]:
    """More than one question in a reply. A specialist between clients answers the last one and
    the first is lost — §4."""
    return ["more than one question"] if (text or "").count("?") > 1 else []


def reply_reasons(text: str) -> list[str]:
    """Everything wrong with one live reply, for the eval to report."""
    return (
        usted_reasons(text) + markdown_reasons(text) + amount_reasons(text) + question_reasons(text)
    )
