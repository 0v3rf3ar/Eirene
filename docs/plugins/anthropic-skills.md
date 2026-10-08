# Anthropic Skills

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / Anthropic Skills

Anthropic Skills is a broad collection for documents, visual artifacts, writing,
frontend work, and reusable agent guidance. Install it when you need several of
these workflows; use a standalone bundle when you only need one overlapping skill.

## Install and choose a skill

```text
/plugins install anthropic-skills
/plugins inspect anthropic-skills
/skills
```

The installed upstream bundle is named `skills`. `/skills` remains Eirene's
built-in enable/disable picker. Invoke a skill as `/skills:NAME`; the
`/anthropic-skills` entry helps select a workflow when installed through that
catalog shortcut.

## Available workflows

The following 19 skills describe the upstream snapshot used for these guides.
Each suffix belongs after `/skills:`. Inspect your installation for changes.

| Skill | Purpose |
| --- | --- |
| `docx` | Create, edit, and inspect Word documents. |
| `pdf` | Read, create, and transform PDFs using suitable document tools. |
| `pptx` | Prepare, edit, and render slide decks. |
| `xlsx` | Work with spreadsheets, formulas, and structured tabular files. |
| `doc-coauthoring` | Collaboratively draft and refine a structured document. |
| `internal-comms` | Draft common internal communication formats. |
| `frontend-design` | Plan and build a frontend with a clear visual direction. |
| `web-artifacts-builder` | Build richer web artifacts with frontend tooling. |
| `webapp-testing` | Test local web application behavior with browser tooling. |
| `algorithmic-art` | Create generative visual work. |
| `canvas-design` | Create static visual designs and compositions. |
| `brand-guidelines` | Apply the bundle's supplied brand guidance where appropriate. |
| `theme-factory` | Apply or create themes for artifacts. |
| `slack-gif-creator` | Produce animated GIFs suited to Slack usage. |
| `skill-creator` | Create and improve reusable skills. |
| `mcp-builder` | Guide development of MCP integrations. |
| `claude-api` | Guide work targeting Claude APIs and SDKs. |
| `academy-guide` | Find relevant Claude Academy learning resources. |
| `discernment-nudge` | Add task-relevant questions for checking assumptions in substantive advice. |

## Example: document work

```text
/skills:docx Create a project handoff document from notes/handoff.md. Save it to output/handoff.docx and verify its rendered layout.
/skills:pdf Extract the tables from reports/quarterly.pdf into a readable summary.
```

Identify the input, desired output path, format, and what to verify. A file being
created does not prove its layout, formulas, or export behavior are correct; ask
for rendering or validation when that is part of the deliverable.

## Dependencies and supporting files

The bundle retains scripts, templates, references, and licenses. Different skills
need different Python or Node.js packages, fonts, renderers, office utilities, or
browser components. Eirene does not install them merely by importing the bundle.
Read the chosen skill's requirements and approve any necessary setup through the
normal policy. `/plugins doctor anthropic-skills` reports the general caveat, not
a full dependency check for every document format.

Image inspection needs a vision-capable model. Browser tests need their browser
runtime. A text-only connection can discuss a document workflow but cannot create
or inspect its files through tools.

## Scope and overlap

`claude-api`, `academy-guide`, and the supplied brand guidance target their named
products or assets even when the host model is another provider. Provider-neutral
loading does not turn that content into instructions for every API or brand.

The standalone [Frontend Design](frontend-design.md) bundle overlaps with
`/skills:frontend-design`. If both are installed, use the namespaced form. Disable
unneeded skills in `/skills` to keep guidance focused.

Source: [anthropics/skills](https://github.com/anthropics/skills).

## Installed identity and per-skill loading

The catalog shortcut `anthropic-skills` can differ from the imported manifest
name `skills`. Configuration keys use the installed identity: `plugins.skills`
and individual IDs such as `skills:docx`. The inspector accepts the catalog
shortcut for lookup; the built-in `/skills` command still takes precedence over
a plugin alias with the same name.

Support files are retained under `plugins/skills/`. On managed tool-capable
providers the model loads the selected skill, then can read relevant resources
with `load_plugin_resource`; importing does not execute its Python/Node scripts.
Relative resource paths stay inside the installed bundle. For parsing/loading
budgets see [skills](../skills.md#discovery-identifiers-and-parsing-limits), and
for stored preferences see [config.json](../config-file.md#skill-and-plugin-maps).
