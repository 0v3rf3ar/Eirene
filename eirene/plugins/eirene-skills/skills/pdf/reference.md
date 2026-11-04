# PDF reference

Techniques beyond the basics in `SKILL.md`.

## Coordinates

PDF space has its origin at the **bottom-left** of the page, in points (1/72 in).
A US Letter page is 612 × 792; A4 is 595 × 842. pdfplumber, `pdftotext -bbox`
and page images use a **top-left** origin instead:

- `y_top = page_height − y_bottom`
- `x_px = x_pt × dpi / 72`, `y_px = y_top × dpi / 72` at a given render dpi.

A page's visible area is its CropBox (defaults to the MediaBox), which may not
start at (0, 0) — add its lower-left corner when placing things. `/Rotate`
turns the page when displayed but not its coordinate system.

## pypdfium2 (fast rendering and text)

```python
import pypdfium2 as pdfium

pdf = pdfium.PdfDocument("document.pdf")
page = pdf[0]
image = page.render(scale=2).to_pil()        # 144 dpi
image.save("page_1.png")
text = page.get_textpage().get_text_range()
for index in range(len(pdf)):
    pdf[index].render(scale=1.5).to_pil().save(f"page_{index + 1}.png")
```

Useful when Poppler is not installed; it bundles PDFium.

## JavaScript

### pdf-lib (create and modify)

```javascript
const { PDFDocument, StandardFonts, rgb, degrees } = require("pdf-lib");
const fs = require("fs");

// Modify an existing file
const doc = await PDFDocument.load(fs.readFileSync("input.pdf"));
const font = await doc.embedFont(StandardFonts.Helvetica);
const [first] = doc.getPages();
const { width, height } = first.getSize();
first.drawText("CONFIDENTIAL", { x: width / 2 - 120, y: height / 2, size: 48, font,
                                 color: rgb(0.8, 0.1, 0.1), opacity: 0.25, rotate: degrees(30) });
fs.writeFileSync("stamped.pdf", await doc.save());

// Merge selected pages
const out = await PDFDocument.create();
for (const name of ["a.pdf", "b.pdf"]) {
  const src = await PDFDocument.load(fs.readFileSync(name));
  const pages = await out.copyPages(src, src.getPageIndices());
  pages.forEach((p) => out.addPage(p));
}
fs.writeFileSync("merged.pdf", await out.save());

// A new document
const fresh = await PDFDocument.create();
const page = fresh.addPage([595, 842]);                     // A4
const bold = await fresh.embedFont(StandardFonts.HelveticaBold);
page.drawText("Invoice", { x: 50, y: 780, size: 24, font: bold });
page.drawRectangle({ x: 50, y: 700, width: 495, height: 1, color: rgb(0.7, 0.7, 0.7) });
const png = await fresh.embedPng(fs.readFileSync("logo.png"));
page.drawImage(png, { x: 445, y: 760, width: 100, height: 40 });
fs.writeFileSync("invoice.pdf", await fresh.save());
```

Standard fonts cover WinAnsi (Western European) characters only; for others,
`npm install @pdf-lib/fontkit`, `doc.registerFontkit(fontkit)`, then
`doc.embedFont(fs.readFileSync("DejaVuSans.ttf"))`. Forms: see `forms.md` and the
scripts.

### pdf.js (`pdfjs-dist`) — text with positions

```javascript
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";

const pdf = await getDocument({ url: "document.pdf" }).promise;
for (let n = 1; n <= pdf.numPages; n++) {
  const page = await pdf.getPage(n);
  const { items } = await page.getTextContent();
  for (const item of items) {
    const [, , , , x, y] = item.transform;        // bottom-left origin
    console.log(n, x.toFixed(1), y.toFixed(1), item.str);
  }
  const annotations = await page.getAnnotations(); // links, form widgets
}
```

## Poppler, further

```bash
pdftotext -bbox-layout input.pdf words.html      # every word with xMin/yMin/xMax/yMax (top-left origin)
pdftotext -tsv input.pdf words.tsv               # newer Poppler: the same as a table
pdftoppm -png -r 300 -f 3 -l 3 input.pdf p       # one page, print resolution
pdftoppm -jpeg -jpegopt quality=85 -r 150 input.pdf p
pdftoppm -png -x 0 -y 0 -W 800 -H 400 -r 150 input.pdf crop   # a region
pdfimages -list input.pdf                        # size, colour space, dpi of each image
pdfimages -all -f 2 -l 4 input.pdf img           # originals, pages 2–4
pdffonts input.pdf                               # fonts and whether embedded
```

## qpdf, further

```bash
qpdf --split-pages=10 input.pdf part-%d.pdf          # groups of 10 pages
qpdf input.pdf --pages . 1,3-5,z -- picked.pdf       # z = last page; r1 = last too
qpdf --empty --pages a.pdf 1-2 b.pdf 5 -- mix.pdf
qpdf --linearize input.pdf web.pdf                   # fast web view
qpdf --object-streams=generate --compress-streams=y input.pdf smaller.pdf
qpdf input.pdf repaired.pdf                          # rewriting often repairs damage
qpdf --show-encryption input.pdf
qpdf --encrypt USER OWNER 256 --print=none --modify=none -- input.pdf locked.pdf
qpdf --json input.pdf | head                         # inspect structure
```

## pdfplumber, further

```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    page = pdf.pages[0]
    for word in page.extract_words():                     # x0, x1, top, bottom (top-left origin)
        print(word["text"], word["x0"], word["top"])
    region = page.crop((0, 0, page.width, 200))          # (x0, top, x1, bottom)
    print(region.extract_text())
    tables = page.extract_tables(table_settings={
        "vertical_strategy": "lines",                     # or "text" when the table has no rules
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "intersection_tolerance": 5,
    })
    page.to_image(resolution=120).debug_tablefinder().save("tables.png")   # see what it found
```

Use `"text"` strategies for tables drawn without lines. The debug image is the
quickest way to tune settings.

## reportlab tables

```python
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

rows = [["Item", "Qty", "Price"], ["Widget", "3", "$12.00"], ["Gadget", "1", "$40.00"]]
table = Table(rows, colWidths=[260, 80, 100], repeatRows=1)
table.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f8")]),
]))
styles = getSampleStyleSheet()
SimpleDocTemplate("table.pdf", pagesize=A4).build([Paragraph("Order", styles["Title"]), Spacer(1, 12), table])
```

Wrap long cell text in `Paragraph` objects so it wraps. `repeatRows=1` repeats
the header on each page.

## Recipes

### Images out of a PDF

```bash
pdfimages -all input.pdf img          # originals, fastest
```

For figures that are vector drawings (not embedded images), render the page and
crop the region:

```python
import pypdfium2 as pdfium
page = pdfium.PdfDocument("paper.pdf")[3]
image = page.render(scale=300 / 72).to_pil()
image.crop((x0, top, x1, bottom)).save("figure.png")    # pixels at 300 dpi
```

### Crop pages

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()
for page in reader.pages:
    page.cropbox.lower_left = (50, 50)        # points, bottom-left origin
    page.cropbox.upper_right = (562, 742)
    writer.add_page(page)
writer.write("cropped.pdf")
```

### Many files, robustly

```python
from pathlib import Path
from pypdf import PdfReader
from pypdf.errors import PdfReadError

failures = []
for path in sorted(Path("inbox").glob("*.pdf")):
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            failures.append((path.name, "password required"))
            continue
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        Path("out", path.stem + ".txt").write_text(text, encoding="utf-8")
    except (PdfReadError, OSError) as exc:
        failures.append((path.name, str(exc)))
print(f"{len(failures)} failed:", *failures, sep="\n  ")
```

Report failures instead of stopping at the first one.

## Performance

- **Large files:** process page by page; do not build one huge string or list of
  images. `pdftoppm -f/-l` renders ranges.
- **Text:** `pdftotext` is much faster than Python libraries for plain text;
  pdfplumber is slower but gives positions and tables.
- **Images:** `pdfimages` extracts without re-encoding; rendering whole pages is
  slower and larger.
- **Forms:** fill with the scripts; flatten only at the end, if at all.
- **Memory:** close documents (`with pdfplumber.open(...)`, `pdf.close()` for
  pypdfium2) inside loops.

## Troubleshooting

**Encrypted:** `reader.is_encrypted`; many files open with an empty user password
(`reader.decrypt("")`) and only restrict printing or editing. Otherwise ask for the
password. Do not try to break protection.

**Damaged:** `qpdf input.pdf repaired.pdf`, or open with
`PdfReader(path, strict=False)`. `qpdf --check` describes the damage.

**No text, or garbage like `(cid:12)`:** the page is scanned, or its fonts lack a
Unicode map. OCR the rendered page (see SKILL.md), or read the page image
directly.

**Wrong reading order or merged columns:** try `pdftotext -layout`, or crop
columns with pdfplumber and extract each.

**Missing characters in a PDF you made:** the font lacks the glyphs — embed a
TrueType font that has them.
