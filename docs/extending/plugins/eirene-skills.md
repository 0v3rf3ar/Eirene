# Eirene Skills

[Documentation](../../README.md) / [Plugin catalog](../plugin-catalog.md) / Eirene Skills

This bundle of skills ships with Eirene and covers documents, design, frontend work, web testing, internal writing, MCP servers and writing skills. Installing it needs no network or Git.

## Install

```text
/plugins install eirene-skills
/plugins trust eirene-skills
/skills
```

Each skill becomes a command named after it, such as `/docx`. If something else already uses the name, the menu shows `/eirene-skills:docx` instead. Open the `eirene-skills` folder in `/skills` to enable only the ones you use.

## The skills

| Skill | Purpose |
| --- | --- |
| `docx` | Create, edit and review Word documents, including tracked changes and comments. |
| `pdf` | Read, merge, split, create, fill forms in, and OCR PDF files. |
| `pptx` | Create, edit and design PowerPoint decks, and work from templates. |
| `xlsx` | Build and edit spreadsheets with formulas, recalculation and financial-model conventions. |
| `doc-coauthoring` | Write a substantial document together, section by section, then test it on a fresh reader. |
| `internal-comms` | Status reports, 3P updates, newsletters, FAQs and incident reports. |
| `frontend-design` | Give an interface a deliberate visual direction instead of templated defaults. |
| `web-artifacts-builder` | Build a React, Tailwind and shadcn/ui app bundled into one HTML file. |
| `webapp-testing` | Drive a local web app with Playwright: check behavior, screenshots and console output. |
| `algorithmic-art` | Generative p5.js art with seeded randomness and a live parameter viewer. |
| `canvas-design` | Original posters and static art as PNG or PDF, from a written design philosophy. |
| `theme-factory` | Apply one of ten color-and-font themes, or a new one, to any artifact. |
| `slack-gif-creator` | Animated GIFs and emoji sized and tuned for Slack. |
| `mcp-builder` | Design, build, test and evaluate MCP servers in TypeScript or Python. |
| `skill-creator` | Write skills, test them against a baseline, review results and tune descriptions. |
| `discernment-nudge` | End consequential answers with two or three questions that help check them. |

## Example: documents

```text
/docx Turn notes/handoff.md into output/handoff.docx with a table of contents, then check the rendered pages.
/pdf Fill in forms/application.pdf with the details in notes/applicant.md.
/xlsx Add a profit-margin column to reports/q4.xlsx and recalculate.
```

Say where the input is, where the output should go, its format, and what to check. The skills render and validate their output, and tell you when they cannot.

## Requirements

Skills use ordinary tools and ask before installing anything. Each `SKILL.md` has a "Requirements" line. In general:

| Need | Used by |
| --- | --- |
| Python 3 | Almost every script. Most use only the standard library. |
| Node.js | `docx`, `pptx`, PDF forms, `web-artifacts-builder`, `mcp-builder` |
| LibreOffice | Rendering and converting Office files, and recalculating spreadsheets |
| Poppler (`pdftoppm`, `pdftotext`) | Page images and PDF text |
| Pillow | Thumbnails, GIFs and canvas art |
| Playwright | `webapp-testing` |

`/plugins doctor eirene-skills` reports whether Python, Node.js, LibreOffice and `pdftoppm` are on `PATH`. It does not check per-skill packages.

Visual checks need a model that can read images, and creating files needs a provider with tools.

## Testing skills

`skill-creator` and `mcp-builder` run their tests as [headless runs](../../automation/headless.md):

- **Test prompts** run with and without the skill, in parallel and in separate folders, recording time, tokens and tool calls.
- **Description tuning** runs each trigger query in a private data directory with your configuration and the candidate skill, and counts a trigger when the model loads it.
- **MCP evaluations** run each question with only the server under test granted.

They use your active provider unless you pass `--provider` and `--model`. Use an API provider, because Claude Code and Codex cannot honor the restricted tool lists these tests need.

## Updating

`/plugins update eirene-skills` fetches the newest copy from [Eirene's repository](https://github.com/0v3rf3ar/Eirene/tree/master/eirene/plugins/eirene-skills), which needs Git and network access. Configuration keys are `plugins.eirene-skills` and `skills.eirene-skills:NAME`.

## Origin

`frontend-design` is adapted, with thanks, from the Apache-2.0 skill of the same name in [Anthropic's official plugins](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design). See the [NOTICE](../../../NOTICE) file. The bundle follows the folder layout of the Agent Skills format, so other agents that read `SKILL.md` folders can use these skills too.
