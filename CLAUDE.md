# CLAUDE.md

Guidance for working in this repository. The shared rules — tiers, documents, the board, naming,
comments — are `agent-platform/CLAUDE.md` and are not repeated here. This file holds what is true
of **this** repository only.

## What this is

The Salón Aziza assistant: a consumer of `agent-platform`, beside `medical`, `concierge` and
`banking`. The design is [`docs/PROJECT_DEFINITION.md`](docs/PROJECT_DEFINITION.md), the voice is
[`docs/BRAND_VOICE.md`](docs/BRAND_VOICE.md), and how to run it is the root
[`README.md`](README.md). Read the design document before changing the schema, the tools or the
guards; read the voice document before writing a single Spanish string.

## The trap

**The user is a specialist, not a client.** Every sibling assistant answers the person being
served; this one answers the person doing the serving. A string copied from any of them arrives
in the wrong register and often in the wrong role — `medical` and `concierge` are formal-*usted*,
and `banking` is warm-*tú* to a customer, which is not the same as brisk-*tú* to a colleague.

A specialist-facing constant is named `*_MSG` or `*_TEXT`. That convention is not cosmetic:
`tests/test_voice.py` discovers strings by it, so one added outside it is ungated.

## Commands

```bash
make check                            # lint + the deterministic gate. What the pipeline runs.
make lint                             # ruff check AND ruff format --check — both halves
make format
make test

REQUIRE_DB=1 make test                # an absent database becomes a failure, not a skip

docker compose up -d --wait db && ./.venv/bin/python scripts/seed_mock.py
adk web                               # pick `aziza_adk`
./.venv/bin/python scripts/daily_summary.py --date $(date +%F)
```

The venv is Python 3.12, built with `uv venv --python 3.12 --seed .venv`.

## Three things to know before editing

**A price is never an argument.** No tool takes one, and none ever should. `add_service` resolves
what the specialist said against the catalog and reads the price off the row it found. The moment
a price can arrive from the model, the salon's own figures stop being the ones on the receipt.

**Identity is resolved at the edge, not in a tool.** `channel.py` matches the Telegram id against
`specialists` before the Runner runs, and an unregistered sender never reaches the graph. Tools
read the specialist from session state and never from an argument. A commission is what a person
is paid; there must be no parameter in which a model could name someone it is not.

**Money is `Decimal` and `NUMERIC(12,2)`, everywhere, with no exceptions.** If you find yourself
reaching for a float, or writing arithmetic into a prompt, the change is wrong.

## Where a behaviour belongs

| It is about | It goes in |
|---|---|
| reading or writing data | `queries.py`, which is the only module that opens a connection |
| what a spoken phrase resolves to | `catalog.py`, and `tests/test_catalog.py` |
| an amount, a rate, a rounding | `money.py`, and `tests/test_money.py` |
| what a specialist reads | `receipts.py`, against `docs/BRAND_VOICE.md` |
| who may do what | `guards.py` and the tool body, never a prompt alone |
| the fictitious salon | `demo_data.py`, which the seeder and the tests both read |
| how a reply sounds | `prompts/common.py`, against `docs/BRAND_VOICE.md` |

`money.py`, `catalog.py`, `receipts.py` and `demo_data.py` reach no database and no model, and
that is load-bearing rather than tidy: the commission arithmetic, the split-payment balance and
the rendered template are the behaviours that must be assertable, and an assertion that reaches a
database is one the gate can skip.

## Tests

Every file under `tests/` reaches no model, no network and no key. Three quarters of them reach no
database either; the rest skip without one, and `REQUIRE_DB=1` turns those skips into failures.

`tests/test_agents.py` asserts the input screen's **attachment**, discovered from the built graph.
If you change how the graph is built, check that test still goes red when the screen is removed by
hand — an attachment test that cannot fail is worse than none.

The eval is the other layer and is never wired into `pytest` — a case flips run-to-run even at
temperature 0, so it can show a conversation is good and can never hold a behaviour still.
