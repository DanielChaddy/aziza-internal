# CLAUDE.md

Guidance for working in this repository. The shared rules — tiers, documents, naming, comments —
are `agent-platform/CLAUDE.md` and are not repeated here. This file holds what is true of **this**
repository only. Open items are this repository's own GitHub issues, except the ones that order a
platform tag against this repository's pin — docs/PROJECT_DEFINITION.md §11 owns that distinction.

## What this is

The Salón Aziza assistant: a consumer of `agent-platform`, beside `medical`, `concierge`, `bhd`
and `banreservas`. The design is [`docs/PROJECT_DEFINITION.md`](docs/PROJECT_DEFINITION.md), the
voice is [`docs/BRAND_VOICE.md`](docs/BRAND_VOICE.md), and how to run it is the root
[`README.md`](README.md). Read the design document before changing the schema, the tools or the
guards; read the voice document before writing a single Spanish string.

## In development

**This project is IN DEVELOPMENT, and its databases are disposable.** `dev-db-pgsql` is a test
database in a shared environment: nothing in `aziza` or `aziza_sessions` is the salon's record of
anything yet, and what is there is somebody exercising the assistant. So a schema change is
applied by dropping and rebuilding rather than by migrating in place — `db/schema.sql` states the
shape it wants and carries no `ALTER`, and the rebuild in
[`deploy/helm/README.md`](deploy/helm/README.md) needs no permission first.

This is the one thing in this file with an end date, and the date is not set. Until it is lifted,
do not describe that database as production, and do not let a row in it stop a change.

## The trap

**The user is a specialist, not a client.** Every sibling assistant answers the person being
served; this one answers the person doing the serving. A string copied from any of them arrives
in the wrong register and often in the wrong role — `medical` and `concierge` are formal-*usted*,
and `bhd` is warm-*tú* to a customer, which is not the same as brisk-*tú* to a colleague.

A specialist-facing constant is named `*_MSG` or `*_TEXT`. That convention is not cosmetic:
`tests/test_voice.py` discovers strings by it, so one added outside it is ungated.

**A CLIENT-facing constant is named `*_CLIENT_COPY` and lives in `queue_text.py`.** She is the one
audience this repository has that is not a colleague — `docs/BRAND_VOICE.md` §8 — and the suffix is
what keeps the two sweeps apart. A client string named `*_MSG` is gated against the wrong register.

## Commands

```bash
make check                            # lint + the deterministic gate. What CI runs.
make lint                             # ruff check AND ruff format --check — both halves
make format
make test

REQUIRE_DB=1 make test                # an absent database becomes a failure, not a skip

docker compose up -d --wait db
./.venv/bin/python scripts/seed_catalog.py --with-demo-specialists   # the flag is local-only
adk web                               # pick `aziza_adk`
./.venv/bin/python scripts/daily_summary.py --date $(date +%F)
```

The venv is Python 3.12, built with `uv venv --python 3.12 --seed .venv`.

## Three things to know before editing

**A price is never an argument.** No tool takes one, and none ever should. `add_service` resolves
what the specialist said against the catalog and reads the price off the row it found. The moment
a price can arrive from the model, the salon's own figures stop being the ones on the receipt.

The one place the salon has no figure of its own is a supplier's invoice, and the answer there is
the same shape: `register_expense` takes no amount either. Every figure comes off the row she was
shown, and `fiscal_do` refuses one that does not add up — docs/PROJECT_DEFINITION.md §15.

**Identity is resolved at the edge, not in a tool.** `channel.py` matches the Telegram id against
`specialists` before the Runner runs, and an unregistered sender never reaches the graph. The
SENDER is never an argument, and that half has no exceptions.

**Whose work it is can be an argument, and only for an owner.** `on_behalf_of` is the one
parameter that can move a commission to a person the sender is not, so it is gated on the `owner`
role in `guards.before_tool_guard` — off the row the edge resolved, where no wording in a turn
reaches it — and re-checked in the tool body. Naming is REQUIRED of an owner who holds no
discipline, because she has no work of her own for an unnamed entry to belong to and a sale in her
name is a commission paid to the wrong person; an owner who does hold one is recording her own
work when she names nobody. The name resolves deterministically through `staff.py`, two people
called Yamilé come back as two candidates, `sales.recorded_by` records who typed it, and the
ticket says *Trabajo de* so she reads the attribution before the money moves.

**Roles and disciplines are separate, additive and both many-to-many.** A discipline is what she
may record, a role is what she may do beyond her own work, and a person holds any mix of them.
`staff_data.py` is the dataset for both. A Telegram id of `None` there is someone whose work the
salon records and who cannot yet talk to the assistant — never the empty string, which the edge
would match against a sender who supplied nothing.

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
| when the salon is open | `hours.py`, asserted through the guard in `tests/test_guards.py` |
| when a pay period runs, and its pay-day | `pay.py`, and `tests/test_pay.py` |
| what the salon sells and charges | `catalog_data.py`, which the seeder and the tests both read |
| who really works here | `staff_data.py` — a Telegram id in it is a credential, not a label |
| the invented specialists | `demo_data.py`, seeded only behind `--with-demo-specialists` |
| which specialist a spoken name means | `staff.py`, and `tests/test_staff.py` |
| which client a name and a number mean | `clients.py`, and `tests/test_clients.py` |
| who is waiting, and who is next | `arrivals.py`, and `tests/test_arrivals.py` |
| the code a client scans | `join.py` and `qr.py`, and `tests/test_join.py`, `tests/test_qr.py` |
| what a CLIENT reads | `queue_text.py` (`*_CLIENT_COPY`), against `docs/BRAND_VOICE.md` §8 |
| the page she fills in | `queue_pages.py` and `queue_form.py`, `queue_http.py` for the routes |
| whether a mini-app launch is real | `init_data.py`, and `tests/test_init_data.py` |
| what one client has had done | `queries.client_visits`, `tools.client_history`, §3 |
| who comes, who spends, who stopped | `tools.salon_clients`, `tools.lapsed_clients`, §3 |
| what a client owes, and change | `queries.client_*`, `tools.record_payment`, §7 |
| the register, and what it should hold | `queries.expected_register`, `tools.close_register`, §7 |
| which price column a client reads | `names.py`, and `tests/test_names.py` |
| what an invoice must look like | `agent-platform` `packages/fiscal-do/`, §15 |
| what the salon bought, and the register | `queries.record_expense`, `tools.draft_expense`, §15 |
| what a large invoice is, and how she paid | `money.LARGE_EXPENSE_THRESHOLD`, `tools.FORMA_PAGO`, §15 |
| the file DGII is sent | `agent-platform` `packages/fiscal-do/`, §15 |
| the link she taps for a report | `reports.py` and `report_http.py`, §15 |
| how a reply sounds | `prompts/common.py`, against `docs/BRAND_VOICE.md` |

`money.py`, `catalog.py`, `names.py`, `staff.py`, `clients.py`, `arrivals.py`, `receipts.py`,
`hours.py`, `pay.py`, `join.py`, `qr.py`, `queue_form.py`, `queue_pages.py`, `init_data.py`,
`reports.py`,
`catalog_data.py`, `staff_data.py` and `demo_data.py` reach no database and no model,
and that is load-bearing rather than tidy: the commission arithmetic, the split-payment balance,
the price column a name selects, which of two Marías a number means and the rendered template are
the behaviours that must be assertable, and an assertion that reaches a database is one the gate
can skip. `hours.py` takes it further and holds no CLOCK either — the moment is a parameter, and
`tools.now` is the one wall-clock read on the turn path, so "refused at 20:01 on a Tuesday" is a
value rather than an evening spent waiting.

## Tests

Every file under `tests/` reaches no model, no network and no key. Three quarters of them reach no
database either; the rest skip without one, and `REQUIRE_DB=1` turns those skips into failures.

`tests/test_agents.py` asserts the input screen's **attachment**, discovered from the built graph.
If you change how the graph is built, check that test still goes red when the screen is removed by
hand — an attachment test that cannot fail is worse than none.

The eval is the other layer and is never wired into `pytest` — a case flips run-to-run even at
temperature 0, so it can show a conversation is good and can never hold a behaviour still.
