-- Salón Aziza — business schema for database `aziza`.
-- Mirrors docs/PROJECT_DEFINITION.md §6. Idempotent: safe to apply repeatedly.
--
-- This file states the shape it wants and carries no migration. While the project is IN
-- DEVELOPMENT (CLAUDE.md) the databases are disposable, so a column that changed is reached
-- by dropping and rebuilding rather than by altering in place.
--
-- The ADK session store lives in a SEPARATE database (`aziza_sessions`), created empty by
-- db/init.sql and managed entirely by ADK (agent-platform docs/ADK_LESSONS_LEARNED.md §6a).
-- Nothing here touches it.
--
-- Money is NUMERIC(12,2) everywhere. A commission is what a person is paid, and a float cannot
-- hold RD$1,500.10 exactly.

BEGIN;

CREATE TABLE IF NOT EXISTS disciplines (
    id   SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS specialists (
    id               SERIAL PRIMARY KEY,
    specialist_ref   TEXT NOT NULL UNIQUE,
    -- THE CREDENTIAL. A sale carries a commission, so who did the work is never a value the
    -- sender types — it is this, matched at the edge before the model runs (§3).
    --
    -- NULL is someone the salon records work for who cannot yet talk to the assistant. Never the
    -- empty string: the edge matches by equality, so a blank column would admit a blank sender.
    telegram_user_id TEXT UNIQUE
                     CONSTRAINT specialists_telegram_not_blank CHECK (telegram_user_id <> ''),
    full_name        TEXT NOT NULL,
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- What a person may DO, as against what she is trained to do. Additive and many-to-many for the
-- same reason disciplines are: an owner who also does wax holds both and is not a third kind of
-- person (§3).
--
-- `owner` is the one that widens authorization — it carries naming another specialist's work,
-- closing the register, reading the salon's figures, and recording outside opening hours.
CREATE TABLE IF NOT EXISTS roles (
    id   SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS specialist_roles (
    specialist_id INTEGER NOT NULL REFERENCES specialists (id) ON DELETE CASCADE,
    role_id       INTEGER NOT NULL REFERENCES roles (id)       ON DELETE CASCADE,
    PRIMARY KEY (specialist_id, role_id)
);

-- Many-to-many, because someone who does both wax and nails holds both and is not a third
-- discipline (§3).
CREATE TABLE IF NOT EXISTS specialist_disciplines (
    specialist_id INTEGER NOT NULL REFERENCES specialists (id)  ON DELETE CASCADE,
    discipline_id INTEGER NOT NULL REFERENCES disciplines (id)  ON DELETE CASCADE,
    PRIMARY KEY (specialist_id, discipline_id)
);

CREATE TABLE IF NOT EXISTS services (
    id            SERIAL PRIMARY KEY,
    service_ref   TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL UNIQUE,
    discipline_id INTEGER NOT NULL REFERENCES disciplines (id),
    -- TWO prices, and a NULL is not a zero: it means the salon does not offer this to that
    -- client, which is a refusal with a reason rather than a fall through to the other column
    -- (§5). A service priced the same for everyone carries the same amount in both.
    price_female  NUMERIC(12, 2) CHECK (price_female >= 0),
    price_male    NUMERIC(12, 2) CHECK (price_male >= 0),
    CHECK (COALESCE(price_female, price_male) IS NOT NULL),
    currency      TEXT NOT NULL DEFAULT 'DOP',
    -- What a specialist calls it out loud, in their own words. Matched on, never shown.
    aliases       TEXT NOT NULL DEFAULT '',
    active        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS ix_services_discipline ON services (discipline_id);

-- Who owes what, and for how long. A ticket carries `client_name` as a SNAPSHOT of what the
-- specialist said; this is the person that name referred to, so a balance can outlive the ticket
-- that created it and be found again on her next visit (§7).
--
-- `phone` is what will eventually tell two people called Carmen apart. Until something asks for
-- one, a name is matched folded and a second Carmen shares the first one's row — which is why
-- the column exists now and the ambiguity is written down rather than discovered.
CREATE TABLE IF NOT EXISTS clients (
    id         SERIAL PRIMARY KEY,
    client_ref TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    -- Accent- and case-folded, so "MARÍA" and "maria" are one person. Written by the app rather
    -- than by the database, because the fold is `conversation_core.fold` and one implementation
    -- of it is the whole point.
    folded     TEXT NOT NULL UNIQUE,
    phone      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales (
    id             SERIAL PRIMARY KEY,
    sale_ref       TEXT NOT NULL UNIQUE,
    -- WHOSE WORK IT IS, and therefore who the commission belongs to.
    specialist_id  INTEGER NOT NULL REFERENCES specialists (id),
    -- WHO TYPED IT. Equal to specialist_id when she recorded her own; an owner otherwise. Always
    -- set, never NULL: a magic absence would make "she entered it" and "we lost track" the same
    -- row, and this is the audit trail for money paid to a person (§3).
    recorded_by    INTEGER NOT NULL REFERENCES specialists (id),
    -- The person, as against `client_name` which is the words the specialist used. Both, for the
    -- same reason `sale_lines` keeps a service_name beside a service_id (§4).
    client_id      INTEGER REFERENCES clients (id),
    client_name    TEXT NOT NULL,
    -- WHICH price column every line on this ticket reads (§5). Set when the ticket opens and
    -- re-priced if it changes, so a line can never disagree with the ticket it belongs to.
    client_gender  TEXT NOT NULL DEFAULT 'female'
                   CHECK (client_gender IN ('female', 'male')),
    -- How we know. 'defaulted' is the one that earns the notice on the ticket: the name was not
    -- recognized, so the female column was applied and the specialist is told (aziza_adk/names.py).
    gender_source  TEXT NOT NULL DEFAULT 'defaulted'
                   CHECK (gender_source IN ('stated', 'matched', 'defaulted')),
    -- 'partial' is CLOSED with a balance outstanding. It has to be a closing state: one open
    -- ticket per specialist is enforced below, so a client who leaves owing would otherwise stop
    -- her serving anybody else (§7).
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'paid', 'partial', 'void')),
    services_total NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (services_total >= 0),
    -- Kept apart from services_total and never added into it: commission is taken on work, and a
    -- product pays none (§7).
    products_total NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (products_total >= 0),
    -- Stamped when the sale closes, in salon-local time: a night that runs past midnight belongs
    -- to the day it started, and the end-of-day message is grouped by this.
    business_date  DATE,
    opened_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at        TIMESTAMPTZ
);

-- One open ticket per specialist, so "my current ticket" is unambiguous — and it holds under a
-- race, which a check-then-insert in the tool does not. Partial, so a closed sale frees the slot.
CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_one_open_per_specialist
    ON sales (specialist_id) WHERE status = 'open';

CREATE INDEX IF NOT EXISTS ix_sales_specialist_date ON sales (specialist_id, business_date);

-- What one person entered against another's name, which is the question an audit asks.
CREATE INDEX IF NOT EXISTS ix_sales_recorded_by ON sales (recorded_by)
    WHERE recorded_by <> specialist_id;

CREATE TABLE IF NOT EXISTS sale_lines (
    id           SERIAL PRIMARY KEY,
    sale_id      INTEGER NOT NULL REFERENCES sales (id) ON DELETE CASCADE,
    service_id   INTEGER NOT NULL REFERENCES services (id),
    -- SNAPSHOTS, both of them. A later catalog edit must not change a ticket already quoted:
    -- what the client agreed to is read from this row, never re-derived (§4).
    service_name TEXT NOT NULL,
    unit_price   NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    line_total   NUMERIC(12, 2) NOT NULL CHECK (line_total >= 0),
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_sale_lines_sale ON sale_lines (sale_id);

CREATE TABLE IF NOT EXISTS sale_payments (
    id          SERIAL PRIMARY KEY,
    sale_id     INTEGER NOT NULL REFERENCES sales (id) ON DELETE CASCADE,
    -- The salon's actual accounts, named rather than typed: 'transfer' could not say WHICH bank
    -- received it, and the register cannot be reconciled against a total nobody can attribute.
    method      TEXT NOT NULL CHECK (method IN ('cash', 'banreservas', 'bhd')),
    amount      NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    -- The tip rides on the payment that carried it and is NOT part of `amount`: commission is
    -- taken on services alone, and a tip folded into the total would be taxed at 40% (§7).
    tip         NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (tip >= 0),
    -- Handed back out of the drawer, so it is neither a payment nor a tip. `amount` is what the
    -- TICKET received; this is what left with the client, and the register is short by it (§7).
    change_given NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (change_given >= 0),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_sale_payments_sale ON sale_payments (sale_id);

-- No discipline column, deliberately: anyone may sell a drink, so nothing here is authorized
-- against what a specialist is trained to do.
CREATE TABLE IF NOT EXISTS products (
    id               SERIAL PRIMARY KEY,
    product_ref      TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL UNIQUE,
    price_client     NUMERIC(12, 2) NOT NULL CHECK (price_client >= 0),
    -- What she pays when she takes one for herself. Not a discount a client can be given: it is
    -- the amount of a debit against her (§7).
    price_specialist NUMERIC(12, 2) NOT NULL CHECK (price_specialist >= 0),
    currency         TEXT NOT NULL DEFAULT 'DOP',
    aliases          TEXT NOT NULL DEFAULT '',
    active           BOOLEAN NOT NULL DEFAULT TRUE
);

-- A SEPARATE table from sale_lines rather than a nullable service_id on that one. The commission
-- base is then `services_total` by construction: there is no query that could accidentally sweep
-- a product into the figure a person is paid on (§7).
CREATE TABLE IF NOT EXISTS sale_product_lines (
    id           SERIAL PRIMARY KEY,
    sale_id      INTEGER NOT NULL REFERENCES sales (id) ON DELETE CASCADE,
    product_id   INTEGER NOT NULL REFERENCES products (id),
    -- SNAPSHOTS, as on sale_lines and for the same reason (§4).
    product_name TEXT NOT NULL,
    unit_price   NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    line_total   NUMERIC(12, 2) NOT NULL CHECK (line_total >= 0),
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_sale_product_lines_sale ON sale_product_lines (sale_id);

-- What a specialist owes the salon for what she took, and what she has paid against it. A LEDGER
-- rather than a settled flag on each purchase: the salon lets her pay part of it whenever she
-- likes and carry the rest to pay-day, and a boolean cannot hold a part payment. The balance is
-- SUM(purchase) - SUM(payment) and is never stored.
CREATE TABLE IF NOT EXISTS specialist_ledger (
    id            SERIAL PRIMARY KEY,
    specialist_id INTEGER NOT NULL REFERENCES specialists (id) ON DELETE CASCADE,
    -- What she took, and it is two different things: a 'purchase' is a product off the shelf, a
    -- 'loan' is money out of the register. She is told them apart on her end-of-day message
    -- because they feel different to owe (§7).
    kind          TEXT NOT NULL CHECK (kind IN ('purchase', 'loan', 'payment')),
    -- Which of the two a payment pays down. NULL on a debit, where `kind` already says. Without
    -- it the two balances could only be reported gross, and a part payment would belong to both.
    settles       TEXT CHECK (settles IN ('purchase', 'loan')),
    CHECK ((kind = 'payment') = (settles IS NOT NULL)),
    -- Which account the money moved through. NULL on a purchase, where nothing moves: she took a
    -- product, and the register is no lighter for it. A loan empties the drawer and a payment
    -- fills it, so the register cannot be reconciled without this.
    method        TEXT CHECK (method IN ('cash', 'banreservas', 'bhd')),
    CHECK ((kind = 'purchase') = (method IS NULL)),
    -- As on sales: whose debt it is above, who entered it here.
    recorded_by   INTEGER NOT NULL REFERENCES specialists (id),
    -- Set on a purchase, null otherwise: a payment is against the balance, not against an item,
    -- and a loan was never an item at all.
    product_id    INTEGER REFERENCES products (id),
    description   TEXT NOT NULL,
    -- Always positive. `kind` carries the sign, so a row cannot be entered with the wrong one.
    amount        NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    business_date DATE NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_specialist_ledger_specialist
    ON specialist_ledger (specialist_id, business_date);

-- What a CLIENT owes the salon and what she has paid against it. The same shape as
-- `specialist_ledger` and for the same reason: the balance is SUM(debt) - SUM(payment), never
-- stored, so a part payment needs no new column and cannot disagree with its own history.
CREATE TABLE IF NOT EXISTS client_ledger (
    id            SERIAL PRIMARY KEY,
    client_id     INTEGER NOT NULL REFERENCES clients (id) ON DELETE CASCADE,
    -- Set on a debt, null on a payment: a payment is against the balance, not against a ticket.
    sale_id       INTEGER REFERENCES sales (id),
    kind          TEXT NOT NULL CHECK (kind IN ('debt', 'payment')),
    -- Which account received it. NULL on a debt, which is money that moved nowhere. Without this
    -- a settlement paid days later is invisible to the register it actually landed in.
    method        TEXT CHECK (method IN ('cash', 'banreservas', 'bhd')),
    CHECK ((kind = 'payment') = (method IS NOT NULL)),
    -- Whose entry this is. A debt belongs to the ticket's specialist; a payment to whoever took
    -- it, who is often not the same person on a later day.
    recorded_by   INTEGER NOT NULL REFERENCES specialists (id),
    -- Always positive. `kind` carries the sign, so a row cannot be entered with the wrong one.
    amount        NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    business_date DATE NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_client_ledger_client ON client_ledger (client_id, business_date);

-- What the register held at the end of a day, against what the day's entries say it should have.
--
-- Both are stored and the variance is NOT: `counted` is a fact about a drawer at a moment, and
-- `expected` is a SNAPSHOT of what the entries said at that same moment. Recomputing the
-- expectation later would quietly absorb anything entered afterwards, which is the one thing a
-- reconciliation exists to catch (§7).
CREATE TABLE IF NOT EXISTS register_closes (
    id                   SERIAL PRIMARY KEY,
    -- One per day. Closing twice is refused rather than recorded as two opinions.
    business_date        DATE NOT NULL UNIQUE,
    closed_by            INTEGER NOT NULL REFERENCES specialists (id),
    counted_cash         NUMERIC(12, 2) NOT NULL CHECK (counted_cash >= 0),
    counted_banreservas  NUMERIC(12, 2) NOT NULL CHECK (counted_banreservas >= 0),
    counted_bhd          NUMERIC(12, 2) NOT NULL CHECK (counted_bhd >= 0),
    expected_cash        NUMERIC(12, 2) NOT NULL,
    expected_banreservas NUMERIC(12, 2) NOT NULL,
    expected_bhd         NUMERIC(12, 2) NOT NULL,
    closed_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id             SERIAL PRIMARY KEY,
    specialist_id  INTEGER NOT NULL REFERENCES specialists (id) ON DELETE CASCADE,
    business_date  DATE NOT NULL,
    services_total NUMERIC(12, 2) NOT NULL,
    commission     NUMERIC(12, 2) NOT NULL,
    tips           NUMERIC(12, 2) NOT NULL,
    -- Reported so she can see it, and deliberately not in the commission base (§7).
    products_total NUMERIC(12, 2) NOT NULL DEFAULT 0,
    -- Her whole outstanding balance on the day the message went out, not that day's entries,
    -- and split the way she is told it (§7).
    owed_products  NUMERIC(12, 2) NOT NULL DEFAULT 0,
    owed_loans     NUMERIC(12, 2) NOT NULL DEFAULT 0,
    -- Commission accrued in the pay period so far. Tips are not in it: they are handed over the
    -- same evening, so there is nothing of them left to accumulate.
    period_commission NUMERIC(12, 2) NOT NULL DEFAULT 0,
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- THE claim that stops a second send. The row is written before the message goes out and
    -- committed only once it has (scripts/daily_summary.py).
    UNIQUE (specialist_id, business_date)
);

COMMIT;
