---
name: theme-factory
description: Apply a consistent color and font theme to slides, documents, reports, HTML pages and other artifacts. Offers 10 ready-made themes with palettes and font pairings, and can create a new theme on request.
---

# Theme factory

A set of professional themes — each a coordinated color palette plus a header and
body font pairing — that you can apply to any artifact: a slide deck, a document,
a report, a landing page.

Each theme gives you:

- a palette of four colors with hex codes and their roles;
- a font for headers and one for body text;
- a short note on where it fits best.

## Workflow

1. **Show the themes.** Open `showcase.html` (a single page with every theme's
   swatches and type) so the person can compare them. If they cannot open HTML,
   list the ten themes below with their four hex values. Do not edit the
   showcase.
2. **Ask** which theme to use.
3. **Wait** for an explicit choice before applying anything.
4. **Apply** the chosen theme, as described below.

## Themes

Full definitions are in `themes/`:

1. **Ocean Depths** — calm, professional, maritime (`themes/ocean-depths.md`)
2. **Sunset Boulevard** — warm, energetic sunset colors (`themes/sunset-boulevard.md`)
3. **Forest Canopy** — grounded earth tones (`themes/forest-canopy.md`)
4. **Modern Minimalist** — clean contemporary greys (`themes/modern-minimalist.md`)
5. **Golden Hour** — rich autumn warmth (`themes/golden-hour.md`)
6. **Arctic Frost** — cool, crisp winter blues (`themes/arctic-frost.md`)
7. **Desert Rose** — soft, dusty, refined (`themes/desert-rose.md`)
8. **Tech Innovation** — bold high-contrast tech (`themes/tech-innovation.md`)
9. **Botanical Garden** — fresh garden colors (`themes/botanical-garden.md`)
10. **Midnight Galaxy** — dramatic deep purples (`themes/midnight-galaxy.md`)

## Applying a theme

1. Read the chosen file in `themes/`.
2. Use its colors and fonts consistently across the whole artifact: backgrounds,
   headings, body text, accents, charts.
3. Check contrast and readability; use the darkest color for text on light
   backgrounds and the lightest on dark ones.
4. Keep the theme's character on every slide or page.

The fonts are common open fonts (DejaVu, FreeSans/FreeSerif). If one is not
installed, use the nearest available family and say so. For web output, declare
a fallback stack, for example `"DejaVu Sans", Verdana, sans-serif`.

## A new theme

When none of the ten fit, make one. Use whatever the person described — a mood,
an industry, a brand color — to choose four colors and a font pairing, and give it
an evocative name in the same style as the others. Write it out in the same shape
as a file in `themes/` and show it for review. Apply it only once the person
approves.
