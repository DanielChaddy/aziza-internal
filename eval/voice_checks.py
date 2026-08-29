"""docs/BRAND_VOICE.md as regexes, run over every reply the assistant produces.

Two consumers, and the second is what makes this worth having: `eval/eval_runner.py` scores live
replies with it, and `tests/test_voice.py` runs it over every fixed string this repository ships.
Pure — no model, no database, no framework — so its own logic can be gated by the deterministic
suite while the checks themselves run against real conversations.

The conjugation and the markup are `conversation_core`'s, which holds them for five consumers —
`agent-platform/docs/DIVERGENCE.md` §21 and §22. What is this salon's, and stays: which nouns
after "su" mean the reader's own, and the shape of a figure only a tool may write.

The Spanish here is the SUBJECT of the checks rather than their medium.
"""

from __future__ import annotations

import re

from conversation_core import register, reply

#: This salon's nouns for the shared check — `register.formal_reasons` says why the list is the
#: caller's. Both numbers, because it matches the noun literally and "comisiones" is not
#: "comisión" with an s.
_POSSESSIVE_NOUNS = (
    "cuenta",
    "cuentas",
    "clienta",
    "clientas",
    "comisión",
    "comisiones",
    "propina",
    "propinas",
    "día",
    "días",
    "total",
    "totales",
)

#: Figures this assistant must never write itself — §3. A bare number beside a currency mark that
#: no tool produced is the failure this catches; the tools always emit the grouped form.
_LOOSE_AMOUNT = re.compile(r"RD\$\s")


def usted_reasons(text: str) -> list[str]:
    """Every way `text` addresses a specialist formally. Empty means it reads as "tú"."""
    return register.formal_reasons(text or "", possessive_nouns=_POSSESSIVE_NOUNS)


def is_tu(text: str) -> bool:
    return not usted_reasons(text)


def markdown_reasons(text: str) -> list[str]:
    return reply.markdown_reasons(text or "")


def amount_reasons(text: str) -> list[str]:
    """An amount written loosely. Every figure the assistant sends came from a tool already
    formatted, so a space after the currency mark means it was retyped."""
    return ["an amount the assistant wrote itself"] if _LOOSE_AMOUNT.search(text or "") else []


def question_reasons(text: str) -> list[str]:
    """More than one question in a reply. A specialist between clients answers the last one and
    the first is lost — §4. The threshold is this assistant's; the counting is not."""
    return ["more than one question"] if reply.count_questions(text or "") > 1 else []


def reply_reasons(text: str) -> list[str]:
    """Everything wrong with one live reply, for the eval to report."""
    return (
        usted_reasons(text) + markdown_reasons(text) + amount_reasons(text) + question_reasons(text)
    )
