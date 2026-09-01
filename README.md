# Salón Aziza — asistente para especialistas

A Spanish-language **Telegram** assistant the specialists of Salón Aziza record their work
through, built on **Google ADK** over the shared packages in `agent-platform`. A specialist says
who she worked on and what she did — by text or by voice note — gets back a priced ticket, charges
the client across one or more payment methods, and at the end of the day receives what she earned.

**The users are the salon's staff, not its clients.** No client ever talks to this assistant.

An owner uses the same assistant and the same tools, naming the specialist an entry belongs to
when it is not her own. That name is required of an owner who does no salon work rather than
defaulted, because a sale in her name would be a commission paid to the wrong person.

Architecture at a glance:

- **One agent** (`aziza_adk/agents/sales.py`): there is nothing to route between, and it is still
  built through the platform's graph factory so the input screen is attached rather than
  remembered.
- **Twenty-three tools and two layers of guard** (`aziza_adk/tools.py`, `guards.py`): identity
  resolved at the edge before the Runner, a deterministic discipline check against the specialist
  the work is booked to, and a confirm-first gate that refuses to charge a total the specialist
  has not been shown.
- **One line for the whole salon** (`aziza_adk/arrivals.py`, `db/schema.sql`): a client keeps the
  place her arrival gave her in every area she is waiting for, and is passed over only while
  somebody has her. Both rules are one filter over one order, and neither is stored.
- **A code a client scans to put herself in it** (`aziza_adk/join.py`, `qr.py`, `queue_http.py`):
  a short-lived signed link, rotated by the specialist's Telegram Mini App
  (`aziza_adk/mini_app.py`). A client the salon knows reaches the line in one post; one it does
  not is asked her name. The token proves she was standing there, never who she is.
- **One argument that can move a commission** (`on_behalf_of`), gated on a column rather than on
  wording: refused for anyone the database does not give the `owner` role, required of an owner
  who holds no discipline, and recorded in `sales.recorded_by` alongside whose work it was.
- **A price that is never a model output** (`aziza_adk/catalog.py`): what she said is resolved
  against the salon's catalog, and the price is read off the row. Which of the row's two prices
  is decided by a table of names (`names.py`), never by the model — and the ticket says when it
  had to guess.
- **Products, which pay no commission** (`db/schema.sql`): a product line lives in its own table,
  so the figure a specialist is paid on cannot accidentally include one. What she takes for
  herself is a debit against her instead, carried on a ledger until she settles it.

---

## Prerequisites

- **Python 3.12** with a virtualenv at `.venv`.
- **Docker**, for PostgreSQL.
- A **Gemini API key** in `.env` for `adk web` and the eval. `pytest` needs none.

```bash
uv venv --python 3.12 --seed .venv         # --seed, or the venv has no pip
./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                       # then set GOOGLE_API_KEY
```

The platform packages install from a **private** Azure DevOps repository by git tag. To work
across both repositories at once, overlay the editable copies afterwards:

```bash
./.venv/bin/pip install -e ../agent-platform/packages/channel-telegram   # …and the others
```

## Run it

```bash
docker compose up -d --wait db                # Postgres 16 on :5434, two databases
./.venv/bin/python scripts/seed_catalog.py --with-demo-specialists   # idempotent
adk web                                       # pick `aziza_adk`, http://localhost:8000
```

The client's page, the mini app and the owner's report ride on the same app. With
`JOIN_LINK_SECRET` and `PUBLIC_BASE_URL` set in `.env`, `http://localhost:8080/mini-app` shows the
code and `/j/<token>` is what it points at. The 606 download is `/r/<token>` and wants
`REPORT_LINK_SECRET` and `SALON_RNC` — its own secret, never the join page's. All of them refuse
everything with no secret configured, which is the safe direction.

One turn through the channel without Telegram:

```bash
ENABLE_SIMULATE=1 ./.venv/bin/uvicorn aziza_adk.channel:app --port 8080
curl -sX POST localhost:8080/simulate -H 'content-type: application/json' \
     -d '{"sender":"700000001","text":"Le hice manicure y pedicure a Laura"}'
```

`700000001` is a seeded specialist. Any other id gets the "not registered" line and no model call
— which is the point. `/simulate` authenticates nobody: `sender` is a field the caller types, so
anybody who reaches it is any specialist whose Telegram id they know. Hence the switch, off unless
set, and no route for it in an Ingress — two layers, because a port-forward goes past the second.

### Against real Telegram

Create the bot with BotFather, then register the webhook with the same secret the service reads:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d url=https://<host>/webhook -d secret_token=<TELEGRAM_WEBHOOK_SECRET>
```

With the secret unset the webhook refuses every delivery, which is the safe direction for a
service that is not configured yet.

### The demo script

1. **Refused cold.** Message the bot from an unregistered id → one line, no session, no model call.
2. **A sale.** As a seeded specialist: *"Le hice manicura normal a Laura"* → the ticket at the
   salon's own price, RD$300.00, with no notice: Laura is a name the table knows.
3. **A word that names three prices.** *"Y una manicura"* → asked which, because three services
   begin with it at three prices and picking the cheapest would be a wrong receipt.
4. **A price that does not exist.** *"Y un corte de pelo"* → refused, with what the salon sells.
5. **The wrong area.** As a nails specialist: *"y piernas completas"* → refused.
6. **A client the table does not know.** *"Le hice piernas completas a Ariel"* → priced female at
   RD$850.00 **and said so**. *"Es hombre"* → re-priced to RD$1,400.00.
7. **A product.** *"Se llevó una Coca-Cola"* → RD$50.00 on the ticket, and no commission on it.
8. **A split payment.** *"Pagó 200 en efectivo"* → the balance. *"Y el resto con tarjeta, más 100
   de propina"* → the receipt, and the ticket closes.
9. **A voice note.** Say the same thing out loud — it takes the same path a typed message does.
10. **Her own tab.** *"Me tomé un agua"* → RD$15.00 charged to her, not to a client.
11. **The day.** *"¿Cómo voy hoy?"* → services, commission, tips, products sold, and what she owes.
12. **An owner.** As an owner who does no salon work: *"Le hice manicura normal a Laura"* → asked
    whose work it was, never booked to her. *"Yamilé le hizo manicura normal a Laura"* → the
    ticket, with *Trabajo de: Yamilé Reyes* on it, and the commission on Yamilé's day.
13. **The line.** *"Llegó Carmen para uñas y depilación"*, then *"llegó Ana para depilación"* →
    both in the salon's one line. As a nails specialist: *"¿quién sigue?"* → Carmen. Now
    *"¿quién está esperando?"* → Ana is first for depilación, because somebody has Carmen.
14. **Her place is kept.** Charge Carmen and ask again → she is ahead of Ana for depilación once
    more. Being served for one area never spends her place in the other.
15. **She puts herself in it.** Open `/mini-app` from the bot's menu button → the code, counting
    down. Scan it with a phone → the form. A number the salon knows goes straight in; a new one is
    asked for a name. Wait for the code to rotate and scan the old one → *"Este código ya venció."*

## Testing

Two layers.

```bash
make check                 # the GATE — lint + the deterministic suite. Must be green.
REQUIRE_DB=1 make test     # what CI runs: an absent database is a failure
```

- **`pytest` is the regression gate**, and it reaches no model and no network. Three quarters of
  it reaches no database either — the money, the catalog resolution and the rendered templates are
  asserted from values alone, which is what lets the arithmetic behind a commission be held at all.
  Without a database the rest skip; `REQUIRE_DB=1` turns those skips into failures. Run it and
  read the count from the run rather than from this sentence.
- **CI runs both of the commands above** on every push to `main`, weekly, and on demand:
  [`.github/workflows/ci.yml`](.github/workflows/ci.yml), on GitHub-hosted runners. Lint needs no
  credential; the test job installs the private platform pins and reads an `ADO_PAT` secret.
- **`eval/`** drives the real graph over conversational cases and scores every reply with
  `eval/voice_checks.py`. Cases flip run-to-run even at temperature 0, so it is a signal and
  deliberately not wired into `pytest`.

## The end-of-day message

```bash
SUMMARY_SEND_MODE=simulate ./.venv/bin/python scripts/daily_summary.py
```

Each specialist who billed that day gets one message: services, commission, tips, date. It is
idempotent by construction — the claim row is taken before the send and committed only once it has
succeeded — and **a simulated run records nothing**, so a dry run cannot mark a day as already
reported.

On the cluster it runs as `cronjob/aziza-summary` on the same image, at 21:00 in the salon's
own timezone. It ships set to `simulate` and sends nothing until the salon's real specialists
are registered — [`deploy/helm/README.md`](deploy/helm/README.md) is the owner of the deploy.

## The shared packages

All from `agent-platform`, pinned in `requirements.txt` by git tag. What each holds is that
repository's `README.md` and it is the owner — this table says only what *this* service takes.

| Package | What this service gets from it |
|---|---|
| `conversation-core` | the env primitives, the accent fold, the literal-date block and the context-state reader |
| `agent-adk` | the factory that builds the graph and puts the input screen on it |
| `channel-telegram` | the whole Telegram transport |
| `agent-telemetry` | the root logging configuration — one call in `channel.py`, and the OTLP provider behind it if an endpoint is ever set |
| `agent-evalkit` | the multi-run aggregate the eval reports |
| `agent-transcription` | the model call that turns a voice note into the text a turn can act on |
| `agent-webview` | the signed short-lived link the QR encodes, and the one HTML escape |

`agent-telemetry` installs **nothing** with `OTEL_EXPORTER_OTLP_ENDPOINT` unset, which is how
`adk web`, the eval, `pytest` and the deployment all run — [`deploy/helm/README.md`](deploy/helm/README.md)
owns the deployed state.

## Environment

Every variable, its default and what an empty value disables: [`.env.example`](.env.example),
implemented in `aziza_adk/config.py` and in the channel package's own `settings.py`.

## What is open

This repository's GitHub issues. Nothing here keeps a second copy, and the board the sibling
assistants use does not track this repository.
