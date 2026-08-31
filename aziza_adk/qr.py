"""The code a client points her camera at.

`segno` is pure Python and writes nothing to disk, which is what lets it run under
`readOnlyRootFilesystem: true` and be asserted without a network. docs/PROJECT_DEFINITION.md §13.

The SVG leaves as a base64 `data:` URL on an `<img>`, never as markup the page splices in: an
`<img>` renders SVG with scripting disabled by specification, so the one place a third party's
output reaches the document is not also an HTML sink. Base64 rather than percent-encoding because
segno writes `#000` and a raw `#` in a data URL truncates it at the fragment.
"""

from __future__ import annotations

import base64

import segno

#: Medium recovery. The token is ~130 characters, so this is a version 9 symbol at 61 modules —
#: it survives a fingerprint on the screen and still scans from arm's length across a counter.
#: Raising it costs modules, and a denser code is one a client has to lean in for.
ERROR_CORRECTION = "m"

#: Module size in pixels. The page scales the image with CSS; this only has to be large enough
#: that the PNG-less SVG is crisp on a phone held at arm's length.
SCALE = 6

#: Explicit black on explicit WHITE. A transparent background inherits the page's, and a client
#: whose phone is in dark mode would be pointing her camera at white-on-black — which many
#: scanners refuse outright.
DARK = "#000000"
LIGHT = "#ffffff"


def svg(url: str) -> str:
    """The QR for one URL, as a standalone SVG document."""
    return segno.make(url, error=ERROR_CORRECTION).svg_inline(scale=SCALE, dark=DARK, light=LIGHT)


def data_url(url: str) -> str:
    """The QR for one URL, ready for an `<img src>`."""
    encoded = base64.b64encode(svg(url).encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
