#!/usr/bin/env node
// List a PDF's fillable form fields as JSON.
//
//   node form_fields.mjs form.pdf [fields.json]
//
// Prints (or writes) a list of fields:
//   {field_id, page, rect: [left, bottom, right, top], type, value, ...}
// type is "text", "checkbox", "radio_group", "choice", "button" or "signature".
// Checkboxes add checked_value/unchecked_value; radio groups add radio_options
// [{value, rect, page}]; choices add choice_options [{value, text}]. Coordinates
// are PDF points with y = 0 at the bottom of the page. Pages are 1-based.
// Exits 2 when the PDF has no fillable fields. Needs pdf-lib (npm install pdf-lib).
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

// Look for pdf-lib in the current folder first, then next to this script (and NODE_PATH).
let lib;
for (const base of [`${process.cwd()}/`, import.meta.url]) {
  try {
    lib = createRequire(base)("pdf-lib");
    break;
  } catch {}
}
if (!lib) {
  console.error("pdf-lib is required: run `npm install pdf-lib` in this folder");
  process.exit(1);
}
const { PDFDocument, PDFTextField, PDFCheckBox, PDFRadioGroup, PDFDropdown, PDFOptionList,
        PDFButton, PDFSignature, PDFName } = lib;

const [input, output] = process.argv.slice(2);
if (!input || input === "-h" || input === "--help") {
  console.log("usage: node form_fields.mjs form.pdf [fields.json]");
  process.exit(input ? 0 : 2);
}

const pdf = await PDFDocument.load(readFileSync(input), { ignoreEncryption: true });
const pages = pdf.getPages();

function pageOf(widget) {
  const ref = widget.P();
  if (ref) {
    const index = pages.findIndex((page) => page.ref === ref);
    if (index >= 0) return index + 1;
  }
  const widgetRef = pdf.context.getObjectRef(widget.dict);
  for (let index = 0; index < pages.length; index++) {
    const annots = pages[index].node.Annots();
    if (!annots || !widgetRef) continue;
    for (let i = 0; i < annots.size(); i++) {
      if (annots.get(i) === widgetRef) return index + 1;
    }
  }
  return null;
}

function rectOf(widget) {
  const { x, y, width, height } = widget.getRectangle();
  const round = (v) => Math.round(v * 100) / 100;
  return [round(x), round(y), round(x + width), round(y + height)];
}

const fields = [];
for (const field of pdf.getForm().getFields()) {
  const widgets = field.acroField.getWidgets();
  const first = widgets[0];
  const entry = { field_id: field.getName(), page: first ? pageOf(first) : null,
                  rect: first ? rectOf(first) : null };
  if (field.isReadOnly()) entry.read_only = true;
  if (field instanceof PDFTextField) {
    entry.type = "text";
    entry.value = field.getText() ?? "";
    const max = field.getMaxLength();
    if (max !== undefined) entry.max_length = max;
    if (field.isMultiline()) entry.multiline = true;
  } else if (field instanceof PDFCheckBox) {
    entry.type = "checkbox";
    const on = first?.getOnValue();
    entry.checked_value = on ? on.toString() : "/Yes";
    entry.unchecked_value = "/Off";
    entry.value = field.isChecked() ? entry.checked_value : "/Off";
  } else if (field instanceof PDFRadioGroup) {
    entry.type = "radio_group";
    entry.value = field.getSelected() ?? null;
    entry.radio_options = widgets.map((widget, i) => ({
      value: field.getOptions()[i] ?? widget.getOnValue()?.decodeText?.() ?? String(widget.getOnValue()),
      rect: rectOf(widget), page: pageOf(widget),
    }));
  } else if (field instanceof PDFDropdown || field instanceof PDFOptionList) {
    entry.type = "choice";
    entry.value = field.getSelected();
    entry.choice_options = field.getOptions().map((value) => ({ value, text: value }));
    if (field instanceof PDFDropdown && field.isEditable()) entry.editable = true;
  } else if (field instanceof PDFButton) {
    entry.type = "button";
  } else if (field instanceof PDFSignature) {
    entry.type = "signature";
  } else {
    entry.type = "unknown";
  }
  fields.push(entry);
}
fields.sort((a, b) => (a.page ?? 0) - (b.page ?? 0) || (b.rect?.[3] ?? 0) - (a.rect?.[3] ?? 0)
                      || (a.rect?.[0] ?? 0) - (b.rect?.[0] ?? 0));

if (fields.length === 0) {
  console.error("This PDF has no fillable form fields. Follow the non-fillable steps in forms.md.");
  process.exit(2);
}
const text = JSON.stringify(fields, null, 2);
if (output) {
  writeFileSync(output, text + "\n");
  console.log(`${fields.length} fillable fields written to ${output}`);
} else {
  console.log(text);
}
