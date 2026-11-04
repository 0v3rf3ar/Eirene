# Filling PDF forms

**Do these steps in order. Do not jump ahead to writing your own code.**

Scripts are in `scripts/` (paths relative to this skill's folder). The form tools
use Node.js with `pdf-lib`: if `node scripts/form_fields.mjs` says pdf-lib is
missing, run `npm install pdf-lib` in your working folder (ask first).

## Step 0 — does it have fillable fields?

```bash
node scripts/form_fields.mjs form.pdf field_info.json
```

- It writes `field_info.json` → follow **Fillable forms**.
- It says the PDF has no fillable fields (exit status 2) → follow **Forms without
  fields**.

## Fillable forms

### 1. Read the field list

`field_info.json` lists every field:

```json
[
  {"field_id": "last_name", "page": 1, "rect": [92, 700, 260, 716], "type": "text", "value": "", "max_length": 40},
  {"field_id": "Check12", "page": 1, "rect": [...], "type": "checkbox",
   "checked_value": "/Yes", "unchecked_value": "/Off", "value": "/Off"},
  {"field_id": "contact", "page": 1, "rect": [...], "type": "radio_group",
   "radio_options": [{"value": "email", "rect": [...], "page": 1}, {"value": "phone", "rect": [...], "page": 1}]},
  {"field_id": "country", "page": 2, "rect": [...], "type": "choice",
   "choice_options": [{"value": "NL", "text": "NL"}, {"value": "DE", "text": "DE"}]}
]
```

`rect` is `[left, bottom, right, top]` in PDF points, with y = 0 at the **bottom**
of the page.

### 2. Work out what each field is for

Field ids are often meaningless (`Text7`, `Check12`). Render the pages and match
fields to their printed labels:

```bash
python scripts/pdf_to_images.py form.pdf pages
```

It prints each image's pixel size and the page size in points. To find a field on
the image: `x_px = left × image_width / page_width` and
`y_px = (page_height − top) × image_height / page_height`.

### 3. Write the values

`field_values.json`:

```json
[
  {"field_id": "last_name", "description": "applicant's last name", "page": 1, "value": "Simpson"},
  {"field_id": "Check12", "description": "18 or over", "page": 1, "value": "/Yes"},
  {"field_id": "contact", "description": "preferred contact", "page": 1, "value": "email"}
]
```

- text: a string;
- checkbox: `true`/`false`, or its `checked_value` / `"/Off"`;
- radio group: one of its `radio_options` values;
- choice: one of its `choice_options` values.

Only fill what you have real information for. Leave the rest empty and tell the
person which fields still need them — never invent personal details.

### 4. Fill

```bash
node scripts/fill_fields.mjs form.pdf field_values.json filled.pdf
```

It checks every id and value first; if it lists problems, fix the JSON and run it
again — nothing is written until all entries are valid. Add `--flatten` to bake
the values in so they can no longer be edited (only when asked).

### 5. Check

```bash
node scripts/form_fields.mjs filled.pdf | grep -A1 '"field_id"'
python scripts/pdf_to_images.py filled.pdf check
```

Look at the rendered pages and confirm every value sits in the right place.

## Forms without fields

You will write text onto the page at measured positions. Get coordinates from the
PDF's own structure when you can (precise), and estimate from images only when you
must.

### Step 1 — extract the structure

```bash
python scripts/form_structure.py form.pdf form_structure.json
```

Per page it lists:

- **labels** — every word with `x0, top, x1, bottom`;
- **lines** — horizontal rules (`x0, x1, y`), which usually mark entry rows;
- **checkboxes** — small squares with their centres;
- **row_boundaries** — the distinct y positions of the rules;
- `pdf_width`, `pdf_height`.

Coordinates are PDF points with y = 0 at the **top**, growing downwards (the
opposite of `field_info.json`). Lines and checkboxes need `pdfplumber`; without
it only words are found.

If the labels are meaningful words, use **Approach A**. If there are few or none
(a scanned form, or text showing as `(cid:12)`), use **Approach B**.

### Approach A — from the structure (preferred)

**A.1 Read the layout.**

1. **Group labels:** neighbouring words that form one label ("Last" + "Name").
2. **Rows:** labels with about the same `top` are on one row.
3. **Entry areas** start just after a label (`x0 = label.x1 + 5`) and run to the
   next label or the end of the rule.
4. **Checkboxes:** use their coordinates as given.

**A.2 Look for what was missed.** Round checkboxes, unusual controls, decorative
or very light elements are not detected. Render the pages
(`python scripts/pdf_to_images.py form.pdf pages`) and compare. For anything
missing, measure it visually (Approach B) and convert to points (see
"Mixing both").

**A.3 Write fields.json** with `pdf_width`/`pdf_height`, which tells the filler the
numbers are PDF points:

```json
{
  "pages": [{"page_number": 1, "pdf_width": 612, "pdf_height": 792}],
  "form_fields": [
    {"page_number": 1, "description": "Last name", "field_label": "Last Name",
     "label_bounding_box": [43, 63, 87, 73], "entry_bounding_box": [92, 63, 260, 79],
     "entry_text": {"text": "Smith", "font_size": 10}},
    {"page_number": 1, "description": "Citizen: yes", "field_label": "Yes",
     "label_bounding_box": [260, 200, 280, 210], "entry_bounding_box": [285, 197, 292, 205],
     "entry_text": {"text": "X"}}
  ]
}
```

Text fields: `entry x0 = label x1 + 5`; `entry x1` = next label's `x0` or the
rule's end; `top` = the label's top; `bottom` = the rule below, or label bottom
plus the row height. Checkboxes: the box's own coordinates.

**A.4 Check the boxes** — see Step 2.

### Approach B — from images (fallback)

**B.1 Render** the pages: `python scripts/pdf_to_images.py form.pdf pages`.

**B.2 Rough positions.** On each page image, find each label, its entry area
(line, box or blank) and each checkbox, and note approximate pixel coordinates.

**B.3 Zoom to refine — this is what makes it accurate.** Crop around each rough
position with about 50 px of margin and measure precisely:

```python
from PIL import Image
page = Image.open("pages/page_1.png")
x, y, w, h = 50, 120, 300, 80                   # crop origin and size
page.crop((x, y, x + w, y + h)).resize((w * 3, h * 3)).save("crops/name.png")
```

(ImageMagick works too: `magick pages/page_1.png -crop 300x80+50+120 +repage crops/name.png`,
or `convert` on older versions.) In the crop, find where the entry area starts and
ends and its top and bottom, then convert back: `full_x = x + crop_x / 3`,
`full_y = y + crop_y / 3` (dividing by the zoom you used). Crop neighbouring
fields together to save steps.

**B.4 Write fields.json** with `image_width`/`image_height` (the rendered image's
pixel size), which tells the filler the numbers are pixels:

```json
{
  "pages": [{"page_number": 1, "image_width": 1545, "image_height": 2000}],
  "form_fields": [
    {"page_number": 1, "description": "Last name", "field_label": "Last Name",
     "label_bounding_box": [120, 175, 242, 198], "entry_bounding_box": [255, 175, 720, 218],
     "entry_text": {"text": "Smith", "font_size": 10}}
  ]
}
```

### Mixing both

When the structure covers most fields but misses some:

1. use Approach A for what it found;
2. measure the missing ones on the images (B.3);
3. convert those to points — `pdf_x = image_x × pdf_width / image_width`,
   `pdf_y = image_y × pdf_height / image_height` — and
4. write everything in **one** coordinate system, PDF points with
   `pdf_width`/`pdf_height`.

### Step 2 — check before filling

```bash
python scripts/check_boxes.py fields.json
python scripts/validation_image.py pages/page_1.png fields.json 1 check_1.png
```

`check_boxes.py` reports overlapping boxes and boxes too short for the font size.
The validation image draws entry boxes in red and labels in blue, numbered: look at
it and fix anything misplaced before filling.

### Step 3 — fill

```bash
node scripts/fill_annotations.mjs form.pdf fields.json filled.pdf
```

It converts the coordinates, writes each entry in Helvetica, vertically centred,
shrinking text that would not fit, and centres single characters such as "X" in
checkboxes. Rotated pages are refused: rotate them upright first
(`page.rotate(...)` with pypdf, or `qpdf --rotate`), then measure.

### Step 4 — check the result

```bash
python scripts/pdf_to_images.py filled.pdf check
```

If text is out of place:

- **Approach A:** the coordinates must come from `form_structure.json`, with
  `pdf_width`/`pdf_height`.
- **Approach B:** `image_width`/`image_height` must match the images you measured
  on, and the pixel positions must be from the full image, not a crop.
- **Mixed:** recheck the image-to-point conversions.
