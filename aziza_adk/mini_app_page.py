"""The shell and the script Telegram loads, as pure strings.

Two documents and nothing else: no database, no clock, no salon data — and no Spanish either. The
shell is PUBLIC by necessity, because `initData` reaches JavaScript through
`window.Telegram.WebApp` and so is not in the request that fetches the page. Everything with the
salon behind it is a separate route that gates, which apps exist for her included —
docs/PROJECT_DEFINITION.md §14.

Every label arrives in one of those gated answers rather than living here, so the copy stays in
Python constants where the sweep can find it (docs/BRAND_VOICE.md §6). The two lines that cannot
wait for a fetch ride on `data-` attributes.

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
[hidden] { display: none !important; }
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
           background: #3a1f1a; color: #f5c1b6; font-size: .9rem; }
button { font: inherit; color: inherit; cursor: pointer; }
#launcher { display: grid; gap: .6rem; }
#launcher button { width: 100%; text-align: left; padding: 1rem;
                   border: 0; border-radius: .8rem;
                   background: var(--tg-theme-secondary-bg-color, #221d18); }
#back { border: 0; background: none; padding: 0 0 .75rem;
        color: var(--tg-theme-link-color, #d9a441); font-size: .9rem; }
.card { padding: .9rem; margin: 0 0 .6rem; border-radius: .8rem;
        background: var(--tg-theme-secondary-bg-color, #221d18); }
.card .head { display: flex; justify-content: space-between; gap: .75rem; align-items: baseline; }
.card .what { font-weight: 600; }
.card .n { color: var(--tg-theme-hint-color, #b9a9a2); font-size: .85rem; white-space: nowrap; }
.card .flag { color: var(--tg-theme-hint-color, #b9a9a2); font-size: .8rem;
              font-style: italic; margin: .2rem 0 0; }
.card .by { color: var(--tg-theme-hint-color, #b9a9a2); font-size: .85rem; margin: .45rem 0 0; }
.card .link { border: 0; background: none; padding: 0;
              color: var(--tg-theme-link-color, #d9a441); text-decoration: underline; }
.card .shot { display: block; width: 100%; height: auto; margin: .5rem 0 0;
              border-radius: .5rem; }
.card .tick { margin: .8rem 0 0; width: 100%; padding: .6rem; border: 0; border-radius: .6rem;
              background: var(--tg-theme-button-color, #d9a441);
              color: var(--tg-theme-button-text-color, #1a140f); font-weight: 600; }
.card .tick[disabled] { opacity: .5; }
"""

#: The whole client-side program. It fetches, it renders, and it schedules the next fetch off the
#: SERVER's `expires_at` rather than a hardcoded interval — one number drives the rotation, so a
#: configuration change takes effect on the next mint with nothing here to disagree with it.
_SCRIPT = """
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) { tg.ready(); tg.expand(); }
  var auth = tg && tg.initData ? "tma " + tg.initData : "";
  var heading = document.getElementById("heading");
  var launcher = document.getElementById("launcher");
  var back = document.getElementById("back");
  var problem = document.getElementById("problem");
  var code = document.getElementById("code");
  var age = document.getElementById("age");
  var lines = document.getElementById("lines");
  var views = {
    queue: document.getElementById("queue"),
    supplies: document.getElementById("supplies")
  };
  var apps = [];
  var chooseLabel = "";
  var expiresAt = 0;
  var view = "";
  // Which opening the running timers belong to. Going back and in again starts a second set, and
  // without this the first would go on fetching underneath it for as long as the app is open.
  var epoch = 0;

  function complain(text) {
    problem.textContent = text;
    problem.hidden = false;
  }

  function failed() {
    complain(document.body.dataset.failed);
  }

  function send(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Authorization": auth, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : null,
      cache: "no-store"
    }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r;
    });
  }

  function ask(path, body) {
    return send(path, body).then(function (r) { return r.json(); });
  }

  function drawCode(mine) {
    return ask("/mini-app/qr").then(function (data) {
      if (mine !== epoch) return;
      var img = new Image();
      // src on an <img>, never innerHTML: an <img> renders SVG with scripting disabled, so the
      // one place a third party's output reaches the document is not also an HTML sink.
      img.src = data.svg;
      img.alt = "";
      code.replaceChildren(img);
      expiresAt = data.expires_at;
      problem.hidden = true;
      // A beat before it dies, so a client raising her phone at the last second still gets a
      // code the server will still accept.
      var wait = Math.max(5, data.rotate_seconds) * 1000;
      setTimeout(function () { if (mine === epoch) drawCode(mine); }, wait);
    });
  }

  function drawQueue(mine) {
    return ask("/mini-app/queue").then(function (data) {
      if (mine !== epoch) return;
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
      setTimeout(function () { if (mine === epoch) drawQueue(mine); }, 20000);
    });
  }

  function drawSupplies() {
    return ask("/mini-app/supplies").then(renderSupplies);
  }

  function renderSupplies(data) {
    var root = views.supplies;
    root.replaceChildren();
    if (!data.items.length) {
      var none = document.createElement("p");
      none.className = "none";
      none.textContent = data.empty_label;
      root.appendChild(none);
      return;
    }
    data.items.forEach(function (item) { root.appendChild(card(item, data)); });
  }

  function card(item, labels) {
    var box = document.createElement("article");
    box.className = "card";
    var head = document.createElement("div");
    head.className = "head";
    var what = document.createElement("span");
    what.className = "what";
    what.textContent = item.label;
    var when = document.createElement("span");
    when.className = "n";
    when.textContent = item.waited;
    head.append(what, when);
    box.appendChild(head);
    if (!item.listed) {
      var flag = document.createElement("p");
      flag.className = "flag";
      flag.textContent = labels.unlisted_label;
      box.appendChild(flag);
    }
    item.reports.forEach(function (one) { box.appendChild(reported(one, labels)); });
    var tick = document.createElement("button");
    tick.className = "tick";
    tick.textContent = labels.bought_label;
    tick.addEventListener("click", function () {
      tick.disabled = true;
      ask("/mini-app/supplies/bought", { ids: item.ids }).then(renderSupplies).catch(function () {
        tick.disabled = false;
        failed();
      });
    });
    box.appendChild(tick);
    return box;
  }

  function reported(one, labels) {
    var row = document.createElement("p");
    row.className = "by";
    var said = [one.who, one.waited];
    if (one.note) said.push(one.note);
    row.textContent = said.join(" \\u00b7 ");
    if (one.photo_id) {
      var see = document.createElement("button");
      see.className = "link";
      see.textContent = labels.photo_label;
      see.addEventListener("click", function () {
        see.disabled = true;
        showPhoto(row, see, one.photo_id);
      });
      row.append(" ", see);
    }
    return row;
  }

  function showPhoto(row, button, id) {
    // By ROW rather than by handle, and fetched rather than linked: an <img src> carries no
    // header, so the bytes come back through the same credential every other read uses.
    send("/mini-app/supplies/photo", { ids: [id] }).then(function (r) {
      return r.blob();
    }).then(function (blob) {
      var img = new Image();
      img.src = URL.createObjectURL(blob);
      img.alt = "";
      img.className = "shot";
      button.remove();
      row.after(img);
    }).catch(function () {
      button.disabled = false;
      failed();
    });
  }

  function open(app) {
    epoch += 1;
    var mine = epoch;
    view = app.key;
    heading.textContent = app.label;
    launcher.hidden = true;
    back.hidden = apps.length < 2;
    Object.keys(views).forEach(function (key) { views[key].hidden = key !== app.key; });
    problem.hidden = true;
    if (app.key === "queue") {
      drawCode(mine).catch(failed);
      drawQueue(mine).catch(function () {});
      return;
    }
    drawSupplies().catch(failed);
  }

  function choose() {
    epoch += 1;
    view = "";
    heading.textContent = chooseLabel;
    launcher.replaceChildren();
    apps.forEach(function (app) {
      var b = document.createElement("button");
      b.textContent = app.label;
      b.addEventListener("click", function () { open(app); });
      launcher.appendChild(b);
    });
    launcher.hidden = false;
    back.hidden = true;
    Object.keys(views).forEach(function (key) { views[key].hidden = true; });
  }

  function tick() {
    if (view !== "queue" || !expiresAt) return;
    var left = Math.max(0, expiresAt - Math.floor(Date.now() / 1000));
    age.textContent = left + "s";
  }
  setInterval(tick, 1000);

  back.addEventListener("click", choose);

  if (!auth) {
    complain(document.body.dataset.noAuth);
    return;
  }
  ask("/mini-app/apps").then(function (data) {
    apps = data.apps || [];
    chooseLabel = data.choose_label;
    back.textContent = data.back_label;
    if (!apps.length) return;
    // One app is opened rather than offered: a launcher listing a single thing is a tap asking
    // for nothing.
    if (apps.length === 1) { open(apps[0]); return; }
    choose();
  }).catch(failed);
})();
"""


def script() -> str:
    """The page's own program, served with a type `nosniff` will execute."""
    return _SCRIPT


def shell(*, title: str, no_auth: str, failed: str) -> str:
    """The document Telegram opens. Carries no salon data — every label arrives by fetch.

    The two failure lines ride on `data-` attributes rather than being built into the script,
    because they are Spanish a specialist reads and belong with the rest of her copy. They are
    also the only two that cannot wait for an answer: one of them is what a failed fetch says.
    """
    from agent_webview.spec import esc

    return (
        "<!doctype html><html lang=es><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)}</title>"
        f'<script src="{SDK}"></script>'
        f"<style>{_STYLE}</style></head>"
        f'<body data-no-auth="{esc(no_auth)}" data-failed="{esc(failed)}"><main>'
        "<button id=back hidden></button>"
        '<h1 id="heading"></h1>'
        "<nav id=launcher hidden></nav>"
        "<section id=queue hidden>"
        "<div id=code></div><p id=age></p><div id=lines></div>"
        "</section>"
        "<section id=supplies hidden></section>"
        "<p id=problem hidden></p>"
        "</main>"
        '<script src="/mini-app/app.js"></script>'
        "</body></html>"
    )
