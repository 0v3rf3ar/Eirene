---
name: pdf
description: Anything with PDF files — read or extract text and tables, merge, split, rotate, crop, watermark, create new PDFs, fill forms (fillable or not), encrypt or decrypt, extract images, and OCR scanned pages. Use whenever a .pdf is mentioned as input or someone asks for one as output.
---

# PDF

This covers the everyday PDF jobs with Python libraries and command-line tools.
For more advanced techniques, JavaScript libraries and troubleshooting, read
`reference.md`. **To fill in a form, read `forms.md` and follow it step by step.**

**Requirements** (check what is installed; ask before installing):

- Python: `pypdf` (merge, split, rotate, encrypt), `pdfplumber` (text, tables,
  layout), `reportlab` (create);
- Poppler: `pdftotext`, `pdftoppm`, `pdfimages`, `pdfinfo`, `pdfunite`,
  `pdfseparate`;
- optional: `qpdf` (repair, linearise, page selection), `tesseract` (OCR),
  Node.js with `pdf-lib` (forms — the scripts in `scripts/` use it).

## Start here

```python
from pypdf import PdfReader

reader = PdfReader("document.pdf")
print(len(reader.pages), "pages")
text = "\n".join(page.extract_text() or "" for page in reader.pages)
```

If `extract_text()` returns little or nothing on a page that clearly has words,
the PDF is scanned: see "Scanned PDFs (OCR)".

## pypdf — pages and files

**Merge**

```python
from pypdf import PdfWriter

writer = PdfWriter()
for name in ["a.pdf", "b.pdf", "c.pdf"]:
    writer.append(name)
writer.write("merged.pdf")
```

**Split into single pages**

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
for number, page in enumerate(reader.pages, 1):
    writer = PdfWriter()
    writer.add_page(page)
    writer.write(f"page_{number}.pdf")
```

**Pick pages** (`writer.append("input.pdf", pages=(0, 5))` takes pages 1–5).

**Metadata**

```python
meta = PdfReader("document.pdf").metadata
print(meta.title, meta.author, meta.subject, meta.creator)
```

**Rotate**

```python
reader = PdfReader("input.pdf")
writer = PdfWriter()
for page in reader.pages:
    writer.add_page(page.rotate(90))   # clockwise, multiples of 90
writer.write("rotated.pdf")
```

**Watermark or stamp** — make a one-page PDF with the mark (for example with
reportlab), then:

```python
mark = PdfReader("watermark.pdf").pages[0]
reader = PdfReader("document.pdf")
writer = PdfWriter()
for page in reader.pages:
    page.merge_page(mark)          # on top; use mark.merge_page(page) on a copy for underneath
    writer.add_page(page)
writer.write("watermarked.pdf")
```

**Passwords**

```python
reader = PdfReader("input.pdf")
writer = PdfWriter(clone_from=reader)
writer.encrypt(user_password="open-me", owner_password="owner-secret", algorithm="AES-256")
writer.write("encrypted.pdf")

locked = PdfReader("encrypted.pdf")
if locked.is_encrypted:
    locked.decrypt("open-me")
```

Only remove protection from files the person is entitled to unlock.

## pdfplumber — text, layout and tables

```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        print(page.extract_text())                 # reading order with line breaks
        for table in page.extract_tables():        # lists of rows
            for row in table:
                print(row)
```

All tables into one spreadsheet:

```python
import pandas as pd
import pdfplumber

frames = []
with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        for table in page.extract_tables():
            if table and len(table) > 1:
                frames.append(pd.DataFrame(table[1:], columns=table[0]))
if frames:
    pd.concat(frames, ignore_index=True).to_excel("tables.xlsx", index=False)
```

Check extracted tables against the page image: merged cells, wrapped headers
and tables split across pages often need fixing by hand. `reference.md` shows
tuning `table_settings`.

## reportlab — new PDFs

**Simple drawing**

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("hello.pdf", pagesize=letter)
width, height = letter
c.setFont("Helvetica", 12)
c.drawString(72, height - 72, "Hello")
c.line(72, height - 80, width - 72, height - 80)
c.showPage()
c.save()
```

**Documents with flowing text** (Platypus handles wrapping and page breaks):

```python
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

styles = getSampleStyleSheet()
story = [Paragraph("Report title", styles["Title"]), Spacer(1, 12),
         Paragraph("Body text. " * 40, styles["BodyText"]), PageBreak(),
         Paragraph("Second page", styles["Heading1"])]
SimpleDocTemplate("report.pdf", pagesize=A4).build(story)
```

**Subscripts and superscripts:** never use Unicode sub/superscript characters
(₀₁₂…, ⁰¹²…) with reportlab's built-in fonts; they have no such glyphs and print
as black boxes. In a `Paragraph` use markup — `H<sub>2</sub>O`,
`x<super>2</super>`. On the canvas, draw the digit smaller and shifted.

**Other characters:** the built-in fonts cover Latin-1 only. For anything else
(curly quotes are fine; Greek, Cyrillic, CJK, most symbols are not), register a
TrueType font: `pdfmetrics.registerFont(TTFont("DejaVu", "DejaVuSans.ttf"))`.

**Check the result:** render it (`pdftoppm -png -r 80 out.pdf page`) and look at
the pages, if your model can read images.

## Command line

**Poppler**

```bash
pdftotext input.pdf out.txt              # text
pdftotext -layout input.pdf out.txt      # keep columns and alignment
pdftotext -f 2 -l 5 input.pdf out.txt    # pages 2–5
pdfinfo input.pdf                        # pages, size, encryption, producer
pdfunite a.pdf b.pdf merged.pdf          # merge
pdfseparate input.pdf page-%d.pdf        # split
pdfimages -list input.pdf                # list embedded images
pdfimages -all input.pdf img             # extract them in their own formats
pdftoppm -png -r 150 input.pdf page      # render pages
```

**qpdf**

```bash
qpdf --empty --pages a.pdf b.pdf -- merged.pdf
qpdf input.pdf --pages . 1-5 -- first-five.pdf
qpdf input.pdf out.pdf --rotate=+90:1          # rotate page 1
qpdf --password=SECRET --decrypt locked.pdf open.pdf
qpdf --check input.pdf                         # structure check
```

## Scanned PDFs (OCR)

```bash
pdftoppm -png -r 300 scanned.pdf page
for f in page-*.png; do tesseract "$f" "${f%.png}"; done      # page-N.txt
```

To make the PDF itself searchable, `ocrmypdf scanned.pdf searchable.pdf` (if
installed) adds a hidden text layer. In Python: `pytesseract.image_to_string`
on images from `pdf2image.convert_from_path`. If your model can read images, you
can also read rendered pages directly for short documents.

## Quick reference

| Task | Tool | How |
| --- | --- | --- |
| Merge | pypdf / pdfunite / qpdf | `writer.append(...)` |
| Split | pypdf / pdfseparate | one page per writer |
| Text | pdfplumber / pdftotext | `page.extract_text()` |
| Tables | pdfplumber | `page.extract_tables()` |
| Create | reportlab | canvas or Platypus |
| Render pages | pdftoppm | `pdftoppm -png -r 150` |
| Images out | pdfimages | `pdfimages -all` |
| OCR | tesseract | render first |
| Fill forms | `scripts/` + `forms.md` | follow forms.md |

## Next

- `forms.md` — filling forms, fillable or not. Follow it in order.
- `reference.md` — pypdfium2, pdf-lib and pdf.js, advanced Poppler and qpdf,
  coordinates and cropping, batch work, troubleshooting.
