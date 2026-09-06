"""The Junior Bay sign-off appended to mail a tenant sends to their own customers.

Free tenants carry it; premium ($19, tier `pro`) does not -- removing the platform's branding is what the
upgrade buys. The tier vocabulary is NOT restated here: it comes from domain/fees.py, which already owns
what "pro" means, so a future tier cannot mean one thing to billing and another to this footer.

Mail a tenant sends to their CUSTOMERS carries it. Mail the platform sends to the TENANT does not -- a
verification code is not the place to invite someone to start the store they already run.
"""

from html import escape
from typing import Any

from stripe_link.domain.fees import normalize_tier_id

# The tiers that have paid to remove the branding.
PREMIUM_TIERS = ("pro",)

SIGNATURE_TEXT = "Want to start your own online store?"
SIGNATURE_CTA = "Try it for free"
SIGNATURE_URL = "https://juniorbay.com/?utm_source=tenant_email&utm_medium=email&utm_campaign=signature"
# Already public on the images CDN and used by the homepage, so it needs no new hosting.
SIGNATURE_LOGO_URL = "https://images.juniorbay.com/icon/favicon.png"


def shows_platform_signature(tenant_profile: Any) -> bool:
    """Whether this tenant's outbound mail carries the sign-off. Absent profile means free, not exempt.

    Fails toward SHOWING: an unreadable profile must not silently hand a free tenant the premium perk.
    """
    profile = tenant_profile if isinstance(tenant_profile, dict) else {}
    return normalize_tier_id(profile.get("tier_id")) not in PREMIUM_TIERS


def signature_html() -> str:
    """A rule, a small mark, and one line of copy.

    Images are blocked by default in most mail clients, so the LINE carries the message and the logo is
    decoration with an empty alt -- a signature that reads as a broken-image icon advertises nothing.
    """
    return (
        '<div style="margin:28px 0 0;padding:16px 0 0;border-top:1px solid #e5e7eb;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Arial,sans-serif;'
        'font-size:13px;line-height:1.5;color:#6b7280;">'
        f'<a href="{escape(SIGNATURE_URL, quote=True)}" style="color:#6b7280;text-decoration:none;">'
        f'<img src="{SIGNATURE_LOGO_URL}" alt="" width="20" height="20"'
        ' style="vertical-align:middle;border:0;margin-right:8px;">'
        f'<span style="vertical-align:middle;">{SIGNATURE_TEXT} '
        f'<span style="color:#4f46e5;font-weight:600;">{SIGNATURE_CTA}</span>'
        "</span></a></div>"
    )


def signature_text() -> str:
    return f"\n\n--\n{SIGNATURE_TEXT} {SIGNATURE_CTA}: {SIGNATURE_URL}\n"
