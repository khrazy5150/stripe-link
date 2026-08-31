# Mobile editing

Status: PLANNED, not built. Long-term. Written 2026-08-31.
Related: `plans/TODO.md` (⭐ HIGH — the dashboard is not usable on a phone),
`plans/BUILDER_SECTION_ORDER.md` (the restructure that makes this tractable).

---

## 1. The decision

**Target: full parity — a tenant should eventually be able to do everything on a phone.**
**Accepted for now: landing-page EDITING is desktop-only.**

Those are not in conflict. Parity is the destination; the builder is the one screen expensive enough to
defer. Everything else on the phone is ordinary responsive work with real value on its own.

## 2. What is actually broken

Measured 2026-08-31, not assumed. `dashboard/src/styles.css` carries **three** responsive breakpoints
(two `max-width:900px`, one `max-width:60rem`) and nothing below. The sidebar has **no** collapsed or
drawer state. From a real phone, the menus could not be navigated to reach the builder at all — the
failure is "unreachable", not "cramped".

## 3. Tiers, cheapest and most valuable first

### Tier 0 — the dashboard minus the builder

No design decisions, no new concepts, and it delivers "a tenant can run their business from a phone"
for everything except composing a page.

- **Sidebar → drawer.** THE blocker. It is a fixed column, so on a phone it either eats the screen or
  hides the content behind it. Nothing else is reachable until this exists.
- **Modals full-screen below a phone breakpoint.** Page Settings and the section editor are centred
  cards sized for a laptop.
- **Wide rows → cards.** Orders, Customers, Leads, Invoices, Refunds.
- **Tap targets.** The 2026-08-29 density pass tuned for a mouse (3.2rem controls, 1.2rem text). Add a
  mobile scale; do NOT loosen the desktop values, which are deliberate.

### Tier 1 — reorder without dragging

**Do this regardless of the mobile timeline.** The section reorder uses the HTML5 drag-and-drop API,
which mobile browsers do not fire for touch — so ordering is impossible on a phone. The identical gap
exists for keyboard users on desktop, which makes it a live WCAG 2.1.1 defect today, not a phone
problem.

Explicit move controls (▲/▼ per row) driving the same `moveSectionBefore`. One implementation serves
touch, mouse, keyboard and screen readers. Keep drag as a mouse-only enhancement on top.

**Do not reimplement dragging with pointer events.** That means hand-rolling scroll-vs-drag
disambiguation, momentum and autoscroll, and it is where this normally consumes a week.

### Tier 2 — the builder

The hard one, and less hard than it was a week ago.

The Phase 1/2 restructure accidentally did most of the work: the builder is now **compact rows plus
modal editing**, which is a mobile-native pattern. It also already has the two controls a phone needs —
Hide Form / Show Form, and the device toggle. On a narrow screen the builder is close to a single-pane
app already.

What remains is the SHELL, not the content:
- collapse the two-pane grid to one pane with an explicit Form ⇄ Preview switch (Hide Form is the seed);
- full-screen the editors (Tier 0 covers this);
- handle the iOS keyboard shrinking the viewport under an open modal;
- the preview at 390px on a 390px screen is 1:1, so the device toggle becomes meaningless there — hide
  it or lock it to mobile.

**Build it as the SAME component, responsive.** Do not fork a mobile builder: two implementations of one
screen is the drift shape this codebase has been bitten by repeatedly, and this is the most-changed
screen in the product.

## 4. Decisions to make when picking this up

1. **Is the preview needed WHILE editing on a phone?** Probably not — edit, then look. Every mobile
   editor works that way, and assuming otherwise is what makes the layout hard.
2. **Does the wizard need mobile too?** Creating a page on a phone is a plausible first-run path and is
   much simpler than editing one. It may be worth doing before Tier 2.
3. **Measure before investing in Tier 2.** Instrument whether tenants actually attempt to edit on a
   phone. Tier 0 might satisfy the real demand, and that answer is cheap to get and expensive to guess.

## 5. Sequencing

    Tier 1 (reorder controls)  -> independent, small, fixes a live a11y defect
    Tier 0 (sidebar, modals, cards, targets)  -> unblocks the whole dashboard
    measure  -> do tenants try to edit on a phone?
    Tier 2 (builder shell)  -> only if the answer is yes

Tier 1 first because it is small, self-contained, and fixes a defect that exists on desktop today.
