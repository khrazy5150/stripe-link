"""Full-page notices the PLATFORM serves in place of a tenant's store.

The shell is `platform_page.html`, ported from stripe-cart's `paywall_template.html` -- the page a shopper
already meets when a merchant's billing lapses (the dark-blue card, the JB wordmark, the orange top rule,
the `<em>` accent in the headline, the trust strip). A Sabbath closure is the same KIND of event from the
shopper's side -- the store they wanted is not taking orders right now -- so it reads as the same page
rather than as a second design nobody recognises.

**The template is a shell with slots, not a paywall.** Two things in the legacy page were written for
billing specifically and are wrong anywhere else: the "One step away" eyebrow, and a trust strip reading
"Secured by Stripe / 256-bit encryption / Cancel anytime". A shopper told the store is shut for the day
does not need to be reassured about card encryption; they need to know nothing was charged and when it
reopens. Both are slots here, so each page states what is true of itself
(`feedback_notices_only_when_actionable` -- copy that does not fit the situation is noise at best).

**Rendered per request, never published.** stripe-cart wrote its blocked storefront to S3 as a static
`index.html`, which suits an indefinite suspension. A Sabbath window ends at a different minute every week,
so a published artifact would be stale within days and would state a reopening time that had already
passed -- the one fact the page exists to carry.
"""
from __future__ import annotations

import datetime
import html
from pathlib import Path
from typing import Any

_TEMPLATE_PATH = Path(__file__).with_name("platform_page.html")
_template_cache: str | None = None

#: The icon the legacy page uses, already public on the image CDN.
LOGO_IMAGE = "https://images.juniorbay.com/icon/favicon.png"


def _template() -> str:
    global _template_cache
    if _template_cache is None:
        _template_cache = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return _template_cache


def _trust_badge(label: str) -> str:
    """One footer fact. The legacy page drew a different icon per badge; a single check mark keeps the
    strip honest when the facts are not about security."""
    return (
        '      <div class="trust-badge">\n'
        '        <svg viewBox="0 0 14 14" fill="none" aria-hidden="true">\n'
        '          <path d="M3 7.5L6 10.5L11 4" stroke-width="1.4" stroke-linecap="round"'
        ' stroke-linejoin="round"/>\n'
        "        </svg>\n"
        f"        {html.escape(label)}\n"
        "      </div>\n"
    )


def render_platform_page(*, headline: str, subtitle: str, notice: str = "", eyebrow: str = "",
                         action_html: str = "", trust: tuple[str, ...] = (), logo_url: str = "https://juniorbay.com/",
                         below_card: str = "") -> str:
    """Fill the shared shell. `headline` may carry an `<em>` for the orange accent word and is NOT escaped;
    every caller here passes a literal, and escaping it would print the tag."""
    filled = _template()
    for token, value in (
        ("__LOGO_URL__", html.escape(logo_url)),
        ("__EYEBROW__", html.escape(eyebrow)),
        ("__NOTICE__", html.escape(notice)),
        ("__HEADLINE__", headline),
        ("__SUBTITLE__", html.escape(subtitle)),
        ("__PLAN_CARDS__", ""),
        ("__ACTION_SECTION__", action_html),
        ("__TRUST__", "\n" + "".join(_trust_badge(t) for t in trust) if trust else ""),
        ("__BELOW_CARD__", below_card),
    ):
        filled = filled.replace(token, value)
    return filled


def format_reopen(moment: datetime.datetime, timezone_name: str) -> str:
    """"Saturday at 6:12 pm" in the STORE's zone.

    The store's zone, not the visitor's: the shopkeeper reopens when it is sundown where the shop is, and a
    visitor two timezones away reading their own clock would arrive at the wrong hour. The zone is named on
    the page for exactly that reason.
    """
    from stripe_link.domain.store_timezone import load_zone

    local = moment.astimezone(load_zone(timezone_name))
    # %-I is "6" rather than "06"; it is a GNU/BSD extension and both Lambda and macOS have it, but a
    # failure here must not take the page down over a clock format.
    try:
        clock = local.strftime("%-I:%M %p").lower()
    except ValueError:  # pragma: no cover - platform without the dash flag
        clock = local.strftime("%I:%M %p").lstrip("0").lower()
    return f"{local.strftime('%A')} at {clock}"


def render_sabbath_closed(*, reopen_at: datetime.datetime | None = None, timezone_name: str = "UTC",
                          store_name: str = "") -> str:
    """The page a shopper gets while a store is closed for the Sabbath.

    **It names the reopening moment or it says nothing about time at all.** "Closed" without "until when"
    is the difference between a pause and a dead shop, and a wrong time is worse than no time -- so a
    missing `reopen_at` drops the sentence rather than inventing one.
    """
    when = format_reopen(reopen_at, timezone_name) if reopen_at else ""
    shop = str(store_name or "").strip()
    notice = (f"{shop} is closed for the Sabbath, from Friday sundown to Saturday sundown."
              if shop else "This store is closed for the Sabbath, from Friday sundown to Saturday sundown.")
    subtitle = (
        f"Orders reopen {when} ({timezone_name}). Nothing has been charged, and the store is"
        " open as usual for the rest of the week."
        if when else
        "Nothing has been charged. The store is open as usual for the rest of the week."
    )
    return render_platform_page(
        eyebrow="Back soon",
        notice=notice,
        # The accent word carries the meaning, as "offline." does on the billing page.
        headline="This store is closed for the <em>Sabbath.</em>",
        subtitle=subtitle,
        trust=(f"Reopens {when}" if when else "Reopens automatically",
               "Nothing was charged",
               "Open the rest of the week"),
    )


def sabbath_closed_html(exc: Any) -> str:
    """Convenience for a caller holding a `SabbathClosedError`."""
    return render_sabbath_closed(reopen_at=getattr(exc, "resume_at", None),
                                 timezone_name=getattr(exc, "timezone_name", "UTC") or "UTC")
