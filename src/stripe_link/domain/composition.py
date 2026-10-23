"""Page Composer — the single place that decides which sections a landing page renders.

Business logic, not rendering. Both renderers obey it: the Python publisher calls compose_page() here, and
the Vue builder mirrors the same decisions from the SAME rules file (composition_rules.json), so a section
can never appear in the preview and not on the published page. See plans/PAGE_COMPOSER.md.

Rules (composition_rules.json) are an ALLOW-LIST: per offer_type, the section keys visible by default.
A section whose key isn't "governed" (the composable body elements — testimonials, faq, …) shows whenever
it's present (adding it IS the opt-in). The tenant overrides a governed default via page.composition.overrides
(compact: {section_key: {enabled: bool}}) — default != forced.

Composition has two axes (plans/LANDING_PAGE_GOAL_COMPOSITION.md): offer_type (WHAT the page sells) sets the
base sections, and the page's goal (WHY / where its traffic comes from) enables capability packs on top.
Packs are union-only, so a page without a goal composes exactly as it did before goals existed.
"""

from __future__ import annotations

import json
from pathlib import Path

from stripe_link.domain.opportunities import derived_offer_type
from typing import Any

_RULES_PATH = Path(__file__).resolve().parent.parent / "composition_rules.json"
try:
    with _RULES_PATH.open(encoding="utf-8") as _fh:
        RULES: dict[str, Any] = json.load(_fh)
except (OSError, ValueError):
    # Degrade safely if the rules file is somehow unbundled: nothing governed -> every section visible
    # (no composition), rather than crashing the Lambda at import.
    RULES = {"elements": {}, "governed_sections": [], "offer_types": {}, "packs": {}, "goals": {}}

ELEMENTS: dict[str, Any] = RULES.get("elements") or {}
_GOVERNED: set[str] = set(RULES.get("governed_sections") or [])
_OFFER_TYPES: dict[str, Any] = RULES.get("offer_types") or {}
_PACKS: dict[str, Any] = RULES.get("packs") or {}
_GOALS: dict[str, Any] = RULES.get("goals") or {}


def element(section_type: str) -> dict[str, Any]:
    """Catalog metadata for a section type (label / ui / kind / channel / heading_role / tokens)."""
    return ELEMENTS.get(str(section_type or ""), {})


def element_label(section_type: str) -> str:
    return str(element(section_type).get("label") or section_type)


def element_channel(section_type: str) -> str:
    """Where a section renders: "body" (visible markup), "head" (meta / JSON-LD) or "sidecar" (its own
    artifact, e.g. /llms.txt). The renderer routes composed sections by this, so head sections are ordinary
    composed sections that simply don't paint pixels (plans/LANDING_PAGE_GOAL_COMPOSITION.md). Unknown or
    unset defaults to "body" — the safe assumption for any element predating channels."""
    return str(element(section_type).get("channel") or "body")


def section_key(section_type: str) -> str:
    """Canonical composition key. Post-Builder-Reframe the key IS the section type (no aliasing)."""
    return str(section_type or "")


def _offer_type_rule(offer_type: str) -> dict[str, Any]:
    return _OFFER_TYPES.get(str(offer_type or ""), _OFFER_TYPES.get("single", {}))


def supported_goals() -> list[str]:
    """Every goal a page may legally store, INCLUDING deprecated ones. Deleting a goal outright would strand
    pages that already reference it — they would stop validating, so they could not be saved or even
    re-rendered. Retiring is therefore additive: mark it `deprecated` and it stays valid forever while
    disappearing from the wizard (see offerable_goals)."""
    return list(_GOALS.keys())


def offerable_goals() -> list[str]:
    """Goals a NEW page may choose — what the wizard lists. Excludes deprecated ones."""
    return [name for name, meta in _GOALS.items() if not (meta or {}).get("deprecated")]


def goal_deprecated(goal: str) -> bool:
    return bool((_GOALS.get(str(goal or "")) or {}).get("deprecated"))


def goal_label(goal: str) -> str:
    return str((_GOALS.get(str(goal or "")) or {}).get("label") or goal)


def goal_note(goal: str) -> str:
    return str((_GOALS.get(str(goal or "")) or {}).get("note") or "")


def goal_packs(goal: str) -> list[str]:
    """Capability packs a goal turns on. An unknown/absent goal enables none — which is exactly how pages
    composed before goals existed, so old pages need no migration."""
    return list((_GOALS.get(str(goal or "")) or {}).get("packs") or [])


def pack_seeds(goal: str) -> list[str]:
    """Content-bearing element types the create wizard should seed for this goal (deduped, in pack order).
    These render nothing until the tenant fills them in, and are tenant-owned once seeded — the goal never
    retracts them."""
    seeds: list[str] = []
    for name in goal_packs(goal):
        for seed in (_PACKS.get(name) or {}).get("seeds") or []:
            if seed not in seeds:
                seeds.append(seed)
    return seeds


def goal_chrome(goal: str, key: str) -> bool | None:
    """A chrome default this goal sets, or None when it has no opinion.

    The goal is a statement about WHY the page exists, and some of the page's furniture follows from that
    rather than from what it sells. The breadcrumb is the clearest case: it is an on-page SEO device, not
    something a visitor wants, so it belongs on a page that came from search and nowhere else. Every goal
    therefore sets it, and only `search_seo` sets it true.

    Configuration rather than code, so a NEW goal sets its own chrome without a renderer change — same
    reason packs live in this file. A goal that sets nothing returns None and leaves the shape in charge,
    which is what a page predating the goal axis still gets.
    """
    value = (_GOALS.get(str(goal or "")) or {}).get("chrome") or {}
    found = value.get(key)
    return found if isinstance(found, bool) else None


def goal_sections(goal: str) -> set[str]:
    """Governed sections the goal's packs turn on, unioned over the base. Empty until derived head/sidecar
    sections (structured_data, llms_txt) land — see plans/LANDING_PAGE_GOAL_COMPOSITION.md Phase 3."""
    return {
        key
        for name in goal_packs(goal)
        for key in ((_PACKS.get(name) or {}).get("sections") or [])
    }


def excluded_sections(offer_type: str) -> set[str]:
    """Sections this offer_type can NEVER show, whatever else asks for them."""
    return set(_offer_type_rule(offer_type).get("excludes") or ())


# The shipping element cannot live in an offer_type's section list, because `single` and `bundle` cover
# digital goods too and a shipping card on a download is nonsense. It is keyed on the one thing that
# actually decides it: whether the offer ships something.
SHIPS_PHYSICAL_SECTION = "shipping"


def default_visible(offer_type: str, key: str, goal: str = "", ships_physical: bool = False) -> bool:
    """Whether a governed section key is visible by DEFAULT for this offer_type + goal (before overrides).
    Base sections from the offer_type, unioned with the sections the goal's packs enable -- minus anything
    the offer_type declares impossible.

    **Shipping defaults ON for anything that ships**, like trust badges do for a sales page, and the tenant
    unticks it if they do not want it. Default rather than forced, but the default matters more here than
    anywhere else on the page: the element is the only thing that collects a postcode, a quote without one
    returns `needs: postal_code`, and Stripe then gets no shipping option at all -- so the buyer pays
    nothing to post and nobody is told. A real order shipped a Large box for $7.83 having collected $0 at
    checkout, purely because its page had no shipping element (2026-10-06).
    """
    if key in excluded_sections(offer_type):
        return False
    if key == SHIPS_PHYSICAL_SECTION:
        return bool(ships_physical)
    base = _offer_type_rule(offer_type).get("sections") or []
    return key in base or key in goal_sections(goal)


def is_section_visible(
    offer_type: str,
    section_type: str,
    overrides: dict[str, Any] | None = None,
    goal: str = "",
    ships_physical: bool = False,
) -> bool:
    """Final visibility for one section: override wins, else the offer_type + goal default; ungoverned
    sections (body elements) are visible whenever present."""
    key = section_key(section_type)
    if key not in _GOVERNED:
        return True
    # An exclusion outranks a tenant override too. Everything else here is a preference; this is a
    # statement about what the page IS, and a refund policy on a page that takes no money is incoherent
    # rather than merely unwanted.
    if key in excluded_sections(offer_type):
        return False
    override = (overrides or {}).get(key)
    if isinstance(override, dict) and "enabled" in override:
        return bool(override.get("enabled"))
    return default_visible(offer_type, key, goal, ships_physical)


def page_overrides(page: dict[str, Any]) -> dict[str, Any]:
    composition = page.get("composition") or {}
    overrides = composition.get("overrides")
    return overrides if isinstance(overrides, dict) else {}


def page_goal(page: dict[str, Any]) -> str:
    """The page's goal, or "" when it predates the goal axis (composes as base-only)."""
    return str((page or {}).get("goal") or "")


def derived_head_sections(offer_type, overrides, goal, present) -> list[dict[str, Any]]:
    """Head-channel sections the composer GENERATES rather than reads off the page.

    A head section (structured_data today) carries no tenant fields at all — render_head_section builds the
    JSON-LD from the offer and the sections already on the page. Its truth is entirely `is_section_visible`,
    which is to say the goal's capability pack plus the tenant's toggle. Storing it in `page.sections` as
    well was a second copy of a fact the composer already had, kept only because compose_page used to filter
    and never add — a constraint that no longer holds.

    That duplicate cost a page its rich results: a save-path bug dropped the stored marker, and with it the
    page's entire Product/FAQPage markup, even though the goal still said it should be there. Derived, it
    cannot be lost, and a page that lost it heals on the next publish with no re-save.
    """
    seen = {str(section.get("type") or "") for section in present}
    return [
        {"id": key.replace("_", "-"), "type": key}
        for key, spec in RULES.get("elements", {}).items()
        if spec.get("channel") == "head"
        and key not in seen
        and is_section_visible(offer_type, key, overrides, goal)
    ]


def derived_shipping_section(offer_type, overrides, goal, present, ships_physical) -> list[dict[str, Any]]:
    """The shipping element, generated when the offer ships and the page has not got one.

    Derived rather than written into `page.sections` for the same reason `structured_data` is: it carries
    no tenant fields at all. `render_shipping_selector` emits an empty shell and fetches the countries and
    the rates at page load, because a rate depends on destination and live carrier pricing and a published
    page is an S3 artifact. There is nothing to author, so there is nothing to store.

    The consequence that matters: a page published before this existed heals on its next publish, with no
    re-save and no rebuild. Unticking it in Page Sections still wins -- that writes an override, and an
    override outranks the default.
    """
    if not ships_physical or SHIPS_PHYSICAL_SECTION in {str(s.get("type") or "") for s in present}:
        return []
    if not is_section_visible(offer_type, SHIPS_PHYSICAL_SECTION, overrides, goal, ships_physical):
        return []
    return [{"id": SHIPS_PHYSICAL_SECTION, "type": SHIPS_PHYSICAL_SECTION}]


# Page kinds whose section sequence is AUTHORED in code rather than composed from a goal: the funnel steps
# and thank-you pages built by runtime/upsell_pages.py. Composing their order would scramble it — celebration
# sits in the `free` band while headline/subheadline are `pinned_top`, so a baseline pass drops the
# celebration below the headline. They are not builder pages: no goal, no tenant deltas, nothing to compose.
AUTHORED_PAGE_TYPES = ("funnel_step", "thank_you")


# Which composition each lead-capture action gets. The three capture_* actions share one page -- the FIELD
# differs, the page does not -- while call, bridge and link-in-bio are genuinely different shapes.
LEAD_COMPOSITIONS = {
    "capture_email": "lead_capture",
    "capture_phone": "lead_capture",
    "capture_email_phone": "lead_capture",
    "call_number": "lead_call",
    "external_url": "lead_bridge",
    "social_redirect": "lead_social",
    # A session page is a capture page that must also say WHEN (plans/WEBINAR.md).
    "register_event": "lead_event",
}
# An offer that says lead_gen without naming an action still must not get a checkout page. The capture
# shape is the safe default: it is the only one that keeps a form, so nothing the tenant typed is lost.
DEFAULT_LEAD_COMPOSITION = "lead_capture"


def composition_key(offer: dict[str, Any]) -> str:
    """Which composition this offer gets: "lead_gen", else its offer_type.

    Deliberately NOT folded into derived_offer_type. That function answers "how does this offer PRICE" --
    single, bundle or listicle -- and four places in the renderer branch on it to decide carousel and
    minicart behaviour. Intent is a different question ("does this page transact at all?") and conflating
    them would silently change those four.

    Reads `product_intent` straight off the OFFER, which already carries it, so no product lookup and no
    signature change. See plans/SOCIAL_MEDIA_PAGES.md §2a for why the first attempt used offer_type and
    could never be reached: offer_type is derived, and no offer SHAPE can express "sells nothing".
    """
    if str((offer or {}).get("product_intent") or "") == "lead_gen":
        return LEAD_COMPOSITIONS.get(
            str((offer or {}).get("lead_capture_action") or ""), DEFAULT_LEAD_COMPOSITION)
    # A TIP JAR is a transaction page, but not a sales page: there is no product, no delivery and nothing to
    # be reassured about, so the persuasion furniture of a checkout page does not belong on it. Read off the
    # offer like `lead_capture_action`, because the composer never sees the products; the renderer stamps it
    # from them, so an offer saved before the field existed still composes correctly.
    if str((offer or {}).get("pricing_model") or "") == "customer_chooses":
        return "tip_jar"
    return derived_offer_type(offer or {})


# The two OFFER-LESS compositions, and the sections that identify each (plans/OFFERLESS_PAGES_IN_BUILDER.md
# P1). A storefront homepage, a category page and a store profile carry no offer at all, so `composition_key`
# -- which reads an offer -- has nothing to read and falls through to `single`. Under `single` the price
# selector and the Buy CTA are visible, which is harmless in the renderer (compose_page only ever FILTERS
# page.sections, it never adds one) and wrong in the builder, which CONSTRUCTS sections from builder state
# gated on the same predicate. That asymmetry is the whole reason offer-less pages were locked out of the
# builder; naming their shapes here is what unlocks them.
#
# Derived from the page's own sections rather than a new stored field, so every page that already exists
# composes correctly with no migration -- the same signal `is_offerless_page()` and the dashboard's
# `pageAttachKind()` already read.
OFFERLESS_COMPOSITIONS = ("store_profile", "storefront")
_OFFERLESS_MARKERS = (
    # Order matters: a profile page may also carry a grid, and the profile block is the more specific claim.
    ("store_profile", "seller_profile"),
    ("storefront", "catalog_grid"),
    ("storefront", "brand_hero"),
)


def offerless_composition(page: dict[str, Any] | None) -> str:
    """Which offer-less shape this page is, or "" when it is an ordinary offer page.

    Only meaningful for a page with NO offer. A link hub (`lead_social`) may carry a `catalog_grid` of its
    own -- its excludes say so explicitly -- so this must never be consulted ahead of the offer; see
    `page_composition_key`, which is the only correct way in.
    """
    present = {
        str(section.get("type") or "")
        for section in ((page or {}).get("sections") or [])
        if isinstance(section, dict)
    }
    for composition, marker in _OFFERLESS_MARKERS:
        if marker in present:
            return composition
    return ""


def page_composition_key(page: dict[str, Any] | None, offer: dict[str, Any] | None) -> str:
    """The composition for a PAGE: its offer's shape, or its offer-less shape when it has no offer.

    THE OFFER ALWAYS WINS. `publish_page` sets `offer = {}` for a page with no `offer_id` and only then
    (runtime/publishing.py), so an empty offer is exactly the "no offer" signal and nothing else -- which
    is what keeps a link-in-bio page holding a `catalog_grid` composing as `lead_social` and not as a
    storefront.

    `composition_key(offer)` is left alone on purpose: six callers in the renderer ask it a question about
    the OFFER ("is this a link hub?", "is this a listicle?"), and widening its signature would invite a
    page-shaped answer at a call site that wants an offer-shaped one.
    """
    if offer:
        return composition_key(offer)
    return offerless_composition(page) or composition_key(offer or {})


# Compositions that may NEVER be indexed, whatever the Site's eligibility says (plans/LEAD_GEN_PAGES.md §5).
# This is a statement about what the page IS, not a preference, so there is no tenant override -- the same
# standing as `excludes` above, and for the same reason. A bridge page's whole purpose is to send the visitor
# somewhere else, which is the thin doorway shape search engines penalise; indexing one would put the Site's
# entire reputation behind a page carrying no content of its own. The honest uses (an old domain forwarding to
# a new one) do not want it indexed either: the DESTINATION should rank, never the bridge.
NEVER_INDEXED_COMPOSITIONS = frozenset({"lead_bridge"})


def composition_forbids_indexing(offer: dict[str, Any]) -> bool:
    """Whether this offer's composition can never be indexed, regardless of Site eligibility."""
    return composition_key(offer) in NEVER_INDEXED_COMPOSITIONS


def shows_breadcrumb(offer: dict[str, Any], page: dict[str, Any] | None = None) -> bool:
    """Whether this page shows the Home > ... trail in its header.

    A breadcrumb says "you are HERE in a hierarchy", which is true of a product inside a catalogue and false
    of the lead shapes: a link hub is an identity page, not a node under a store, and a bridge page is noindex
    by rule -- a crawlable trail on a page no crawler may index is clutter with no reader. So the lead shapes
    default OFF, the transactional ones default ON, and `page.chrome.breadcrumb` overrides either way, because
    a standalone checkout page attached to a Site is a real case with no rule that settles it.

    Gates BOTH the visible nav and the BreadcrumbList JSON-LD, which is why it lives inside breadcrumb_trail
    rather than beside one of its callers: structured data has to describe what is on the page, and markup for
    a breadcrumb a visitor cannot see is exactly the mismatch Google's guidelines call out.

    Three inputs, most specific first:

    1. `page.chrome.breadcrumb` — the tenant said so for THIS page, and nothing outranks that.
    2. The GOAL's own default, which every goal now sets (author, 2026-10-22): ONLY `search_seo` shows a
       breadcrumb. The reasoning is the author's and it is worth keeping, because it reverses what this
       function used to assume -- **a breadcrumb is not a thing visitors want, it is an on-page SEO device**.
       So the question is not "is this page a node in a hierarchy?" but "did this page come from search?".
       Ad, social and email traffic already knows where it is and did not arrive looking to browse upward.
    3. The composition's default: the lead shapes off, everything else on. Reached only by a page with NO
       goal at all -- one created before the goal axis existed. Those keep composing exactly as they did,
       which is why the goals carry the new rule and this line was left alone.

    A goal therefore outranks the SHAPE, and that was the point of the change rather than a side effect:
    lead pages obey it too. A lead page is generally fed by paid ads or a link, not by search, but when one
    IS built for search it gets the breadcrumb like anything else. All three layers are defaults -- the
    tenant's own tick always wins -- so this orders preferences, not invariants.
    """
    override = ((page or {}).get("chrome") or {}).get("breadcrumb")
    if isinstance(override, bool):
        return override
    from_goal = goal_chrome(page_goal(page or {}), "breadcrumb")
    if from_goal is not None:
        return from_goal
    return not is_lead_composition(offer)


def is_lead_composition(offer: dict[str, Any]) -> bool:
    """Whether this offer composes as one of the four lead shapes rather than a checkout page."""
    return composition_key(offer) in set(LEAD_COMPOSITIONS.values())


# Pages whose FORM is short. Being brief is what these pages ARE, not a defect in them, so the thin-content
# nudge is skipped for all of them (plans/LEAD_GEN_PAGES.md, and the tip jar for the same reason: there is no
# product to describe, so "add a specifications table or condition details" is advice that cannot be taken).
THIN_BY_DESIGN = set(LEAD_COMPOSITIONS.values()) | {"tip_jar"}


def is_thin_by_design(offer: dict[str, Any]) -> bool:
    return composition_key(offer) in THIN_BY_DESIGN


def default_cta_label(offer: dict[str, Any]) -> str:
    """What this page's button says when the tenant has not written their own.

    In the rules file with the rest of the composition, because the builder and the renderer both need it and
    a default that disagrees between them is a page whose preview and published copy differ. "" = no opinion,
    and the caller keeps whatever it used before.
    """
    rules = RULES.get("offer_types", {}).get(composition_key(offer), {})
    return str(rules.get("default_cta_label") or "")


def offer_ships_physical(offer: dict[str, Any] | None) -> bool:
    """The offer's own say on whether it ships something, denormalised by the builder.

    `compose_page` receives the OFFER and never its products -- publish runs from a stream holding only the
    page -- which is the same constraint that put `lead_capture_action` and `pricing_model` on the offer.
    The renderer passes the truth it can see (the products it loaded) on top, so an offer saved before this
    field existed still composes correctly.
    """
    return bool((offer or {}).get("ships_physical"))


def compose_page(
    offer: dict[str, Any], page: dict[str, Any], page_type: str = "landing",
    ships_physical: bool = False,
) -> list[dict[str, Any]]:
    """The Renderable Page Model: page.sections filtered to those the composer deems visible, then ORDERED.

    Order is the composer's job for the same reason visibility is: it is a decision about what the page IS,
    and leaving it to whoever last wrote the sections array is what let every page keep whatever sequence it
    happened to be saved with. A page starts at baseline_order(goal); `page.section_order` records the
    tenant's own arrangement on top of it, and is absent until they actually rearrange something.

    The renderer only iterates the result — it never decides.
    """
    offer_type = page_composition_key(page, offer)
    overrides = page_overrides(page)
    goal = page_goal(page)
    authored = page_type in AUTHORED_PAGE_TYPES
    ships_physical = bool(ships_physical or offer_ships_physical(offer))
    visible = [
        section for section in (page.get("sections") or [])
        if is_section_visible(offer_type, str(section.get("type") or ""), overrides, goal, ships_physical)
    ]
    # NOT ON A FUNNEL STEP OR A THANK-YOU PAGE. The shipping element asks the buyer where to send it, and
    # those pages already know -- the address came from the original Checkout Session, which is also the
    # only address an upsell may use (`upsell_destination` refuses to take one from the browser). Asking
    # again collects an answer nobody acts on, and on an upsell page it sits between the price and the
    # button looking like a step the buyer must complete before they can accept. The postage those pages
    # DO need to state is already on the button, as a delta.
    if not authored:
        visible += derived_shipping_section(offer_type, overrides, goal, visible, ships_physical)
    visible += derived_head_sections(offer_type, overrides, goal, visible)
    if authored:
        return visible
    return order_sections(visible, page.get("section_order") or (), goal)


# Placement governs ORDER + draggability; visibility is the separate `enabled` axis above. Both the
# Python renderer and the Vue builder read these values from the one composition_rules.json, so there is
# no second list to drift (see plans/TODO.md, "silent agreement failures").
PLACEMENT_BANDS = ("lead", "pinned_top", "free", "pinned_bottom")


def element_placement(key: str) -> str:
    """Which band a section sits in. Unknown keys are treated as free — a new element is orderable
    until someone decides otherwise, which is the safe default for rendering."""
    return str((RULES.get("elements", {}).get(key) or {}).get("placement") or "free")


def is_movable(key: str) -> bool:
    """Only `free` sections may be dragged. The hero block is pinned on purpose."""
    return element_placement(key) == "free"


def slot_order(goal: str = "") -> list[str]:
    """The slot vocabulary, in page order. A goal may reorder it via goals.<goal>.slot_order.

    Nine entries, which is the number a human can reorder and defend — and the reason per-goal ordering is
    finally affordable (plans/BUILDER_SECTION_ORDER.md 4d). Re-authoring 39 absolute positions per goal was
    guesswork, which is why §4a supported the hook and deliberately defined none.
    """
    override = ((RULES.get("goals", {}).get(goal) or {}).get("slot_order")) if goal else None
    return list(override or RULES.get("slots", []))


def element_slots(section_type: str) -> list[str]:
    """Which slot each INSTANCE of this element wants, in instance order.

    One entry for almost everything. An element that brackets a page declares more: `event_date` is
    ["announce", "reassure"], so a second Date lands beside the ask instead of against the first one, where
    it says nothing (author, 2026-10-15). Instances past the end stay with the last.
    """
    spec = RULES.get("elements", {}).get(section_type) or {}
    declared = [s for s in (spec.get("slots") or []) if isinstance(s, str)]
    if declared:
        return declared
    slot = spec.get("slot")
    return [slot] if isinstance(slot, str) and slot else []


def element_order_mode(section_type: str) -> str:
    """`ordered` — the skeleton decides — or `authored`, meaning the tenant does.

    An authored element has no inherent position because it has no inherent meaning: a content block is
    whatever the tenant wrote. Slot-ordering one is how a fourth content block jumps BACKWARDS to join the
    first three. Authored elements are absent from the baseline entirely, so `_order_entries` sorts them
    after everything that has a baseline position — i.e. at the end of the free band, in the order they
    were added.
    """
    spec = RULES.get("elements", {}).get(section_type) or {}
    return "authored" if spec.get("order_mode") == "authored" else "ordered"


def baseline_order(goal: str = "") -> list[str]:
    """The default section sequence for a page nobody has reordered (plans/BUILDER_SECTION_ORDER.md 4a/4d).

    DERIVED from the catalog's slots, not authored. §4a researched a good sequence and shipped it as 39
    absolute positions maintained by hand, which gave a new element no rule about where it belongs — so
    every element added since was wedged in by whoever added it, and the list drifted until the default
    read as arbitrary. Declaring a slot is a rule; an index is not.

    A goal may still override the whole sequence via goals.<goal>.default_order (§4a's hook, kept), or
    reorder the slots via goals.<goal>.slot_order, which is the cheap one. Neither is defined today.
    """
    override = ((RULES.get("goals", {}).get(goal) or {}).get("default_order")) if goal else None
    if override:
        return list(override)
    slots = {slot: index for index, slot in enumerate(slot_order(goal))}
    tail = len(slots)
    entries = []
    for position, (key, spec) in enumerate(RULES.get("elements", {}).items()):
        band = spec.get("placement") or "free"
        if band == "none":
            continue
        if band != "free":
            # The locked bands carry no slot and need none — `_order_entries` sorts by band first, so all
            # that matters is their order WITHIN the band. They must still be here: dropping them left the
            # hero block (seo_title/hero_media/hero/headline/subheadline) tying on "not in the baseline",
            # which made the H1's position depend on the sections array.
            entries.append((PLACEMENT_BANDS.index(band), -1, 0, position, key))
            continue
        if element_order_mode(key) == "authored":
            continue
        first = (element_slots(key) or [""])[0]
        entries.append((PLACEMENT_BANDS.index("free"), slots.get(first, tail),
                        int(spec.get("rank") or 0), position, key))
    return [key for *_, key in sorted(entries)]


def _order_entries(entries, tenant_order=(), goal: str = ""):
    """THE ordering rule, in one place — the JS mirror is pageComposer.orderEntries().

    Takes (key, type) pairs and returns the INDICES that sort them, so callers map back to whatever they
    actually hold — keys in one case, section dicts in the other — without this function knowing either.

    Every caller adapts its input to (key, type) pairs, because the rule needs both: the key is what the
    tenant's drag order is recorded against, and the TYPE is what has a baseline position. Two versions of
    this rule — one over keys, one over sections — is precisely what let the builder's row list and the
    rendered page disagree, since a repeatable element keys by id and an id is never in the baseline.

    lead -> pinned_top -> tenant-ordered free -> pinned_bottom. Entries missing from `tenant_order` fall back
    to the baseline position of their type, so a tenant who never drags anything still gets a researched
    sequence. An entry in neither list sorts last rather than first. Ties keep their incoming position.
    """
    entries = list(entries)
    order = baseline_order(goal)
    baseline = {key: index for index, key in enumerate(order)}
    rank = {key: index for index, key in enumerate(tenant_order)}
    fallback = len(rank)
    tail = len(baseline)

    # A SECOND instance of a bracketing element takes the next slot its type declares, not the position of
    # the first one. `event_date` is ["announce", "reassure"], so the second Date lands beside the ask.
    # Counted over the incoming entries, which is why this is computed once rather than inside sort_key.
    seen: dict[str, int] = {}
    instance_baseline: dict[int, int] = {}
    slots = {slot: index for index, slot in enumerate(slot_order(goal))}
    for index, (_, section_type) in enumerate(entries):
        declared = element_slots(section_type)
        count = seen.get(section_type, 0)
        seen[section_type] = count + 1
        if count == 0 or len(declared) <= 1:
            continue
        # Instances past the end stay with the LAST declared slot rather than falling back to the first —
        # a third Date belongs with the second, not back at the top.
        wanted_slot = declared[min(count, len(declared) - 1)]
        # Position it as if it were the first element of that later slot, so it sorts among that slot's
        # members rather than ahead of all of them.
        wanted = slots.get(wanted_slot)
        if wanted is None:
            continue
        nearest = [baseline.get(key, tail) for key in order
                   if (element_slots(key) or [""])[0] == wanted_slot]
        instance_baseline[index] = min(nearest) if nearest else tail

    def sort_key(pair):
        index, (key, section_type) = pair
        band = element_placement(section_type)
        band_index = PLACEMENT_BANDS.index(band) if band in PLACEMENT_BANDS else PLACEMENT_BANDS.index("free")
        if key in rank:
            within = rank[key]
        else:
            within = fallback + instance_baseline.get(index, baseline.get(section_type, tail))
        return (band_index, within, index)

    return [index for index, _ in sorted(enumerate(entries), key=sort_key)]


def order_section_keys(keys, tenant_order=(), goal: str = "") -> list[str]:
    """Order section KEYS. A bare string key is its own type; pass a (key, type) pair when they differ,
    which is exactly the repeatable case.

    Filters `placement: "none"` because this builds the DRAGGABLE ROW LIST, and a none-placed section
    (structured_data) has no row. That filter belongs here and nowhere else.
    """
    entries = [(key, key) if isinstance(key, str) else (key[0], key[1]) for key in keys]
    return [
        entries[index][0] for index in _order_entries(entries, tenant_order, goal)
        if element_placement(entries[index][1]) != "none"
    ]


def section_order_key(section: dict[str, Any]) -> str:
    """The key a section is ordered by — the JS mirror is pageComposer.sectionOrderKey().

    Repeatable types can appear several times on one page, so those key by their element id; everything
    else keys by TYPE, which is the vocabulary the builder's Page Sections panel already speaks.
    """
    section_type = str((section or {}).get("type") or "")
    spec = RULES.get("elements", {}).get(section_type) or {}
    section_id = str((section or {}).get("id") or "")
    return section_id if (spec.get("repeatable") and section_id) else section_type


def order_sections(sections, tenant_order=(), goal: str = "") -> list[dict[str, Any]]:
    """Order real section objects — the JS mirror is pageComposer.orderSections().

    Orders; never filters. `placement: "none"` means "not a draggable row", which is order_section_keys'
    business, not "not a section": structured_data is the head-channel JSON-LD, and dropping it here strips
    a page's rich results. The JS twin had exactly that bug.
    """
    sections = list(sections)
    entries = [(section_order_key(section), str(section.get("type") or "")) for section in sections]
    return [sections[index] for index in _order_entries(entries, tenant_order, goal)]


def recommended_section_keys(offer_type: str, goal: str = "") -> list[str]:
    """Governed sections visible by default for this offer_type + goal (the builder's 'Recommended' group)."""
    return [key for key in RULES.get("governed_sections", []) if default_visible(offer_type, key, goal)]


def optional_section_keys(offer_type: str, goal: str = "") -> list[str]:
    """Governed sections hidden by default — the tenant can opt them in ('Other available' group)."""
    return [key for key in RULES.get("governed_sections", []) if not default_visible(offer_type, key, goal)]


def allowed_ctas(offer_type: str) -> list[str]:
    return list(_offer_type_rule(offer_type).get("allowed_ctas") or [])
