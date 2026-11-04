---
name: docx
description: >
  Create, read, edit and review Word documents (.docx) and templates (.dotx):
  reports, memos, letters, contracts, templates with headings, tables of
  contents, page numbers, images, tracked changes and comments. Load it before
  writing any code or XML that creates or changes a .docx, even when a library
  such as docx or python-docx is already installed: it has the pitfalls that
  break documents and the required render check. Use it whenever a Word file is
  the input or the deliverable, including find-and-replace, redlining,
  commenting, or turning content into a polished .docx. Not for PDFs,
  spreadsheets or Google Docs.
---

# Word documents (.docx)

A `.docx` is a ZIP of XML parts. Pick the approach by task:

| Task | Approach |
| --- | --- |
| **Create** a document | a script using the `docx` npm package (pitfalls below) |
| **Edit** an existing document | unpack → edit `word/document.xml` → pack (the `docx` package cannot open files) |
| **Read** the content | `python scripts/docx_text.py file.docx`, or `pandoc -t markdown file.docx` |

Paths below are relative to this skill's folder. Scripts need only Python 3's
standard library unless noted.

**Requirements:** Node.js with `docx` (`npm install docx`) to create; LibreOffice
for rendering and conversion; Poppler's `pdftoppm` to turn pages into images;
`pandoc` optional for reading. Check what is installed and ask before installing.

## Creating with `docx`

Try `require("docx")` first; install it only if that fails. You know the API; these
are the traps:

- **Page size defaults to A4.** For US Letter set
  `page: { size: { width: 12240, height: 15840 } }` (DXA: 1440 = 1 inch). Ask or
  infer from the audience; do not leave A4 for a US reader by accident.
- **Landscape:** give portrait dimensions plus
  `orientation: PageOrientation.LANDSCAPE`; the library swaps them.
- **Tables need widths twice:** `columnWidths` on the table *and* `width` on every
  cell, both in `WidthType.DXA`, summing to the table width. Percentages break in
  Google Docs.
- **Cell shading:** `ShadingType.CLEAR` with a `fill`. `SOLID` paints the cell
  black.
- **Lists:** never type `•`. Define a `numbering` config with
  `LevelFormat.BULLET` (or `DECIMAL`) and reference it from each paragraph.
- **`ImageRun` needs `type`** (`"png"`, `"jpg"`, …) and explicit
  `transformation` width/height.
- **`PageBreak` goes inside a `Paragraph`.**
- **No `\n` in text.** One `Paragraph` per line or paragraph; `break: 1` on a
  `TextRun` for a soft line break.
- **Table of contents:** headings must use the built-in `HeadingLevel.*`, or a
  custom style with `outlineLevel`, or they will not appear. Word fills in the
  TOC when the document is opened (fields update); say so to the person.
- **Horizontal rules:** a paragraph bottom border, not an empty table.
- **Right-aligned text on the same line, dot leaders:** a `PositionalTab`
  (`alignment: PositionalTabAlignment.RIGHT`, `leader: PositionalTabLeader.DOT`)
  inside a `TextRun`, never padding with dots or spaces. LibreOffice does not draw
  positional tabs, so the preview shows the text run together; Word shows it
  correctly. If the preview must match, use a right tab stop with a dot leader
  on the paragraph instead (`tabStops: [{ type: TabStopType.RIGHT, position:
  TabStopPosition.MAX, leader: "dot" }]` and a `\t` in the text).
- **Fonts:** set a document default (`styles.default.document.run.font`); pick
  fonts the reader will have (Calibri, Arial, Cambria, Times New Roman, Georgia).

## Check what you made

After writing a `.docx`, render it and look at the pages:

```bash
python scripts/office/soffice.py --convert-to pdf --outdir out output.docx
pdftoppm -png -r 80 out/output.pdf out/page
ls out/page-*.png
```

Then view the images (Eirene's `read_image`, if your model can see images).
`pdftoppm` pads page numbers to the width of the page count (`page-01.png` …
`page-12.png`). Check layout, page breaks, tables, images and headers. Also run
the structural check:

```bash
python scripts/office/validate.py output.docx
```

## Editing an existing document

Convert legacy `.doc` first:
`python scripts/office/soffice.py --convert-to docx file.doc`.

```bash
python scripts/office/package.py unpack doc.docx unpacked      # safe unzip: no symlinks, no paths outside
python scripts/merge_runs.py unpacked                          # join fragmented runs so text can be found
# edit unpacked/word/document.xml in place — targeted edits, no reformatting or pretty-printing
python scripts/office/package.py pack unpacked out.docx
python scripts/office/validate.py out.docx --original doc.docx
```

Word splits visible text into many `<w:r>` runs (revision ids, spell-check marks),
so a phrase you can read is often not a single string in the XML.
`merge_runs.py` joins neighbouring runs with identical formatting without changing
how the document looks. It also takes a packed file:
`python scripts/merge_runs.py doc.docx -o merged.docx`.

Files from other people are untrusted: always unpack with `package.py`, which
refuses symlinks and paths that escape the folder.

When you script XML changes, edit with `xml.dom.minidom` (as the scripts here do)
or with careful text edits. Round-tripping through `xml.etree.ElementTree`
renames namespace prefixes and drops declarations that `mc:Ignorable` relies on,
which corrupts the file.

Text with leading or trailing spaces needs `xml:space="preserve"` on its `<w:t>`.

## Tracked changes (redlining)

To edit as tracked changes, wrap what you change:

- inserted runs in `<w:ins w:id="…" w:author="…" w:date="…">…</w:ins>`;
- deleted runs in `<w:del …>…</w:del>`, where the text element is
  `<w:delText>`, not `<w:t>`;
- each change gets its own `w:id`, unique among all changes;
- to delete a whole paragraph, wrap every run in `<w:del>` **and** mark the
  paragraph mark deleted:
  `<w:pPr><w:rPr><w:del w:id=".." w:author=".." w:date=".."/></w:rPr></w:pPr>`
  — the `<w:del/>` comes before the `<w:rPr>`'s other children (the schema
  fixes the order). A deleted paragraph mark means "join this paragraph to the
  next".

Then check that nothing slipped through untracked:

```bash
python scripts/office/validate.py out.docx --original doc.docx --author "Your Name"
```

It rejects every change made under that author and compares the result with the
original text; any difference is an edit you made without tracking it — easy to
do, and invisible when changes are shown accepted.

**Clean copy with every change accepted:**

```bash
python scripts/accept_changes.py in.docx out.docx
```

It keeps insertions, removes deletions, resolves moves and formatting changes,
drops deleted table rows, and joins paragraphs whose marks were deleted the way
Word does, so a fully deleted paragraph disappears rather than leaving an empty
(often bulleted) line. Other converters, such as `pandoc
--track-changes=accept`, do not join those paragraphs; an empty bullet in their
output is an artefact of the converter, not a defect in the document.

## Comments

Comments need several linked parts. Use the helper:

```bash
python scripts/comment.py unpacked "The fee cap looks too low" --anchor "capped at" --author "Your Name"
python scripts/comment.py unpacked "Agreed" --parent 0            # a threaded reply
python scripts/comment.py contract.docx "Check this date" --anchor "1 March" -o reviewed.docx
```

It writes `comments.xml`, `commentsExtended.xml`, `commentsIds.xml` and
`commentsExtensible.xml`, their relationships and content types, and prints the
new id. `--anchor` places the comment on the first occurrence of that text (run
`merge_runs.py` first so it sits in one run). Without `--anchor` it prints the
`<w:commentRangeStart>`, `<w:commentRangeEnd>` and `<w:commentReference>` markers
to place yourself — until they are in `word/document.xml`, the comment exists
but does not show. Replies go on their parent's range automatically.

## Reading

```bash
python scripts/docx_text.py file.docx                 # headings, lists, tables, comments; standard library only
python scripts/docx_text.py file.docx --changes       # tracked changes marked [+inserted+] [-deleted-]
pandoc -t markdown file.docx                          # if pandoc is installed
```

Do not read documents with LibreOffice's text export (`--convert-to txt`): on
documents with tables it can loop and write gigabytes. `soffice.py` stops a
conversion whose output passes 512 MB, but the reader above is the right tool.

For layout questions, render to images as in "Check what you made".

## Scripts

| Script | Does |
| --- | --- |
| `scripts/office/package.py unpack FILE DIR` / `pack DIR FILE` | safe unzip / zip with the right part order |
| `scripts/office/validate.py FILE [--original SRC] [--author NAME]` | structure, relationships, content types, tracked-change and comment bookkeeping; untracked-edit check |
| `scripts/office/soffice.py …` | LibreOffice headless with a private profile, so it cannot hang on a lock |
| `scripts/merge_runs.py DIR-or-FILE [-o OUT]` | merge identically formatted runs |
| `scripts/comment.py DIR-or-FILE TEXT [--anchor T] [--parent ID]` | add comments and replies |
| `scripts/accept_changes.py IN [OUT]` | accept every tracked change |
| `scripts/docx_text.py FILE [--changes]` | read a document as Markdown-style text |
