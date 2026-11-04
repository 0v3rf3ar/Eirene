---
name: canvas-design
description: Create original static visual art — posters, prints, covers, abstract compositions, single-page designs — as PNG or PDF, guided by a design philosophy written first. Use when someone asks for a poster, artwork, design or other static visual piece. Always original; never copy an existing artist's work.
---

# Canvas design

You make the work in two steps, and deliver only `.md`, `.pdf` and `.png` files:

1. **A design philosophy** — written to a `.md` file.
2. **The piece** — that philosophy expressed on a canvas, as `.pdf` or `.png`.

**Requirements:** Python 3 with Pillow (`pip install pillow`) for PNG work, or
reportlab / cairo for vector PDF. Use what is installed; ask before installing.
`scripts/fonts.py` downloads open-licensed fonts (see "Type" below). If your
model can read images, look at every render you produce.

## Step 1 — the design philosophy

Write a **visual** philosophy — an aesthetic worldview, not a layout or template —
that will be carried out through:

- form, space, color and composition;
- images, graphics, shapes and patterns;
- a little text, used as a visual accent.

### What this step is

- **What you were given:** the person's request, which may be slight. Treat it as
  a foundation, not a cage.
- **What you write:** the manifesto of an art movement.
- **What happens next:** you take that manifesto and express it visually, in work
  that is about 90% visual design and 10% essential text.

The philosophy must put visual expression first: meaning carried by space, form
and color, interpreted artistically, with very few words.

### Writing it

**Name the movement** in one or two words: "Brutalist Joy", "Chromatic Silence",
"Metabolist Dreams".

**Describe it in 4–6 paragraphs**, concise but complete, covering how it shows up
in:

- space and form;
- color and material;
- scale and rhythm;
- composition and balance;
- visual hierarchy.

Rules:

- **No repetition.** Mention each aspect once; come back to color, space or type
  only to add depth.
- **Insist on craft, more than once.** The philosophy must say repeatedly that the
  finished work should look as if it took countless hours, was made with great
  care, and comes from someone at the very top of the field. Use language like
  "meticulously crafted", "the product of deep expertise", "painstaking
  attention", "master-level execution".
- **Leave room.** Be specific about direction but brief enough that the execution
  step still has interpretive choices to make, also at the highest level of
  craft.
- **Keep it general.** Do not mention what the piece is for; the philosophy should
  read as if it could guide any work in the movement.

The philosophy should push toward visual expression, never toward explanatory
text. Information lives in the design.

### Short examples

These are compressed; yours should be 4–6 full paragraphs.

**Concrete Poetry** — communication through monumental form and bold geometry.
Huge blocks of color, sculptural type (one enormous word, tiny labels),
Brutalist divisions of space; the energy of Polish posters meeting Le Corbusier.
Meaning through weight and tension, not explanation. Text is a rare, forceful
gesture built into the architecture of the page. Every element placed with a
master's precision.

**Chromatic Language** — color as the main information system. Geometric
precision in which zones of color carry meaning; small sans-serif labels let the
fields speak. Albers' studies of color interaction crossed with data graphics.
Words only anchor what color already shows. The result of painstaking chromatic
calibration.

**Analog Meditation** — quiet contemplation through texture and air. Paper grain,
ink bleed, vast empty space. Image dominates; type is whispered. The pacing of a
Japanese photobook. Short phrases at most. Each composition balanced with the
care of a meditation practice.

**Organic Systems** — clustering and modular growth. Rounded forms, organic
arrangements, natural color held in an architectural structure. Information as
diagrams, spatial relationships and marks; text only as small floating labels.
The composition tells the story through expert spatial orchestration.

**Geometric Silence** — order and restraint. Grid precision, stark graphics or
bold photography, dramatic negative space. Small exact type, large quiet zones;
Swiss formalism with Brutalist honesty about material. Structure speaks. Every
alignment the result of many refinements.

### Principles

- **Visual philosophy:** an aesthetic worldview to be expressed in design.
- **Minimal text:** sparse, essential, part of the visual — never long.
- **Spatial expression:** ideas carried by space, form, color and composition.
- **Artistic freedom:** leave the execution room to interpret.
- **Pure design:** you are making an art object, not a decorated document.
- **Expert craft:** say, more than once, that it must look meticulously made.

Save the philosophy as a `.md` file (for example `philosophy.md`).

## Step 2 — find the hidden subject

Before you draw, work out the conceptual thread in the original request.

The subject becomes a **subtle reference inside the work**, refined rather than
literal. Someone who knows the subject should sense it; anyone else simply sees a
strong abstract composition. The philosophy is the language; the subject is the
quiet DNA running through form, color and arrangement. Think of a jazz musician
quoting another tune: the people who know will catch it, and everyone enjoys the
music.

## Step 3 — make the canvas

With the philosophy and the subject settled, make the piece. Pause and collect
your thinking first.

**Always art.** Even when the subject is a film, game or book, keep the approach
sophisticated. Nothing cartoonish or amateur.

**Museum or magazine quality.** By default, one highly visual, design-led page as
PDF or PNG (more only if asked). Favour repeated patterns and precise shapes.
Treat the abstract philosophy as if it were a field guide: borrow the visual
language of systematic observation — dense accumulations of marks, repeated
elements, layered patterns that build meaning through patience and reward long
looking. Add sparse, clinical type and systematic reference marks, as if this
were a plate from an imaginary science, giving an invisible subject the reverence
usually reserved for observed phenomena. Anchor it with a phrase or a small
detail, placed quietly, in a limited palette that feels deliberate. The result
should feel like evidence that something fleeting can be studied, mapped and
understood through careful attention.

**Type.** Text stays minimal and visual-first, but context decides whether that
means near-silent labels or a bold typographic gesture: a punk venue poster
shouts more than a ceramics studio identity. Mostly use light weights. Make the
type part of the art; if the piece is abstract, bring the letters into the
composition rather than typesetting them on top.

Use distinctive fonts, not the system defaults. `scripts/fonts.py` downloads
open-licensed families from Google Fonts into a folder you choose:

```bash
python scripts/fonts.py --list                       # suggested families by character
python scripts/fonts.py "Instrument Serif" "Work Sans:300,600" --dest fonts
```

It prints the `.ttf` paths to load with Pillow (`ImageFont.truetype`) or
reportlab. Keep each font's licence file with any work you hand over.

Downloading needs network access. If it is not available (an unattended run, or
access declined), use fonts already installed — `fc-list : family file` lists
them on Linux; look in `/Library/Fonts` and `~/Library/Fonts` on macOS and
`C:\Windows\Fonts` on Windows — and choose the most distinctive ones there
rather than falling back to a default face.

**Containment is not negotiable.** Whatever the scale of the type, nothing runs
off the canvas and nothing collides. Every element sits inside the edges with
real margins and clear space around it. Measure text with the font's metrics
(`font.getbbox`, `textbbox`) before placing it; do not guess.

**Craft.** For work that reads as human-made, it has to look as though it took
countless hours by someone at the top of the field: composition, spacing, color,
type, every detail. Check that nothing overlaps and every edge is clean. Make
something that would convince an expert.

Render at print resolution (for example 3000–5000 px on the long side for PNG, or
vector PDF), then look at the output and fix what you see.

Deliver the `.pdf` or `.png` together with the philosophy `.md`, and give the
paths.

## Step 4 — refine

Assume the person has already said: "It isn't perfect enough. It must be
pristine — a masterpiece of craft, ready to hang in a museum."

Refine rather than add. Do not reach for more graphics, a filter or a new font.
Make what is already there sharper and more coherent, true to the philosophy and
to minimalism. If your instinct is to call a new function or draw a new shape,
stop and ask: "How can I make what is already here more of a work of art?"

Then make a second pass through the code and polish again.

## More pages

When asked for several pages, make each a distinct variation on the same
philosophy — related, but not repetitive. Put them in one PDF or a numbered set of
PNGs. Treat the first page as one page of a coffee-table book: the next ones are
twists and echoes of it, and together they can tell a quiet story. Full creative
freedom.
