"""The shell and the script Telegram loads, as pure strings.

Two documents and nothing else: no database, no clock, no salon data. The shell is PUBLIC by
necessity — `initData` reaches JavaScript through `window.Telegram.WebApp`, so it is not in the
request that fetches the page and cannot gate it. Everything with the salon behind it is a separate
route that does. docs/PROJECT_DEFINITION.md §14.

The script is a served FILE rather than an inline block, which is what lets the policy say
`script-src 'self' https://telegram.org` with no `'unsafe-inline'` — so an injected `<script>` or
`onclick=` does not execute even if an escape is ever missed.
"""

from __future__ import annotations

#: Telegram's own SDK. The one external origin the page is allowed to fetch, and it is what supplies
#: `initData` and the theme variables.
SDK = "https://telegram.org/js/telegram-web-app.js"

_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
       background: var(--tg-theme-bg-color, #14110d);
       color: var(--tg-theme-text-color, #f2ede8); }
main { max-width: 26rem; margin: 0 auto; padding: 1.25rem 1rem 2.5rem; }
h1 { font-size: 1rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
     color: var(--tg-theme-hint-color, #b9a9a2); margin: 0 0 1rem; }
#code { display: grid; place-items: center; padding: 1rem; border-radius: 1rem;
        background: #fff; min-height: 15rem; }
#code img { width: 100%; max-width: 15rem; height: auto; display: block; }
#age { text-align: center; font-size: .85rem; color: var(--tg-theme-hint-color, #b9a9a2);
       margin: .75rem 0 0; font-variant-numeric: tabular-nums; }
h2 { font-size: .8rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
     color: var(--tg-theme-hint-color, #b9a9a2); margin: 2rem 0 .5rem; }
ol { list-style: none; margin: 0; padding: 0; }
li { padding: .7rem .9rem; margin: .4rem 0; border-radius: .6rem;
     background: var(--tg-theme-secondary-bg-color, #221d18);
     display: flex; justify-content: space-between; gap: .75rem; }
li span.n { color: var(--tg-theme-hint-color, #b9a9a2); font-variant-numeric: tabular-nums; }
li.busy { opacity: .55; }
.none { color: var(--tg-theme-hint-color, #b9a9a2); font-size: .9rem; margin: .4rem 0; }
#problem { padding: .8rem .9rem; margin: 1rem 0 0; border-radius: .6rem;
           background: #3a1f1a; color: #f5c1b6; font-size: .9rem; display: none; }
"""

#: The whole client-side program. It fetches, it renders, and it schedules the next fetch off the
#: SERVER's `expires_at` rather than a hardcoded interval — one number drives the rotation, so a
#: configuration change takes effect on the next mint with nothing here to disagree with it.
_SCRIPT = """
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) { tg.ready(); tg.expand(); }
  var auth = tg && tg.initData ? "tma " + tg.initData : "";
  var code = document.getElementById("code");
  var age = document.getElementById("age");
  var problem = document.getElementById("problem");
  var lines = document.getElementById("lines");
  var expiresAt = 0;

  function complain(text) {
    problem.textContent = text;
    problem.style.display = "block";
  }

  function ask(path) {
    return fetch(path, {
      method: "POST",
      headers: { "Authorization": auth },
      cache: "no-store",
    }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    });
  }

  function drawCode() {
    return ask("/mini-app/qr").then(function (data) {
      var img = new Image();
      // src on an <img>, never innerHTML: an <img> renders SVG with scripting disabled, so the
      // one place a third party's output reaches the document is not also an HTML sink.
      img.src = data.svg;
      img.alt = "";
      code.replaceChildren(img);
      expiresAt = data.expires_at;
      problem.style.display = "none";
      // A beat before it dies, so a client raising her phone at the last second still gets a
      // code the server will still accept.
      var wait = Math.max(5, data.rotate_seconds) * 1000;
      setTimeout(drawCode, wait);
    });
  }

  function drawQueue() {
    return ask("/mini-app/queue").then(function (data) {
      lines.replaceChildren();
      data.lines.forEach(function (line) {
        var h = document.createElement("h2");
        h.textContent = line.area;
        lines.appendChild(h);
        if (!line.waiting.length) {
          var p = document.createElement("p");
          p.className = "none";
          p.textContent = data.empty_label;
          lines.appendChild(p);
          return;
        }
        var ol = document.createElement("ol");
        line.waiting.forEach(function (name, i) {
          var li = document.createElement("li");
          var who = document.createElement("span");
          who.textContent = name;
          var n = document.createElement("span");
          n.className = "n";
          n.textContent = String(i + 1);
          li.append(who, n);
          ol.appendChild(li);
        });
        lines.appendChild(ol);
      });
      data.being_attended.forEach(function (name) {
        var li = document.createElement("li");
        li.className = "busy";
        li.textContent = name;
        lines.appendChild(li);
      });
      setTimeout(drawQueue, 20000);
    });
  }

  function tick() {
    if (!expiresAt) return;
    var left = Math.max(0, expiresAt - Math.floor(Date.now() / 1000));
    age.textContent = left + "s";
  }
  setInterval(tick, 1000);

  if (!auth) {
    complain(document.body.dataset.noAuth);
    return;
  }
  drawCode().catch(function () { complain(document.body.dataset.failed); });
  drawQueue().catch(function () {});
})();
"""


def script() -> str:
    """The page's own program, served with a type `nosniff` will execute."""
    return _SCRIPT


def shell(*, heading: str, no_auth: str, failed: str) -> str:
    """The document Telegram opens. Carries no salon data — every figure arrives by fetch.

    The two failure lines ride on `data-` attributes rather than being built into the script,
    because they are Spanish a specialist reads and belong with the rest of her copy.
    """
    from agent_webview.spec import esc

    return (
        "<!doctype html><html lang=es><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{esc(heading)}</title>"
        f'<script src="{SDK}"></script>'
        f"<style>{_STYLE}</style></head>"
        f'<body data-no-auth="{esc(no_auth)}" data-failed="{esc(failed)}"><main>'
        f"<h1>{esc(heading)}</h1>"
        "<div id=code></div><p id=age></p><div id=lines></div>"
        "<p id=problem></p>"
        "</main>"
        '<script src="/mini-app/app.js"></script>'
        "</body></html>"
    )
