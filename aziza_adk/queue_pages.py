"""The documents a client's browser renders, as pure string functions.

No database, no clock, no framework — the caller hands in what it read, so every page is a value a
test can assert. Every interpolation goes through `agent_webview.spec.esc`, which is the one escape
and is not reimplemented here. docs/PROJECT_DEFINITION.md §13.

The words are `queue_text`; this module holds only structure. There is deliberately no `<script>`
and no external reference of any kind, which is what lets the join route's policy deny both
outright rather than allow-list its way around them.
"""

from __future__ import annotations

from agent_webview.spec import esc

from aziza_adk import queue_text as copy

#: One `<style>` block, inline because the policy denies every external fetch and a stylesheet is
#: one. Sized for a phone held one-handed in a salon.
_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 17px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
       background: #faf7f5; color: #1c1917; }
main { max-width: 30rem; margin: 0 auto; padding: 1.75rem 1.25rem 3rem; }
h1 { font-size: 1.15rem; font-weight: 600; letter-spacing: .02em; margin: 0 0 1.5rem;
     color: #7c4a53; }
h2 { font-size: 1.35rem; font-weight: 600; margin: 0 0 .5rem; }
p { margin: 0 0 1rem; }
label.q { display: block; font-weight: 600; margin: 1.5rem 0 .5rem; }
input[type=tel], input[type=text] { width: 100%; padding: .8rem .9rem; font-size: 1.05rem;
     border: 1px solid #d6cdc8; border-radius: .6rem; background: #fff; color: inherit; }
.hint { font-size: .9rem; color: #6b625d; margin: .4rem 0 0; }
.choice { display: flex; align-items: center; gap: .7rem; padding: .8rem .9rem; margin: .5rem 0;
     border: 1px solid #d6cdc8; border-radius: .6rem; background: #fff; }
.choice input { width: 1.15rem; height: 1.15rem; accent-color: #7c4a53; }
button { width: 100%; margin-top: 1.75rem; padding: .9rem; font-size: 1.05rem; font-weight: 600;
     color: #fff; background: #7c4a53; border: 0; border-radius: .6rem; }
.problem { padding: .8rem .9rem; margin: 0 0 1rem; border-radius: .6rem;
     background: #fbe9e7; color: #8a2f22; font-size: .95rem; }
.turn { padding: 1rem 1.1rem; margin: 1rem 0 0; border-radius: .6rem; background: #fff;
     border: 1px solid #e4dcd7; font-weight: 600; }
@media (prefers-color-scheme: dark) {
  body { background: #17140f; color: #f0ebe6; }
  h1 { color: #e0b0b8; }
  input[type=tel], input[type=text], .choice, .turn { background: #221d18; border-color: #3a322c; }
  .hint { color: #a49a93; }
  .problem { background: #3a1f1a; color: #f5c1b6; }
}
"""


def _shell(body: str) -> str:
    """The document around every page.

    `lang` is on the root element so a screen reader pronounces Spanish and a browser does not
    offer to translate it. `viewport` because without it a phone renders at desktop width and
    every tap target is too small to hit.
    """
    return (
        "<!doctype html><html lang=es><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{esc(copy.TITLE_CLIENT_COPY)}</title>"
        f"<style>{_STYLE}</style></head><body><main>"
        f"<h1>{esc(copy.TITLE_CLIENT_COPY)}</h1>{body}"
        "</main></body></html>"
    )


def _problem(message: str) -> str:
    return f"<p class=problem>{esc(message)}</p>" if message else ""


def notice(message: str) -> str:
    """A page that only says something: a stale code, an unusable link, a closed salon."""
    return _shell(f"<p>{esc(message)}</p>")


def join_form(
    action: str,
    areas: tuple[tuple[str, str], ...],
    *,
    phone: str = "",
    name: str = "",
    chosen: tuple[str, ...] = (),
    problem: str = "",
    ask_name: bool = False,
) -> str:
    """The form she fills in, re-rendered with what she already typed when something is missing.

    `action` is where the form posts, built by the router so the path is spelled once.
    `areas` is (code, Spanish name) read from the salon's own table, so nothing here holds a
    second copy of what the salon does. The name field is asked for only once the phone has turned
    out to be one the salon does not know — a client it does know reaches the line in one POST,
    which is what "she just scans and she is in" has to mean (§13).
    """
    checks = "".join(
        f'<div class=choice><input type=checkbox id="a-{esc(code)}" name=areas '
        f'value="{esc(code)}"{" checked" if code in chosen else ""}>'
        f'<label for="a-{esc(code)}">{esc(label)}</label></div>'
        for code, label in areas
    )
    name_field = (
        f"<label class=q for=name>{esc(copy.ASK_NAME_CLIENT_COPY)}</label>"
        f'<input id=name name=name type=text autocomplete="name" '
        f'value="{esc(name)}" required>'
        if ask_name
        else ""
    )
    return _shell(
        f"{_problem(problem)}"
        f'<form method=post action="{esc(action)}">'
        f"{name_field}"
        f"<label class=q for=phone>{esc(copy.ASK_PHONE_CLIENT_COPY)}</label>"
        f'<input id=phone name=phone type=tel inputmode=numeric autocomplete="tel" '
        f'value="{esc(phone)}" required>'
        f"<p class=hint>{esc(copy.PHONE_HINT_CLIENT_COPY)}</p>"
        f"<label class=q>{esc(copy.ASK_AREAS_CLIENT_COPY)}</label>{checks}"
        f"<button type=submit>{esc(copy.CONTINUE_CLIENT_COPY)}</button></form>"
    )


def which_one(
    action: str,
    candidates: tuple[tuple[int, str], ...],
    *,
    phone: str,
    chosen: tuple[str, ...],
) -> str:
    """Which of the clients on one number she is.

    A number reaches a mother and her daughter, and the pair is the identity — so the half she
    still has to supply is the name, and it is offered rather than typed (§3).
    """
    options = "".join(
        f'<div class=choice><input type=radio id="c-{client_id}" name=client_id '
        f'value="{client_id}"{" checked" if index == 0 else ""}>'
        f'<label for="c-{client_id}">{esc(name)}</label></div>'
        for index, (client_id, name) in enumerate(candidates)
    )
    carried = "".join(f'<input type=hidden name=areas value="{esc(code)}">' for code in chosen)
    return _shell(
        f'<form method=post action="{esc(action)}">'
        f'<input type=hidden name=phone value="{esc(phone)}">{carried}'
        f"<label class=q>{esc(copy.WHICH_ONE_CLIENT_COPY)}</label>{options}"
        f"<button type=submit>{esc(copy.CONTINUE_CLIENT_COPY)}</button></form>"
    )


def joined(name: str, turns: tuple[tuple[str, int | None], ...], *, already: bool) -> str:
    """What she reads once she is in the line, and where she stands in each of them.

    A position of None is a line she is in but cannot be given a number for, which is what being
    in a chair looks like from here — so it says to wait rather than inventing a figure (§12).
    """
    headline = copy.ALREADY_CLIENT_COPY if already else copy.JOINED_CLIENT_COPY
    places = "".join(
        "<p class=turn>"
        + esc(
            copy.POSITION_NEXT_CLIENT_COPY.format(area=area)
            if position == 1
            else copy.POSITION_CLIENT_COPY.format(area=area, position=position)
        )
        + "</p>"
        if position is not None
        else ""
        for area, position in turns
    )
    return _shell(
        f"<h2>{esc(headline.format(name=name))}</h2>"
        f"{places}<p class=hint>{esc(copy.WAIT_CLIENT_COPY)}</p>"
    )
