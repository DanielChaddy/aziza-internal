# Salón Aziza — assistant definition

The owner of what this service does and why it is shaped the way it is. Comments in the code cite
it by `§`. What each shared package holds is `agent-platform`'s `README.md` and it is the owner;
this document cites it rather than describing it again.

## §1 · Who the user is

**The users are the salon's specialists, not its clients.** A specialist opens a chat with the
Telegram bot between clients, says who she worked on and what she did, gets a priced ticket back,
charges the client, and at the end of the day receives what she earned.

No client ever talks to this assistant. That inverts every assumption the sibling assistants make
about the person on the other end, and two of them are load-bearing: the register is that of a
colleague rather than a customer (`docs/BRAND_VOICE.md`), and the sender is known in advance
rather than earning trust during the conversation (§3).

## §2 · Scope

In scope: recording services against a named client, pricing them from the salon's catalog at the
price that client pays, selling the client a product, taking payment across one or more methods,
recording a tip, closing the sale against the specialist who did the work, charging a specialist
for what she takes for herself, recording what she pays against that, and reporting each
specialist's day.

An owner does all of the above against a named specialist as well as herself, and may
read that specialist's day.

Out of scope, and the assistant says so rather than improvising: appointments, changing a price,
discounts, another specialist's figures **when the sender is not an owner**, anything
about a client beyond her name and which of the salon's two price columns she reads.

## §3 · Identity, and why it is not a conversation

**A sale carries a commission, so who did the work is never a value the sender types.** The
Telegram user id is matched against a pre-registered row in `specialists` at the edge of the
service — in `aziza_adk/channel.py`, before the Runner is invoked. An unregistered sender gets one
fixed line, no model call and no session.

This is the opposite of what a customer-facing assistant does, and the reason is the opposite too:
there, the sender authenticates nobody and must earn access through a conversation; here, the id
matched against a pre-registered row *is* the credential.

**A specialist may only record services in a discipline she holds.** The relation is many-to-many:
someone who does both wax and nails holds both, and is not a third discipline. The check is
deterministic and lives in `tools.add_service`, where the resolved service's discipline is in hand.
It is checked against the discipline of the specialist the work is BOOKED to, not of the sender —
an owner entering a wax service for a nails specialist is the same wrong booking as the specialist
doing it herself.

**Roles and disciplines are independent, and both are additive.** A discipline is what a person
may record; a role is what she may do beyond her own work. Someone can hold either, both or
neither, and the pair is two many-to-many relations rather than one column, because an owner who
also does wax is not a third kind of person.

**An owner is the caller that names somebody else, and the naming is not the model's to invent.**
The `owner` role is the authorization, read off the row the edge resolved and enforced in
`guards.before_tool_guard`, so no wording inside a turn can reach it. Three properties hold it
together:

- **Naming is required of an owner who does no salon work.** She has no work of her own for an
  unnamed entry to belong to, so it is refused rather than attributed to her; omission is the
  silent failure here, and a commission is what a person is paid. An owner who *does* hold a
  discipline is recording her own work when she names nobody, which is the ordinary case.
- **The name resolves deterministically.** `staff.py` matches what she said against the salon's
  own roster through the same resolver the catalog uses, so two specialists sharing a first name
  come back as two candidates and she says which. The roster is everyone holding a discipline:
  someone with none has nothing to book to, and someone who cannot type is still on it, because
  the salon records her work whether or not she can enter it.
- **Both halves are recorded, and one is shown.** `specialist_id` is whose work it is and
  `recorded_by` is who typed it, always set and never NULL, so the audit trail cannot be confused
  with a lost one. The ticket names whose work it is whenever somebody else entered it — the same
  reasoning as naming the client, applied to the other thing that could be wrong.

## §4 · The ticket

One open ticket per specialist, enforced by a partial unique index rather than by a check in the
tool — the index holds under a race and the tool's own check exists only to say it kindly.

**A line's price is a snapshot.** `sale_lines.unit_price` and `service_name` are copied from the
catalog when the line is added, so a later price change cannot alter a ticket already quoted. What
the client agreed to is read from the frozen row, never re-derived.

**Correcting the client is the one thing that re-prices a ticket, and it is not an exception to
that rule.** The snapshot protects a quote from a later CATALOG edit. When the client was wrong,
the quote was wrong, and a ticket whose lines disagreed with the client it names would be the
actual defect. It is refused outright where a line already on the ticket has no price for the new
client: dropping that line silently would rewrite something she has read.

**The confirm-first gate is keyed on the total as well as the ticket.** A gate that knew only
which ticket had been shown would go on authorizing a figure that has since moved — re-pricing
shifts it by as much as RD$550. Every path that changes a total re-shows it, and keying the gate
on the amount is what makes that a property rather than a habit.

**The template is rendered in Python, not composed by the model.** `aziza_adk/receipts.py` builds
the ticket and the receipt from Decimals; the tools return the rendered text and the prompt
instructs the agent to send it as it came. Every figure the specialist reads came out of a tool.

## §5 · The catalog

**A service the salon does not sell is refused, never invented, and never priced.** What the
specialist said is resolved against the catalog by `aziza_adk/catalog.py` — accent-folded, in her
own words, aliases included. Three passes, narrowest first: the full name, an alias, then
containment. A phrase naming two services comes back as both, and the agent asks which; picking
the first of two prices is a wrong receipt, which is worse than one more question.

There is no price argument on any tool. The price is the catalog row's.

**A row carries two prices, and which one applies is not the model's to decide.** Many services
cost a different amount for a man than for a woman, so `price_female` and `price_male` are both
columns and `catalog.price_for` picks between them from the client the TICKET already names.
Choosing the column is choosing the price, so the same rule that keeps a price out of a tool
argument keeps this out of the model.

**A NULL is not a zero.** Where the salon offers a service to one client only — Brasilero to
women, Barba to men — the other column is NULL and the service is refused with a reason. Reading
across to the column that does have a figure would charge a price the salon never set.

**Which column a name selects is a table, and the ticket says when it guessed.** `names.py` holds
common given names and answers with a provenance: `matched` when the name is known, `defaulted`
when it is not or when it genuinely goes both ways. A defaulted ticket is priced female AND says
so, so a wrong guess is a line the specialist can see before money moves rather than RD$550 lost
in silence. The tables cannot be exhaustive; that is what the notice is for.

**Products resolve through the same resolver.** A product is a catalog row with a name and
aliases, so it reuses `catalog.resolve` rather than a second implementation, and ambiguity behaves
identically for both.

## §6 · The data

`db/schema.sql` is the implementation and is the owner of the columns. What matters about its
shape:

- Money is `NUMERIC(12,2)` in the database and `Decimal` in Python, end to end. A float cannot
  hold RD$1,500.10 exactly, and a cent lost per sale is a discrepancy nobody can reconstruct.
- A payment is a row, not a column, because a client may settle across cash, card and transfer.
  The ticket stays open until the payments cover the total.
- The tip rides on the payment that carried it and is **not** part of its amount.
- `daily_summaries` carries a unique key on (specialist, day). That key is the claim in §8.
- A service carries two price columns, either of which may be NULL; a `CHECK` refuses a row with
  neither, so a service nobody can be charged for cannot exist (§5).
- Product lines are their own table beside service lines, and the specialist's ledger is a third.
  Both separations are what make the commission base structural rather than remembered (§7).

## §7 · What a specialist earns

**Commission is 40% of the services subtotal, taken before any tip.** The rate is
`COMMISSION_PCT`, one configuration value rather than a per-person column — a per-person split is
a schema change when a real one appears, not a guess made today.

**Tips are the specialist's in full.** A tip folded into the amount would be taxed at the
commission rate, which is why the two are separate columns and separate arguments.

**A product pays her nothing, and that is structural rather than a rule to remember.** A product
sold to a client is a row in `sale_product_lines` and a figure in `sales.products_total`, both
kept apart from the service line table and `services_total`. The commission base is therefore
`services_total` by construction: there is no query that could sweep a product into the figure a
person is paid on by forgetting a `WHERE`.

**What she takes for herself is a debit, not a sale.** She buys at `price_specialist`, which no
client is ever charged, and it never touches a client's ticket. The salon lets her settle it the
same day or carry it to pay-day, so `specialist_ledger` is a ledger of purchases and payments and
the balance is their difference, never a stored number. A settled flag per purchase could not
express a part payment, which is the ordinary case rather than the exception.

What she made is commission + tips. The end-of-day message shows all four figures — services,
commission with its rate beside it, tips, and the total — so the arithmetic can be checked by
hand. A figure that appears from nowhere is the kind people dispute later. Products sold and the
whole outstanding balance are reported beside them: the balance is shown rather than subtracted,
because taking it off today's figure would state a deduction nobody has made.

## §8 · The end of the day

`scripts/daily_summary.py` sends each specialist who billed that day one message. Telegram needs
no approved template and has no reply window, so it is a plain send.

Idempotent by construction rather than by care: the `daily_summaries` row is claimed before the
message goes out and committed only once the send has succeeded. A failed send rolls the claim
back and the next run retries; a second run after a good one claims nothing.

**A simulated run records nothing.** `SUMMARY_SEND_MODE=simulate` logs what would be sent and
writes no claim — a dry run that marks the work as done permanently silences the people it was
rehearsing for.

The business date is the salon's local date at closing, passed in rather than taken from `now()`,
so a night that runs past midnight belongs to the day it began.

## §9 · The transport

Telegram, over `channel-telegram`. The webhook is authenticated by the secret registered at
`setWebhook` — there is no signature and no verification handshake, so a payload is trusted only
as far as the transport that carried it, and the specialist table is the real gate.

A voice note takes the same path a typed message does: the channel transcribes it through
`agent-transcription` and runs the text as an ordinary turn, so it is screened by whatever screens
text rather than arriving as a shape no guard reads.

Replies are plain text with no parse mode. One unescaped character in the platform's markup
dialect rejects the whole message, and a reply full of prices and decimal points is the worst case
for that — a rejected body is silence, not a formatting glitch.

## §10 · Testing

The deterministic suite is the regression gate and reaches no model and no network. Three
quarters of it needs no database either: the money, the catalog resolution and the rendered
templates are asserted from values alone, which is what lets the arithmetic behind a commission be
held at all. `REQUIRE_DB=1` turns an absent database from skips into failures.

The eval is the second layer, over the wording and the shape of a turn, and is never wired into
`pytest` — a case flips run-to-run even at temperature 0.

## §11 · What is open

This repository's GitHub issues, and nothing here keeps a second copy. The one exception is work
that spans the platform and its consumers: an item ordering a package's tag against this
repository's pin cannot live where neither the package nor the sibling is, so it sits on the board
the siblings use.
