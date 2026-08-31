"""The code as an image, asserted from values.

No network and no model. THE property is [2]: this is the one place a THIRD PARTY'S output reaches
a document, so what segno emits is asserted rather than trusted — and that assertion is what makes
the mini app's `img-src 'self' data:` safe to write rather than hopeful.

[3] bounds the symbol. A code that quietly jumps a few versions is one a client has to lean in for,
and nothing else in this repository would report it.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from aziza_adk import config, qr

#: A URL the length of a real one: the base URL plus a minted token, which is what decides the
#: symbol size the test below bounds.
_URL = "https://aziza.danielchaddy.com/j/" + "A" * 132


# --- [1] The same URL renders the same code -------------------------------------------------


def test_the_same_url_renders_the_same_svg():
    """A digest rather than a 5 KB literal: it fails identically, and the only thing that can move
    it is the segno pin — which is why the pin is exact."""
    once = hashlib.sha256(qr.svg(_URL).encode()).hexdigest()
    twice = hashlib.sha256(qr.svg(_URL).encode()).hexdigest()
    assert once == twice


def test_two_different_urls_are_two_different_codes():
    assert qr.svg(_URL) != qr.svg(_URL.replace("A", "B", 1))


# --- [2] What a third party emits, asserted rather than trusted -----------------------------


@pytest.mark.parametrize("forbidden", ["<script", "http://", "https://", "xlink:href", "<image"])
def test_the_svg_carries_no_script_and_no_external_reference(forbidden):
    """An `<img>` renders SVG with scripting disabled by specification, so this is belt and
    braces — but the policy that admits `data:` is written on the strength of it."""
    assert forbidden not in qr.svg(_URL)


def test_the_code_is_black_on_an_explicit_white_ground():
    """A transparent ground inherits the page's, and a client whose phone is in dark mode would be
    pointing her camera at white-on-black — which many scanners refuse outright."""
    rendered = qr.svg(_URL)
    assert qr.LIGHT.lstrip("#")[:3] in rendered or qr.LIGHT in rendered
    assert qr.DARK in rendered or qr.DARK.lstrip("#")[:3] in rendered


def test_the_data_url_is_base64_and_decodes_to_the_svg():
    """Base64 rather than percent-encoding: segno writes `#000`, and a raw `#` in a data URL
    truncates it at the fragment — which renders as nothing, in a viewer, silently."""
    url = qr.data_url(_URL)
    assert url.startswith("data:image/svg+xml;base64,")
    decoded = base64.b64decode(url.split(",", 1)[1]).decode("utf-8")
    assert decoded == qr.svg(_URL)


def test_the_data_url_carries_no_raw_hash_that_would_truncate_it():
    assert "#" not in qr.data_url(_URL)


# --- [3] A symbol a client does not have to lean in for -------------------------------------


def test_the_longest_real_url_still_fits_a_code_that_scans_across_a_counter():
    """Bounded, because a jump to a much denser symbol is invisible here and obvious in the salon.
    Version 11 is 61 modules at this length; the ceiling leaves room and no more."""
    import segno

    symbol = segno.make(_URL, error=qr.ERROR_CORRECTION)
    assert symbol.version <= 12, f"version {symbol.version} is denser than a phone screen wants"


def test_the_url_the_salon_actually_mints_is_the_length_this_file_assumes():
    """If a claim were added to the token the symbol would grow, and the bound above would be
    asserting something about a URL nobody uses."""
    from agent_webview import tokens

    from aziza_adk import join

    token = tokens.mint(
        "a-test-signing-secret-nobody-uses",
        audience="j",
        claims={"by": 7},
        ttl_s=config.JOIN_TOKEN_TTL_SECONDS,
        now=1_800_000_000.0,
        nonce=join.new_nonce(),
    )
    assert len(token) <= 132
