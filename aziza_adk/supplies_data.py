"""What the salon buys for itself, as against `catalog_data.py`, which is what it sells.

Stdlib only, and read by BOTH the seeder and the tests — so a change here cannot leave the tests
asserting against something the salon does not buy.

**Empty is a working state rather than a broken one.** A phrase that matches nothing here is
recorded in the specialist's own words instead of being refused, so the list works on day one and
a row added later only starts grouping two people who say the same thing
(docs/PROJECT_DEFINITION.md §16).

`aliases` are pipe-separated and never shown: they are what she says out loud, and the resolver
is `catalog.resolve`, unchanged and reused.
"""

from __future__ import annotations

# TODO: issue #46 — the salon has not given its list yet.
SUPPLIES: tuple[dict, ...] = ()
