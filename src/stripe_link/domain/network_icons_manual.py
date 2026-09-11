"""Brand glyphs drawn by hand, for networks the generated set cannot supply.

Separate from `network_icons.py` on purpose: that file is GENERATED and rewritten wholesale by
`scripts/generate_network_icons.py`, so anything hand-authored there would be destroyed the next time the
upstream set was refreshed. Merged over the generated table in `social_links.py`, manual winning.

**Why these are not in simple-icons.** LinkedIn asked to be removed from that icon set. That request is about
one library redistributing the mark as a downloadable asset; it is not a rule that nobody may show a LinkedIn
icon on a link to a LinkedIn profile, which is ordinary nominative use and what every product in this category
does. So the answer was never "we cannot show it" -- it was "we should not lift it from a library whose
maintainers were asked to stop handing it out". Drawing it is a different act, and the right one.

**Every path here was rendered and looked at before it shipped**, because `plans/CREATOR_LINK_POLICY.md` and
the generator both say brand marks are the one glyph where "close enough" is not a thing, and authoring by
hand is exactly the risk that warning describes. A path that is subtly wrong is invisible in review and
obvious on a tenant's page.

If you add one: keep it 24x24 and single-path with no fill-rule, since the renderer supplies a bare
`<svg fill="currentColor">` wrapper. Carve counters by drawing them in the OPPOSITE direction to the shape
that encloses them -- the default nonzero winding then treats them as holes, which is how the glyphs in the
generated set do it too.

The brand owner's own usage guidelines govern the mark itself: do not restyle it, keep its clear space, and do
not use it in a way that implies the network endorses the page.
"""

# The fallback for a host we have no mark for. NOT a brand mark, so there is no reference to be faithful to --
# but it was still rendered and looked at, because a glyph that reads as a smudge at 22px is worse than the
# words it replaces. A globe rather than a question mark or a broken-link icon: the link works, we simply do
# not recognise where it goes, and the tenant typed it deliberately.
#
# Annulus + equator bar + meridian ring, each a subpath, counters carved by winding direction.
GLOBE_ICON_PATH = (
    "M12 1A11 11 0 1 1 12 23 11 11 0 1 1 12 1ZM12 2.8A9.2 9.2 0 1 0 12 21.2 9.2 9.2 0 1 0 12 2.8Z"
    "M1.9 11.15H22.1V12.85H1.9ZM12 1A5.4 11 0 1 1 12 23 5.4 11 0 1 1 12 1Z"
    "M12 2.8A3.7 9.2 0 1 0 12 21.2 3.7 9.2 0 1 0 12 2.8Z"
)

MANUAL_ICON_PATHS = {
    # Fansly: two ring-lobes over a wedge, with the aperture ring below. Not in simple-icons, so this was
    # TRACED -- the author supplied a reference, which was sampled to an ASCII map to measure the lobe radius,
    # the rim thickness and the ring's position rather than eyeballing them, then rendered and compared at the
    # 22px it actually displays at. It is a faithful reconstruction, not a copy of an official asset: the
    # interlocking tails of the real mark are simplified to a wedge, which is invisible at this size.
    #
    # Drawn as a UNION (three same-direction subpaths: two circles and the wedge) with the counters carved
    # against them. The wedge's top edge sits below the lobe holes on purpose -- overlap there would re-fill
    # them under nonzero winding and the holes would render as half-moons.
    "fansly.com": (
        "M6.9 2.9A4.3 4.3 0 1 1 6.9 11.5 4.3 4.3 0 1 1 6.9 2.9ZM17.1 2.9A4.3 4.3 0 1 1 17.1 11.5"
        " 4.3 4.3 0 1 1 17.1 2.9ZM4.2 10.2 19.8 10.2 12 20.9ZM6.9 4.5A2.75 2.75 0 1 0 6.9 10"
        " 2.75 2.75 0 1 0 6.9 4.5ZM17.1 4.5A2.75 2.75 0 1 0 17.1 10 2.75 2.75 0 1 0 17.1 4.5Z"
        "M12 12.2A2.45 2.45 0 1 0 12 17.1 2.45 2.45 0 1 0 12 12.2ZM12 13.25A1.4 1.4 0 1 1 12 16.05"
        " 1.4 1.4 0 1 1 12 13.25ZM13.2 13A0.7 0.7 0 1 0 13.2 14.4 0.7 0.7 0 1 0 13.2 13Z"
    ),
    # The "in" square. Rounded rect drawn clockwise; the dot, the i-stem and the n are drawn
    # counter-clockwise so they knock out of it. Rendered at 240px and compared against the mark on
    # linkedin.com before committing.
    "linkedin.com": (
        "M2.5 0h19A2.5 2.5 0 0 1 24 2.5v19a2.5 2.5 0 0 1-2.5 2.5h-19A2.5 2.5 0 0 1 0 21.5v-19"
        "A2.5 2.5 0 0 1 2.5 0ZM7.1 20V9.3H3.9V20h3.2ZM5.5 7.9a1.85 1.85 0 1 0 0-3.7 1.85 1.85 0 0 0 0 3.7Z"
        "M20.4 20v-6.1c0-3.2-1.7-4.7-4-4.7a3.5 3.5 0 0 0-3.1 1.7V9.3H10.1V20h3.2v-5.9c0-1.6.3-3.1 2.3-3.1"
        "s2 1.8 2 3.2V20h2.8Z"
    ),
}
