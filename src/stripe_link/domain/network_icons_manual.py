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
    # Fansly: two padlocks rotated into a heart, with the keyhole ring on the left lock's body -- the author's
    # own description ("two square locks in the shape of a heart") is what finally made the construction legible.
    #
    # TRACED, not hand-fitted. Six attempts at fitting arcs by eye all failed on the same thing: the real mark
    # is two interlocking LOCKS, and every approximation I reached for (a solid heart, ring-lobes over a wedge)
    # was a different shape that merely looked heart-ish. So this comes off the reference bitmap the author
    # supplied -- thresholded to a mask, unioned as pixel cells, smoothed with an open/close and simplified to
    # a 0.055 tolerance in the 24-unit box, then rendered and checked at 240px AND at the 22px it displays at.
    # Polygonal rather than arc-based, which is why it is longer than the generated marks; still under
    # Instagram's, and indistinguishable at any size this is used.
    #
    # Regenerate with scratch tooling if the mark ever changes; there is no upstream to pull it from, since
    # Fansly is not in simple-icons.
    "fansly.com": (
        "M1 9.01 1.36 10.37 1.82 11.28 2.43 12.08 11.30 20.86 11.60 21.05 12.29 21.05 12.61 20.86 18.53 15 "
        "19.45 13.99 19.35 13.69 14.56 8.90 13.97 8.42 13.90 8.28 13.97 8.13 15.76 6.35 16.58 5.80 17.13 "
        "5.62 18.13 5.62 18.68 5.80 19.32 6.16 19.96 6.90 20.24 7.54 20.25 7.87 20.34 8.02 20.25 8.99 19.61 "
        "10.10 18.24 11.46 18.21 11.69 19.73 13.23 20.04 13.39 20.33 13.23 21.31 12.26 22.19 11.17 22.73 "
        "10.11 22.91 9.47 22.91 9.15 23 9.01 23 7.54 22.82 6.71 22.36 5.62 21.66 4.65 20.77 3.86 19.78 3.31 "
        "18.61 2.95 16.77 2.95 16.62 3.04 16.31 3.04 15.12 3.50 13.86 4.40 6.38 11.89 6.20 11.96 4.22 10.02 "
        "3.76 9.28 3.57 8.64 3.58 7.91 3.76 7.27 4.13 6.62 4.59 6.16 5.41 5.71 5.81 5.61 6.69 5.62 7.33 5.80 "
        "7.79 6.08 9.26 7.56 9.65 7.74 11.28 6.14 11.38 5.86 9.68 4.12 9.33 3.86 8.25 3.31 7.16 3.04 5.59 "
        "3.04 4.49 3.31 3.41 3.86 2.08 5.09 1.36 6.35 1.18 6.90 1 7.72ZM9.25 13.70 9.34 13.55 9.35 13.21 "
        "9.62 12.58 10.26 11.85 11.10 11.38 11.48 11.29 12.43 11.29 13.36 11.65 14.01 12.21 14.39 12.77 "
        "14.57 13.32 14.66 14.03 14.57 14.18 14.57 14.60 14.20 15.41 13.47 16.15 12.63 16.52 11.66 16.61 "
        "10.99 16.43 10.44 16.15 9.72 15.43 9.34 14.58ZM10.27 13.49 10.23 14.44 10.51 15 11.04 15.44 11.49 "
        "15.63 12.40 15.64 12.95 15.36 13.40 14.92 13.59 14.54 13.69 13.75 13.58 13.34 13.44 13.24 12.88 "
        "13.33 12.65 13.22 12.36 12.83 12.29 12.27 11.43 12.27 11.04 12.46 10.60 12.81Z"
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
