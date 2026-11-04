---
name: xlsx
description: >
  Create, read, edit, clean and convert spreadsheets: .xlsx, .xlsm, .xltx, .csv
  and .tsv, including formulas, formatting, charts, financial models and messy
  data. Load it before writing any code that creates or changes a workbook, even
  when openpyxl or pandas is already installed: it has the formula rules, the
  pitfalls that lose formulas or values, and the required recalculation check.
  Use it whenever a spreadsheet is the main input or the deliverable, even when
  mentioned casually ("the xlsx in my downloads"). Not for a Word document, an
  HTML report, a standalone script, a database pipeline or a Google Sheets
  integration.
---

# Spreadsheets (.xlsx)

| Task | Approach |
| --- | --- |
| **Create** or **edit** with formulas and formatting | `openpyxl` (pitfalls below) |
| **Bulk data** in or out | `pandas` (`read_excel`, `to_excel`) |
| **Look** at a workbook by cell | `python scripts/show_cells.py file.xlsx` — coordinates, formulas and cached values |
| **Read a model** (formulas *and* values) | two `load_workbook` passes (see pitfalls) |

Paths are relative to this skill's folder.

**Requirements:** `openpyxl` and `pandas` (Python) for building and editing;
LibreOffice for recalculation. `show_cells.py`, `recalc.py` and the validator use
only the standard library. Try the imports first; install only what is missing,
and ask before installing.

## Every workbook you deliver

- **A professional font** throughout (Arial, Calibri, Times New Roman) unless asked
  otherwise.
- **No formula errors.** Do not hand over a file while `recalc.py` reports
  `errors_found`. If you think an error was already there, prove it: open the
  *original* with `data_only=True` and look at that cell. An error you introduced
  looks exactly like one you inherited.
- **Formulas, not pasted results.** Write `ws["B10"] = "=SUM(B2:B9)"`, not a total
  computed in Python. The sheet must update when its inputs change.
- **Follow the request literally:** exact sheet names, exact column headers, the
  formula they described. A clever redesign that computes something else is wrong.
- **Document assumptions and hard-coded numbers** where the reader will see them —
  a cell comment or a note beside the table. Cite real sources
  (`Source: FY2024 annual report, p. 45, revenue note, URL`); when the number came
  from the person, say so.
- **A workbook you create for someone to fill in** gets a short legend saying which
  cells to edit and one example row of realistic values. Never add such a row to a
  file you were asked to edit.
- **When editing someone's file, follow its conventions exactly** — they override
  everything here. Find its input cells first (usually marked by a font color, fill
  or shading), write only there, and leave existing formulas alone.

## Recalculate (required whenever there are formulas)

openpyxl writes formulas as text with **no cached results**. Until the workbook
is recalculated, every formula reads as `None` to anything using cached values —
pandas, `load_workbook(data_only=True)`, most previews.

```bash
python scripts/recalc.py output.xlsx [timeout_seconds]   # default 30
```

LibreOffice recalculates every formula and the file is **rewritten in place**. You
get JSON: `status` (`success` or `errors_found`), `total_formulas`,
`total_errors`, and `error_summary` with up to 100 cell locations per error type
(`locations_truncated` counts the rest; trust `total_errors`). Fix what it names
and run it again. **JSON with an `error` key instead of `status` means nothing was
recalculated** — only that case exits non-zero. `errors_found` exits 0, so read the
status rather than the exit code.

**Clean is not correct.** Recalculation proves formulas *evaluate*, not that they
reference the right cells; an off-by-one range gives a tidy, wrong number. Write
two or three formulas, recalculate, and check they pull what you expect before
filling a whole grid. `show_cells.py --range A1:F20` shows formulas next to their
results.

**Links to other workbooks.** A formula such as `='[1]Returns'!$B$2` refers, by
index, to a *separate file*. That file is rarely available, so the cell's cached
value is all that holds the data. openpyxl drops cached values on save, and
LibreOffice then cannot resolve the link, writes `#NAME?` and removes the link.
`recalc.py` refuses such workbooks: copy the values you need out of the original
before saving over it. `--force` recalculates anyway and accepts the loss.

## Formulas that survive

LibreOffice supports fewer functions than current Excel, and one it cannot evaluate
ends up as `#NAME?` in the file you deliver.

- **Prefer functions from Excel 2007 and earlier** — `SUMIFS`, `COUNTIFS`, `INDEX`,
  `MATCH`, `IFERROR`, `SUMPRODUCT` — which need no prefix.
- **Six later functions work with an `_xlfn.` prefix,** because openpyxl writes the
  formula verbatim and Excel stores newer names prefixed (its interface hides the
  prefix): `_xlfn.TEXTJOIN`, `_xlfn.CONCAT`, `_xlfn.IFS`, `_xlfn.SWITCH`,
  `_xlfn.MAXIFS`, `_xlfn.MINIFS`. Written bare, they give `#NAME?`.
- **Avoid `XLOOKUP`, `XMATCH`, `SORT`, `FILTER`, `UNIQUE` and `SEQUENCE`.** Older
  LibreOffice cannot evaluate them at all; newer versions can, but they are
  spilling array functions and an openpyxl file carries no spill information, so
  only the first cell gets a value while `recalc.py` reports no errors. Use
  `INDEX`/`MATCH` for lookups, and sort, filter and de-duplicate in Python before
  writing.
- A formula LibreOffice could not parse is saved **in lower case** — a quick tell
  next to a `#NAME?`.

## openpyxl pitfalls

- **Reading a model takes two loads.** `data_only=True` gives cached values without
  formulas; the default gives formulas without values.
- **Saving a `data_only=True` workbook destroys its formulas** — every one becomes
  a constant, permanently.
- **`data_only=True` on a file openpyxl just wrote returns `None`** everywhere; run
  `recalc.py` first. (A formula that returns `""` also reads as `None`.)
- **Merged cells:** write only the top-left cell; the others are read-only
  `MergedCell`s.
- **`.xlsm` loses its macros** unless you load with `keep_vba=True`.
- **Sheet names with spaces must be quoted** in references:
  `='Assumptions Inputs'!$B$5`. Unquoted, it evaluates to `#VALUE!`.
- **Column widths and number formats are not automatic.** Set
  `ws.column_dimensions["B"].width` and `cell.number_format` explicitly; freeze the
  header row (`ws.freeze_panes = "A2"`) on data tables.

## CSV and TSV

- Read with an explicit encoding (`utf-8-sig` handles a BOM) and delimiter; check
  for a stray header row, footer totals, merged-cell artefacts and numbers stored
  as text with thousands separators or currency symbols.
- Keep identifiers with leading zeros (postcodes, account numbers) as text.
- Write CSV with `utf-8-sig` when the reader will open it in Excel, so accented
  characters survive.

## Financial models

Unless the person or the existing file says otherwise:

**Colors:** blue text (`0000FF`) for hard-coded inputs and scenario levers; black
for formulas; green (`008000`) for links to other sheets; red (`FF0000`) for links
to other files; yellow fill (`FFFF00`) for key assumptions and cells to fill in.

**Number formats:** currency `$#,##0` with the unit in the header
(`Revenue ($m)`); zeros as `-`, including percentages (`$#,##0;($#,##0);-`);
negatives in parentheses; percentages `0.0%`, **stored as fractions** (`0.15`
shows `15.0%`; `15` shows `1500.0%`); multiples `0.0x`; years as text (`"2024"`,
never `2,024`).

**Structure:** every assumption in its own labelled cell and referenced by the
formulas that use it (`=B5*(1+$B$6)`, never `=B5*1.05`); the same formula across
every period — a single edited cell in the middle of a row is the most common
silent error; guard denominators that can be zero (`=IF(C5=0,0,B5/C5)`).

## Checking the file

```bash
python scripts/recalc.py output.xlsx
python scripts/office/validate.py output.xlsx          # structure, sheet links, shared strings
python scripts/show_cells.py output.xlsx --formulas-only
```

To see the layout, render it: `python scripts/office/soffice.py --convert-to pdf
--outdir render output.xlsx`, then `pdftoppm -png -r 80` and view the images.

## Scripts

| Script | Does |
| --- | --- |
| `scripts/recalc.py FILE [TIMEOUT] [--force]` | recalculate with LibreOffice, save, report errors as JSON |
| `scripts/show_cells.py FILE [--sheet S] [--range A1:H40] [--formulas-only]` | cells by coordinate, with formulas and cached values |
| `scripts/office/validate.py FILE [--original SRC]` | structural checks |
| `scripts/office/soffice.py …` | LibreOffice headless with a private profile |
| `scripts/office/package.py unpack/pack` | safe unzip and re-zip, for XML-level edits |
