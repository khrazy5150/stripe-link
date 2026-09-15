"""The four pages a customer sees when they want to stop paying or ask for their money back.

plans/PURCHASE_SELF_SERVICE.md. Server-rendered, no framework, no tracking: these are reached from a footer
link or an emailed token, by someone who is already slightly annoyed. Same dark shell as the error pages, so
an expired link and a live one clearly belong to the same place.

The copy does one job above all others: keep CANCELLED (a fact) apart from REQUESTED (a decision the seller
makes). Blurring them is how a self-service flow manufactures the disputes it exists to prevent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

_STYLE = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: system-ui, -apple-system, sans-serif;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); color: #f1f5f9;
  min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
.card { width: 100%; max-width: 520px; }
.badge { display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 12px;
  letter-spacing: .08em; text-transform: uppercase; color: #fbbf24; border: 1px solid #b45309; }
h1 { font-size: 26px; margin: 16px 0 8px; }
p { color: #cbd5e1; line-height: 1.6; margin: 0 0 16px; }
.summary { border: 1px solid #334155; border-radius: 12px; padding: 16px 18px; margin: 20px 0;
  background: rgba(15,23,42,.6); }
.summary .amount { font-size: 22px; font-weight: 700; color: #f1f5f9; }
.summary .meta { color: #94a3b8; font-size: 14px; margin-top: 4px; }
label { display: block; font-size: 14px; color: #e2e8f0; margin: 0 0 6px; }
input, textarea { width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid #334155;
  background: #0b1220; color: #f1f5f9; font: inherit; margin-bottom: 16px; }
button { width: 100%; padding: 13px 16px; border: 0; border-radius: 10px; font: inherit; font-weight: 700;
  cursor: pointer; background: #4f46b5; color: #fff; margin-bottom: 10px; }
button.secondary { background: transparent; color: #cbd5e1; border: 1px solid #334155; }
.fine { font-size: 13px; color: #94a3b8; }
a { color: #a5b4fc; }
"""


def _shell(title: str, body: str, badge: str = "Manage a purchase") -> str:
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        f"<title>{escape(title)}</title>\n<style>{_STYLE}</style>\n</head>\n<body>\n"
        f'<div class="card">\n<span class="badge">{escape(badge)}</span>\n{body}\n</div>\n</body>\n</html>'
    )


def _money(amount: Any, currency: str = "usd") -> str:
    return f"{str(currency or 'usd').upper()} {int(amount or 0) / 100:.2f}"


def _date(epoch: int) -> str:
    if not epoch:
        return ""
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%d %b %Y")


def render_lookup_form(action_url: str, tenant_id: str, *, business: str = "", message: str = "",
                       honeypot_field: str = "company_website") -> str:
    """Step one: who are you, and roughly when.

    Deliberately asks for nothing else. A static page cannot verify a card, and asking for one would only
    teach customers to type card numbers into forms they arrived at from a link.
    """
    who = escape(business) if business else "this seller"
    note = f'<p class="fine">{escape(message)}</p>' if message else ""
    return _shell("Manage a purchase", f"""
<h1>Manage a purchase</h1>
<p>Tell us the email address or phone number you used when you bought from {who}, and we will send you a
link to that purchase. You can cancel a recurring payment or ask for a refund from there.</p>
{note}
<form method="POST" action="{escape(action_url)}">
  <input type="hidden" name="action" value="lookup">
  <input type="hidden" name="tenant" value="{escape(tenant_id)}">
  <div style="position:absolute;left:-9999px" aria-hidden="true">
    <label for="{escape(honeypot_field)}">Leave this empty</label>
    <input id="{escape(honeypot_field)}" name="{escape(honeypot_field)}" tabindex="-1" autocomplete="off">
  </div>
  <label for="contact">Email or phone</label>
  <input id="contact" name="contact" autocomplete="email" required placeholder="you@example.com">
  <label for="when">Roughly when? <span class="fine">(optional — helps if you bought more than once)</span></label>
  <input id="when" name="when" type="date">
  <button type="submit">Email me the link</button>
</form>
<p class="fine">We only ever send the link to the address or number you enter.</p>
""")


def render_lookup_sent() -> str:
    """The SAME answer whether or not anything matched.

    Otherwise this page is an oracle for "did that person buy from this creator" — a fact about someone who
    is not the one asking.
    """
    return _shell("Check your inbox", """
<h1>Check your inbox</h1>
<p>If we found a purchase for that email address or phone number, we have just sent a link to it. The link
works for seven days.</p>
<p class="fine">Nothing arrived? Check your spam folder, then try again with the exact address you used at
checkout — it may have been a different one.</p>
""")


def render_transaction(summary: dict[str, Any], action_url: str, token: str, *, business: str = "",
                       policy: str = "", lookup_url: str = "") -> str:
    """Step two: ONE transaction, stated, with only the actions it allows.

    Showing what we think this is, before anything happens, is what makes a wrong match visible instead of
    silent — and the "not this one" link beside it is what stops a wrong match being a dead end. A dead end
    is how someone ends up at their bank, which costs the seller a dispute fee and their ratio.
    """
    actions = summary.get("actions") or []
    every = f" · {escape(str(summary['interval']))}ly" if summary.get("interval") else ""
    cancel_html = ""
    if "cancel" in actions:
        cancel_html = f"""
<form method="POST" action="{escape(action_url)}">
  <input type="hidden" name="action" value="cancel">
  <input type="hidden" name="t" value="{escape(token)}">
  <button type="submit">Stop future payments</button>
</form>
<p class="fine">This takes effect straight away. Payments already made are not returned by this.</p>
"""
    refund_html = ""
    if "refund" in actions:
        policy_html = f'<p class="fine">{escape(policy)}</p>' if policy else ""
        refund_html = f"""
<form method="POST" action="{escape(action_url)}">
  <input type="hidden" name="action" value="refund">
  <input type="hidden" name="t" value="{escape(token)}">
  <label for="reason">Ask {escape(business) if business else "the seller"} for a refund</label>
  <textarea id="reason" name="reason" rows="3" placeholder="What went wrong? (optional)"></textarea>
  {policy_html}
  <button class="secondary" type="submit">Send refund request</button>
</form>
<p class="fine">A refund is the seller's decision, not ours — this sends them your request and they reply to
you directly.</p>
"""
    not_this = (
        f'<p class="fine"><a href="{escape(lookup_url)}">Not this one?</a> Search again and add the date you '
        "bought."
        "</p>" if lookup_url else ""
    )
    return _shell("Your purchase", f"""
<h1>Your purchase</h1>
<div class="summary">
  <div class="amount">{escape(_money(summary.get("amount"), summary.get("currency")))}{every}</div>
  <div class="meta">{escape(str(summary.get("name") or "Your purchase"))} ·
    {escape(_date(summary.get("created_at") or 0))}{" · " + escape(business) if business else ""}</div>
</div>
{cancel_html}
{refund_html}
{not_this}
""")


def render_cancelled(business: str = "") -> str:
    return _shell("Payments stopped", f"""
<h1>Payments stopped</h1>
<p>No further payments will be taken{f" by {escape(business)}" if business else ""}. You will not be charged
again.</p>
<p class="fine">Payments already made are not returned by this. If you want one of them back, use the link
again and send a refund request.</p>
""")


def render_refund_requested(business: str = "") -> str:
    """REQUESTED, not refunded. The distinction is the whole reason this page is worded so plainly."""
    return _shell("Request sent", f"""
<h1>Request sent</h1>
<p>{escape(business) if business else "The seller"} has your refund request and will reply to you by email.
The decision is theirs — we have not taken any money back yet.</p>
<p class="fine">If you do not hear anything, reply to your original receipt.</p>
""")
