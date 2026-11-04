#!/usr/bin/env node
// Fill a PDF's form fields from a JSON list, after checking every id and value.
//
//   node fill_fields.mjs form.pdf values.json filled.pdf [--flatten]
//
// values.json is a list of {"field_id": ..., "value": ...} (other keys such as
// "description" and "page" are allowed and ignored). Values by field type:
//   text        a string (numbers are converted)
//   checkbox    true/false, or the field's checked_value / "/Off"
//   radio_group one of its radio_options values
//   choice      one of its choice_options values
// Nothing is written if any entry is invalid; every problem is listed.
// --flatten bakes the values into the page so they can no longer be edited.
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
const { PDFDocument, PDFTextField, PDFCheckBox, PDFRadioGroup, PDFDropdown, PDFOptionList } = lib;

const args = process.argv.slice(2);
const flatten = args.includes("--flatten");
const [input, valuesPath, output] = args.filter((a) => a !== "--flatten");
if (!input || !valuesPath || !output) {
  console.log("usage: node fill_fields.mjs form.pdf values.json filled.pdf [--flatten]");
  process.exit(2);
}

const pdf = await PDFDocument.load(readFileSync(input), { ignoreEncryption: true });
const form = pdf.getForm();
const byName = new Map(form.getFields().map((f) => [f.getName(), f]));
let values;
try {
  values = JSON.parse(readFileSync(valuesPath, "utf8"));
} catch (error) {
  console.error(`cannot read ${valuesPath}: ${error.message}`);
  process.exit(2);
}
if (!Array.isArray(values)) {
  console.error("values.json must be a list of {field_id, value} objects");
  process.exit(2);
}

const problems = [];
const actions = [];
for (const [index, item] of values.entries()) {
  const where = `entry ${index + 1} (${item?.field_id ?? "no field_id"})`;
  const field = byName.get(item?.field_id);
  if (!field) {
    problems.push(`${where}: no field with that id; run form_fields.mjs for the exact ids`);
    continue;
  }
  if (field.isReadOnly()) problems.push(`${where}: the field is read-only`);
  const value = item.value;
  if (field instanceof PDFTextField) {
    const text = value === null || value === undefined ? "" : String(value);
    const max = field.getMaxLength();
    if (max !== undefined && text.length > max) {
      problems.push(`${where}: ${text.length} characters, but the field allows ${max}`);
    } else {
      actions.push(() => field.setText(text));
    }
  } else if (field instanceof PDFCheckBox) {
    const on = field.acroField.getWidgets()[0]?.getOnValue()?.toString() ?? "/Yes";
    const truthy = [true, "true", "yes", "on", on, on.replace(/^\//, "")];
    const falsy = [false, "false", "no", "off", "/Off", "Off", "", null];
    if (truthy.includes(value)) actions.push(() => field.check());
    else if (falsy.includes(value)) actions.push(() => field.uncheck());
    else problems.push(`${where}: checkbox value must be true/false, "${on}" or "/Off", not ${JSON.stringify(value)}`);
  } else if (field instanceof PDFRadioGroup) {
    const options = field.getOptions();
    if (options.includes(value)) actions.push(() => field.select(value));
    else problems.push(`${where}: choose one of ${JSON.stringify(options)}, not ${JSON.stringify(value)}`);
  } else if (field instanceof PDFDropdown || field instanceof PDFOptionList) {
    const options = field.getOptions();
    const editable = field instanceof PDFDropdown && field.isEditable();
    if (options.includes(value) || (editable && typeof value === "string")) actions.push(() => field.select(value));
    else problems.push(`${where}: choose one of ${JSON.stringify(options)}, not ${JSON.stringify(value)}`);
  } else {
    problems.push(`${where}: ${field.constructor.name} fields cannot be filled with a value`);
  }
}

if (problems.length) {
  console.error(`not filled — fix these in ${valuesPath}:\n  ` + problems.join("\n  "));
  process.exit(1);
}
for (const act of actions) act();
if (flatten) form.flatten();
writeFileSync(output, await pdf.save({ updateFieldAppearances: true }));
console.log(`filled ${actions.length} fields → ${output}${flatten ? " (flattened)" : ""}`);
