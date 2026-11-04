---
name: pptx
description: >
  Create, read, edit and design PowerPoint decks (.pptx) and templates (.potx):
  pitch decks, presentations, slides from a template, speaker notes, combining
  or splitting decks. Load it before writing any code or XML that creates or
  changes a .pptx, even when a library such as pptxgenjs or python-pptx is
  already installed and the task looks simple: it has the design rules, the
  library pitfalls that corrupt files, and the required validation and visual
  check. Also use it to pull text out of a deck, and whenever someone asks for a
  deck, slides or a presentation as a PowerPoint file.
---

# PowerPoint decks (.pptx)

A `.pptx` is a ZIP of XML parts. Pick the approach by task:

| Task | Approach |
| --- | --- |
| **Create** a deck | a script using `pptxgenjs` (pitfalls below) |
| **Edit** a deck, or build from a template | unpack → edit `ppt/slides/slideN.xml` → pack |
| **Read** a deck | `python scripts/extract_text.py deck.pptx` (or `markitdown deck.pptx`); layouts at a glance: `python scripts/thumbnail.py deck.pptx` |

**Requirements:** Node.js with `pptxgenjs` (`npm install pptxgenjs`) to create;
LibreOffice and Poppler's `pdftoppm` to render; Pillow for thumbnails. Other
scripts use only Python's standard library. Check what is installed and ask
before installing.

## Scripts

Paths are relative to this skill's folder.

| Script | Does |
| --- | --- |
| `scripts/extract_text.py deck.pptx` | text per slide in order (`<!-- Slide N: slideX.xml -->`), tables as rows, speaker notes |
| `scripts/thumbnail.py deck.pptx [PREFIX]` | a labelled grid of every slide for choosing layouts; prints the image paths |
| `scripts/add_slide.py DIR slide2.xml [--after slideN.xml]` | duplicate a slide, or start one from `slideLayoutN.xml`, with all the bookkeeping; also takes a `.pptx` with `-o` |
| `scripts/clean.py DIR` | delete slides missing from `<p:sldIdLst>` and every part nothing uses any more |
| `scripts/office/validate.py deck.pptx [--original SRC]` | relationships, content types, slide list, slide XML and chart faults PowerPoint refuses; each message names the fix |
| `scripts/office/package.py unpack/pack` | safe unzip and correct re-zip |
| `scripts/office/soffice.py …` | LibreOffice headless with a private profile, so it cannot hang |

## Creating with pptxgenjs

Try `require("pptxgenjs")` first; install only if it fails. The traps:

- **Set `pres.layout` before adding slides.** The default `LAYOUT_16x9` is
  **10 × 5.625 in**, not 13.33 in wide (`LAYOUT_WIDE` is 13.33 × 7.5). Shapes
  placed past the edge are written anyway and are simply off the slide.
- **Colors are 6-digit hex without `#`:** `color: "FF0000"`. `"#FF0000"` or an
  8-digit hex with alpha **corrupts the file**. For translucency use
  `transparency: 0–100` on fills and images and `opacity: 0–1` on shadows; each is
  ignored on the other.
- **Option objects are mutated in place** (converted to EMU on first use). Never
  reuse one `shadow` or options object across two `add*` calls; build a new one
  each time.
- **Shadow `offset` must be ≥ 0**; a negative one corrupts the file. For an upward
  shadow use `angle: 270` with a positive offset.
- **Letter spacing is `charSpacing`.** `letterSpacing` is silently ignored.
- **Lists:** `bullet: true` on each item, never a typed `•` (you get two). Set
  `breakLine: true` on every item but the last. Space items with
  `paraSpaceAfter`, not `lineSpacing`.
- **One `new pptxgen()` per file**; never reuse an instance.
- **`rectRadius` only works on `ROUNDED_RECTANGLE`.**
- **No gradient fills** — use a gradient image as the background.
- **Text boxes have inner padding.** Set `margin: 0` when text must line up with a
  shape, line or icon at the same x.
- **Speaker notes:** `slide.addNotes("…")`, once per slide; never a text box.
- **Keep charts native** with `addChart()` (an array of `{type, data, options}`
  makes a combo). Compute extras such as trend lines as additional series rather
  than pasting an image. Only chart types PowerPoint cannot draw (Sankey, network,
  chord) go in as images.
- **Default charts look bare.** Set `showTitle` and `title`, `showValue: true`
  with `dataLabelPosition`, `chartColors` from your palette, quiet axes
  (`catAxisLabelColor`, `valAxisLabelColor`, `valGridLine: { color, size }`,
  `catGridLine: { style: "none" }`) and `showLegend: false` for one series.
- **Stacked bar/column labels:** `dataLabelPosition` must be `ctr`, `inEnd` or
  `inBase`. `outEnd` **corrupts the file**.
- **Secondary axes:** a combo series with `secondaryValAxis`/`secondaryCatAxis`
  needs both `valAxes` and `catAxes` on the chart options, two entries each.
  Otherwise the chart refers to axes it never declares and PowerPoint drops it and
  calls the file corrupt.
- **Run the validator after `writeFile()`:**
  `python scripts/office/validate.py deck.pptx`. It catches the chart faults
  above and slide XML PowerPoint refuses. Fix the generator, not the packed XML.
- **Do not reorder `<p:presentation>`'s children.** pptxgenjs writes
  `<p:notesMasterIdLst>` after `<p:sldIdLst>` and PowerPoint accepts it; moving it
  can make the deck unopenable.
- **Icons:** render an icon set (for example `react-icons` via
  `ReactDOMServer.renderToStaticMarkup`) to SVG, rasterise at 256 px or more with
  `sharp`, and add with `addImage({ data: "image/png;base64," + png.toString("base64") })`
  — the `image/png;base64,` prefix is required.

## Editing decks and templates

Look at the layouts first:

```bash
python scripts/thumbnail.py template.pptx template-thumbs
python scripts/extract_text.py template.pptx
```

The thumbnail grid labels each slide with its file name. Map each section of your
content onto a template slide, and vary the layouts — not every section on the same
title-and-bullets slide. (The grid is for choosing layouts; for checking your own
work, render full-size pages as in "Visual check". It needs a `.pptx`, so copy a
`.potx` to a `.pptx` name first.)

```bash
python scripts/office/package.py unpack deck.pptx unpacked
python scripts/add_slide.py unpacked slide2.xml --after slide2.xml   # prints the new slide's path
# reorder or remove slides by editing <p:sldIdLst> in ppt/presentation.xml
python scripts/clean.py unpacked                                     # after removals
# now edit the text in ppt/slides/slideN.xml
python scripts/office/package.py pack unpacked out.pptx
python scripts/office/validate.py out.pptx --original deck.pptx
```

- **Do all structural work — add, remove, reorder — before editing content.**
  `add_slide.py` copies a slide as it is, so duplicating after editing clones your
  edits; `clean.py` deletes any slide missing from `<p:sldIdLst>`, including one you
  just made but have not listed.
- **Never copy slide files by hand.** `add_slide.py` registers the slide everywhere
  it must be. On a packed file, pass `-o` or it rewrites the input. A duplicated
  slide still *shares* its source's charts, SmartArt and embedded objects; editing
  one changes both.
- **python-pptx** cannot duplicate slides, flattens formatting when you assign
  `text_frame.text` (set `run.text` instead), and cannot read the SVG/EMF art many
  templates use.
- Convert legacy `.ppt` first:
  `python scripts/office/soffice.py --convert-to pptx file.ppt`. `.potx` unpacks and
  packs the same way; keep the `.potx` extension.
- To reuse a template's icon or image, duplicate a slide or layout that has it.

Filling a template:

- Edit XML with `xml.dom.minidom` or careful text edits. `xml.etree.ElementTree`
  rewrites namespace prefixes and corrupts decks.
- **Slots are not items.** If the template shows four people and you have three,
  delete the fourth person's whole group (picture and text boxes), not just the
  text — then look for orphaned visuals.
- One `<a:p>` per list item, never several items in one paragraph. Copy the
  sibling's `<a:pPr>` to keep spacing; put `b="1"` on the `<a:rPr>` of titles,
  headings and inline labels ("Status:", "Owner:").
- Let bullets come from the layout. Add `<a:buChar>`, `<a:buAutoNum>` or
  `<a:buNone>` only to override; never a typed `•`.
- Text with leading or trailing spaces needs `xml:space="preserve"` on its `<a:t>`.

## Design

**Plain bullets on white are forgettable.** For every slide, pick from the ideas
below.

### Before you start

- **A palette for this subject.** If your colors would work just as well for an
  unrelated deck, they are not specific enough.
- **Dominance, not balance.** One color carries 60–70% of the visual weight, with
  one or two supporting tones and one sharp accent.
- **Contrast in structure.** Dark title and closing slides with light content
  slides, or dark throughout for a premium feel.
- **One motif, repeated** — rounded image frames, icons in colored circles — on
  every slide. Not a color bar or stripe (see "Avoid").

### Palettes to start from

| Theme | Primary | Secondary | Accent |
| --- | --- | --- | --- |
| Midnight Executive | `1E2761` navy | `CADCFC` ice blue | `FFFFFF` white |
| Forest & Moss | `2C5F2D` forest | `97BC62` moss | `F5F5F5` off-white |
| Coral Energy | `F96167` coral | `F9E795` gold | `2F3C7E` navy |
| Warm Terracotta | `B85042` terracotta | `E7E8D1` sand | `A7BEAE` sage |
| Ocean Gradient | `065A82` deep blue | `1C7293` teal | `21295C` midnight |
| Charcoal Minimal | `36454F` charcoal | `F2F2F2` off-white | `212121` black |
| Teal Trust | `028090` teal | `00A896` seafoam | `02C39A` mint |
| Berry & Cream | `6D2E46` berry | `A26769` dusty rose | `ECE2D0` cream |
| Sage Calm | `84B59F` sage | `69A297` eucalyptus | `50808E` slate |
| Cherry Bold | `990011` cherry | `FCF6F5` off-white | `2F3C7E` navy |

The `theme-factory` skill has more themes with font pairings.

### Each slide

**Every slide gets a visual** — an image, chart, icon or shape.

Layouts:

- two columns: text on one side, a picture on the other;
- icon rows: an icon in a colored circle, a bold heading, a line of description;
- a 2×2 or 2×3 grid of blocks, optionally beside an image;
- a half-bleed image down one side with content over the other.

Data:

- big numbers (60–72 pt) with small labels;
- comparison columns: before/after, pros/cons, options side by side;
- timelines and process flows with numbered steps.

Polish:

- small icons in colored circles beside section headings;
- italic accent text for a key number or tagline.

### Type

**Your fonts are drawn by the viewer's PowerPoint, but you check the deck with
LibreOffice**, which substitutes fonts it lacks — sometimes with different widths,
so the preview can show overflow that will not happen, or hide overflow that will.

- **Safe** (same widths in LibreOffice, shipped with Office): Arial, Calibri,
  Cambria, Times New Roman, Courier New, Bookman Old Style, Century Schoolbook. Use
  them for body text and anywhere fit matters.
- **Character without risk:** a safe serif for headings (Cambria, Bookman Old
  Style, Century Schoolbook) with Calibri or Arial for body.
- **When someone asks for another font** (Georgia, Trebuchet MS…), use it where
  asked, give those boxes about 10% extra room, and do not trust the preview's fit
  for them.
- **Unreliable in preview:** Georgia, Trebuchet MS, Impact, Arial Black, Garamond,
  Consolas, Palatino Linotype, and often Calibri Light — fine for titles with
  slack.
- **Avoid Aptos by default:** no metric-compatible substitute for checking, and
  older Office versions lack it.

| Element | Size |
| --- | --- |
| Slide title | 36–44 pt bold |
| Section heading | 20–24 pt bold |
| Body | 14–16 pt |
| Captions | 10–12 pt, muted |

### Spacing

- at least 0.5 in from the slide edges;
- 0.3–0.5 in between blocks, the same value throughout;
- room to breathe — do not fill every inch.

### Avoid

- the same layout on slide after slide;
- centered body text (center titles only; left-align paragraphs and lists);
- weak size contrast between titles and body;
- blue by default when the subject suggests something else;
- uneven gaps;
- one designed slide among plain ones — commit, or keep it simple throughout;
- text-only slides;
- forgetting text-box padding when aligning text with shapes (`margin: 0`);
- low contrast — light on light, dark on dark, for text and icons;
- **accent lines under titles** — a hallmark of generated slides; use space or
  background color instead;
- **decorative bars and stripes** — full-width header or footer bars, a stripe down
  one edge of the slide or of a card, single-side borders. Set a card apart with a
  tint, a shadow or an icon instead;
- cream or beige backgrounds by default — use white (`FFFFFF`) or the brand palette
  when none is given;
- **text that overflows its box** — shrink it, split the slide, or enlarge the box.

## Checking the deck (required)

The first render usually has a few real problems — overflow, overlap,
misalignment. Find them, fix them, re-render the slides you changed, and stop.

### Content

```bash
python scripts/extract_text.py output.pptx
```

Look for missing content, typos and wrong order. With a template, look for
leftover placeholder text:

```bash
python scripts/extract_text.py output.pptx | grep -iE "\bx{3,}\b|lorem|ipsum|\bTODO|\[insert|click to (add|edit)"
```

Fix anything it finds.

### File

```bash
python scripts/office/validate.py output.pptx                       # built from scratch
python scripts/office/validate.py output.pptx --original source.pptx  # built from a template
```

For a template-based deck always pass `--original`, so problems the template
already had are not reported as yours (and real regressions are not hidden among
them). pptxgenjs can produce chart XML that every other tool accepts and
PowerPoint refuses; the validator names the fix — make it in the generator and
rebuild.

### Visual check

```bash
python scripts/office/soffice.py --convert-to pdf --outdir render output.pptx
rm -f render/slide-*.png
pdftoppm -png -r 110 render/output.pdf render/slide
ls -1 "$PWD"/render/slide-*.png
```

View every image (Eirene's `read_image`, if your model can see images).
`pdftoppm` pads numbers to the page count: `slide-1.png` under 10 slides,
`slide-01.png` for 10–99. After fixes, run all four commands again — the PDF must
be regenerated from the edited deck.

After staring at the code you tend to see what you meant rather than what
rendered. Look at the images fresh; if you can delegate (`delegate_tasks`), a
reviewer with only the images and this checklist works well. Look for:

- **text overflowing or cut off at a box or slide edge — check first**; it is the
  most common defect (for fonts the preview renders unreliably, trust the slack
  you left);
- overlapping elements — text through shapes, lines through words;
- footers or citations colliding with content;
- elements closer than 0.3 in, or cards nearly touching;
- uneven gaps — a large hole in one place, crowding in another;
- less than 0.5 in from the slide edge;
- columns or repeated elements out of alignment;
- low-contrast text or icons;
- template decoration left in the wrong place after text changed (an underline
  sized for one line under a title that now wraps);
- boxes so narrow the text wraps every few words;
- leftover placeholder content.
