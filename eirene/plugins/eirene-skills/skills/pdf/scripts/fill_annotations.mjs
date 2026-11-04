#!/usr/bin/env node
// Write text onto a PDF that has no fillable fields, at the boxes in fields.json.
//
//   node fill_annotations.mjs form.pdf fields.json filled.pdf
//
// fields.json:
//   {"pages": [{"page_number": 1, "pdf_width": 612, "pdf_height": 792}],
//    "form_fields": [{"page_number": 1, "entry_bounding_box": [x0, top, x1, bottom],
//                     "entry_text": {"text": "Smith", "font_size": 10}}, ...]}
// Boxes use a top-left origin (y grows downwards). Give each page either
// pdf_width/pdf_height (PDF points, as from form_structure.py) or
// image_width/image_height (pixels in the page image you measured on); the
// script scales image coordinates to the page. Text is drawn in Helvetica, left
// aligned and vertically centred in the box, shrunk if it would not fit; a
// single character such as "X" is centred (for checkboxes).
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
const { PDFDocument, StandardFonts, rgb } = lib;

const [input, spec, output] = process.argv.slice(2);
if (!input || !spec || !output) {
  console.log("usage: node fill_annotations.mjs form.pdf fields.json filled.pdf");
  process.exit(2);
}
const pdf = await PDFDocument.load(readFileSync(input), { ignoreEncryption: true });
const font = await pdf.embedFont(StandardFonts.Helvetica);
const data = JSON.parse(readFileSync(spec, "utf8"));
const pageInfo = new Map((data.pages ?? []).map((p) => [p.page_number, p]));
const pages = pdf.getPages();
const problems = [];
let written = 0;

for (const [index, field] of (data.form_fields ?? []).entries()) {
  const label = field.description || field.field_label || `field ${index + 1}`;
  const text = field.entry_text?.text;
  if (text === undefined || text === null || text === "") continue;
  const page = pages[(field.page_number ?? 0) - 1];
  const info = pageInfo.get(field.page_number);
  if (!page || !info) {
    problems.push(`${label}: page ${field.page_number} is not in the PDF or not described in "pages"`);
    continue;
  }
  if (page.getRotation().angle % 360 !== 0) {
    problems.push(`${label}: page ${field.page_number} is rotated; rotate it upright first (see SKILL.md)`);
    continue;
  }
  const box = page.getCropBox();
  let sx = 1, sy = 1;
  if (info.image_width && info.image_height) {
    sx = box.width / info.image_width;
    sy = box.height / info.image_height;
  } else if (info.pdf_width && info.pdf_height) {
    sx = box.width / info.pdf_width;
    sy = box.height / info.pdf_height;
  } else {
    problems.push(`page ${field.page_number}: give pdf_width/pdf_height or image_width/image_height`);
    continue;
  }
  const [x0, top, x1, bottom] = field.entry_bounding_box ?? [];
  if ([x0, top, x1, bottom].some((v) => typeof v !== "number") || x1 <= x0 || bottom <= top) {
    problems.push(`${label}: entry_bounding_box must be [x0, top, x1, bottom] with x1 > x0 and bottom > top`);
    continue;
  }
  const left = box.x + x0 * sx, right = box.x + x1 * sx;
  const lower = box.y + box.height - bottom * sy, upper = box.y + box.height - top * sy;
  const width = right - left, height = upper - lower;
  let size = Math.min(field.entry_text?.font_size ?? 10, height * 0.9);
  const value = String(text);
  while (size > 4 && font.widthOfTextAtSize(value, size) > width - 2) size -= 0.5;
  const textWidth = font.widthOfTextAtSize(value, size);
  if (textWidth > width) problems.push(`${label}: "${value}" does not fit even at 4 pt; widen the box`);
  const x = value.length === 1 ? left + (width - textWidth) / 2 : left + 1;
  const y = lower + (height - size * 0.72) / 2;
  const color = field.entry_text?.font_color ? hex(field.entry_text.font_color) : rgb(0, 0, 0);
  page.drawText(value, { x, y, size, font, color });
  written++;
}

function hex(value) {
  const v = String(value).replace("#", "");
  return rgb(parseInt(v.slice(0, 2), 16) / 255, parseInt(v.slice(2, 4), 16) / 255, parseInt(v.slice(4, 6), 16) / 255);
}

writeFileSync(output, await pdf.save());
console.log(`wrote ${written} entries → ${output}`);
if (problems.length) {
  console.error("check these:\n  " + problems.join("\n  "));
  process.exit(1);
}
