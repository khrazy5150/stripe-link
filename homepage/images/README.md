# homepage/images

Bundled static assets for the marketing homepage (served from `https://juniorbay.com/images/`).

- **`hero.jpg`** — the hero photo (creator live-selling her own product). Referenced by
  `index.html` and used as the Open Graph / Twitter share image. Place the provided photo here.
  Recommended: export at ~1024×1000, optimized JPEG (or WebP as `hero.webp` + update the `<img>`).
- **`ellie.jpg`** — the avatar photo for the "Ellie's Kitchen" phone mockup in the capability
  infographic. Square-ish or portrait works; it's cropped to a 76px circle (`object-position` favors
  the face). Optimize small (~200px is plenty).
- **`prop-launch.jpg`**, **`prop-sell.jpg`**, **`prop-brand.jpg`** — the three value-prop card images
  (top of each card). **Portrait** orientation; displayed in a `4 / 5` slot with `object-fit: cover`,
  so any portrait crop works. ~800px wide is plenty. Change the slot shape via `.prop-media`
  `aspect-ratio` in `css/style.css`.
