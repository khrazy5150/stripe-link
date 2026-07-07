"""Server-rendered storefront booking page (GET /book/{service}).

A self-contained HTML page: service summary + a slot picker whose embedded script drives the
public booking API (availability -> reserve -> checkout) on the same origin. No external assets.
"""
from html import escape
from typing import Any

CURRENCY_SYMBOLS = {"usd": "$", "eur": "€", "gbp": "£"}


def _price_label(price: dict[str, Any]) -> str:
    amount = int(price.get("unit_amount") or 0)
    currency = str(price.get("currency") or "usd").lower()
    if amount == 0:
        return "Free"
    symbol = CURRENCY_SYMBOLS.get(currency, "")
    return f"{symbol}{amount / 100:,.2f}" if symbol else f"{amount / 100:,.2f} {currency.upper()}"


def _duration_label(minutes: int) -> str:
    minutes = max(1, int(minutes))
    if minutes < 60:
        return f"{minutes} min"
    hours, rem = divmod(minutes, 60)
    return f"{hours} hr {rem} min" if rem else f"{hours} hr"


def render_booking_page(service: dict[str, Any]) -> str:
    duration = int(service.get("duration_minutes") or 60)
    hero = str((service.get("presentation") or {}).get("hero_image_url") or "").strip()
    hero_html = f'<img class="hero" src="{escape(hero)}" alt="">' if hero else ""
    replacements = {
        "__SERVICE_ID__": escape(str(service.get("service_id") or ""), quote=True),
        "__SERVICE_NAME__": escape(str(service.get("name") or "Book a service")),
        "__SERVICE_DESC__": escape(str(service.get("description") or "")),
        "__PRICE_LABEL__": escape(_price_label(service.get("price") or {})),
        "__DURATION_LABEL__": escape(_duration_label(duration)),
        "__DURATION_MIN__": str(duration),
        "__HERO__": hero_html,
    }
    page = _TEMPLATE
    for token, value in replacements.items():
        page = page.replace(token, value)
    return page


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__SERVICE_NAME__</title>
<style>
  :root { --accent:#4f46e5; --line:#e5e7eb; --muted:#6b7280; --bg:#f8fafc; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:var(--bg); color:#111827; }
  .wrap { max-width:44rem; margin:0 auto; padding:1.5rem; }
  .card { background:#fff; border:1px solid var(--line); border-radius:14px; padding:1.5rem; margin-bottom:1.25rem; }
  .hero { width:100%; max-height:16rem; object-fit:cover; border-radius:12px; margin-bottom:1rem; }
  h1 { margin:0 0 .25rem; font-size:1.6rem; }
  .meta { color:var(--muted); margin:.25rem 0 1rem; }
  .price { font-weight:700; color:var(--accent); }
  label { display:block; font-size:.85rem; font-weight:600; margin:.75rem 0 .3rem; }
  input { width:100%; padding:.6rem .7rem; border:1px solid var(--line); border-radius:8px; font-size:1rem; }
  .days { display:grid; gap:1rem; }
  .day h3 { margin:0 0 .5rem; font-size:1rem; }
  .slots { display:flex; flex-wrap:wrap; gap:.5rem; }
  .slot { border:1px solid var(--line); background:#fff; border-radius:8px; padding:.5rem .8rem; cursor:pointer; font-size:.95rem; }
  .slot.selected { background:var(--accent); color:#fff; border-color:var(--accent); }
  button.book { width:100%; margin-top:1.25rem; padding:.85rem; background:var(--accent); color:#fff; border:0; border-radius:10px; font-size:1.05rem; font-weight:700; cursor:pointer; }
  button.book:disabled { opacity:.5; cursor:not-allowed; }
  .msg { padding:.9rem 1rem; border-radius:10px; margin-bottom:1rem; }
  .msg.error { background:#fef2f2; color:#b91c1c; }
  .msg.ok { background:#ecfdf5; color:#047857; }
  .empty { color:var(--muted); padding:1rem 0; }
</style>
</head>
<body>
<div class="wrap">
  <div id="banner"></div>
  <div class="card">
    __HERO__
    <h1>__SERVICE_NAME__</h1>
    <p class="meta"><span class="price">__PRICE_LABEL__</span> &middot; __DURATION_LABEL__</p>
    <p>__SERVICE_DESC__</p>
  </div>

  <div id="booking" class="card">
    <h3>Choose a time</h3>
    <div id="slots" class="empty">Loading available times&hellip;</div>

    <label for="name">Name</label>
    <input id="name" type="text" autocomplete="name">
    <label for="email">Email</label>
    <input id="email" type="email" autocomplete="email" required>
    <label for="phone">Phone (optional)</label>
    <input id="phone" type="tel" autocomplete="tel">

    <button id="book" class="book" disabled>Select a time</button>
  </div>
</div>
<script>
(function () {
  var serviceId = "__SERVICE_ID__";
  var apiBase = window.location.pathname.replace(/\\/book\\/[^/]+$/, "");
  var selected = null;
  var selectedFulfiller = null;
  var bookBtn = document.getElementById("book");
  var banner = document.getElementById("banner");

  var status = new URLSearchParams(window.location.search).get("status");
  if (status === "success") {
    document.getElementById("booking").style.display = "none";
    banner.innerHTML = '<div class="msg ok">Your booking is confirmed. A confirmation has been sent to your email.</div>';
    return;
  }
  if (status === "cancel") {
    banner.innerHTML = '<div class="msg error">Checkout was cancelled. You can pick another time below.</div>';
  }

  function showError(text) { banner.innerHTML = '<div class="msg error">' + text + '</div>'; }

  function fmtTime(iso) {
    var d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  function fmtDay(iso) {
    var d = new Date(iso);
    return d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  }

  function renderSlots(slots) {
    var host = document.getElementById("slots");
    if (!slots.length) { host.className = "empty"; host.textContent = "No available times in the next two weeks."; return; }
    var byDay = {};
    slots.forEach(function (s) {
      var key = new Date(s.start).toDateString();
      (byDay[key] = byDay[key] || []).push(s);
    });
    host.className = "days";
    host.innerHTML = "";
    Object.keys(byDay).forEach(function (key) {
      var group = byDay[key];
      var wrap = document.createElement("div");
      wrap.className = "day";
      var h = document.createElement("h3");
      h.textContent = fmtDay(group[0].start);
      wrap.appendChild(h);
      var row = document.createElement("div");
      row.className = "slots";
      group.forEach(function (s) {
        var b = document.createElement("button");
        b.className = "slot";
        b.type = "button";
        b.textContent = fmtTime(s.start);
        b.addEventListener("click", function () {
          selected = s.start; selectedFulfiller = s.fulfiller_id || null;
          Array.prototype.forEach.call(document.querySelectorAll(".slot"), function (el) { el.classList.remove("selected"); });
          b.classList.add("selected");
          bookBtn.disabled = false; bookBtn.textContent = "Book " + fmtTime(s.start);
        });
        row.appendChild(b);
      });
      wrap.appendChild(row);
      host.appendChild(wrap);
    });
  }

  function loadSlots() {
    var from = Math.floor(Date.now() / 1000);
    var to = from + 14 * 86400;
    fetch(apiBase + "/services/" + serviceId + "/availability?from=" + from + "&to=" + to)
      .then(function (r) { return r.json(); })
      .then(function (d) { renderSlots(d.slots || []); })
      .catch(function () { document.getElementById("slots").textContent = "Could not load times."; });
  }

  bookBtn.addEventListener("click", function () {
    banner.innerHTML = "";
    var email = document.getElementById("email").value.trim();
    if (!selected) { return; }
    if (!email) { showError("Please enter your email."); return; }
    var customer = { name: document.getElementById("name").value.trim(), email: email, phone: document.getElementById("phone").value.trim() };
    var body = { service_id: serviceId, slot_start: selected, customer: customer };
    if (selectedFulfiller) { body.fulfiller_id = selectedFulfiller; }
    bookBtn.disabled = true; bookBtn.textContent = "Reserving\\u2026";
    fetch(apiBase + "/services/appointments/reserve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { throw new Error(res.j.message || "That time is no longer available."); }
        var base = window.location.href.split("?")[0];
        return fetch(apiBase + "/services/appointments/checkout", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ appointment_id: res.j.appointment.appointment_id, manage_token: res.j.manage_token, success_url: base + "?status=success", cancel_url: base + "?status=cancel" })
        }).then(function (r) { return r.json(); });
      })
      .then(function (checkout) {
        if (checkout.checkout_url) { window.location = checkout.checkout_url; }
        else if (checkout.status === "booked") {
          document.getElementById("booking").style.display = "none";
          banner.innerHTML = '<div class="msg ok">Your booking is confirmed. A confirmation has been sent to your email.</div>';
        } else { throw new Error(checkout.message || "Could not complete booking."); }
      })
      .catch(function (e) { showError(e.message); bookBtn.disabled = false; bookBtn.textContent = "Book"; loadSlots(); });
  });

  loadSlots();
})();
</script>
</body>
</html>
"""
