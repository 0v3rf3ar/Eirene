# Skills

[Documentation](README.md) / Skills

A skill is reusable Markdown guidance for a particular kind of task. It can
explain how to review a UI, prepare a document, follow a project convention, or
verify a change. Skills supply instructions; they do not grant additional tools
or permissions by themselves.

## Enable and disable

```text
/skills
```

Select a skill to toggle it. The picker shows its description and approximate
token size. Installed plugins can contribute skills as well as your own files.
A disabled bundle's skills are unavailable even when the individual skill's
preference is enabled.

Eirene-managed tool-capable models receive a compact catalog and load relevant
skills as needed. Native CLI and text-only connections can receive guidance
inline, subject to instruction budgets. Enable only the skills relevant to your
work, particularly with a small local model.

## Add your own guidance

Place a Markdown file in `~/.local/eirene/skills`, or the corresponding directory
under `EIRENE_HOME`. Both flat `.md` files and a directory containing `SKILL.md`
are discovered.

```text
skills/
|-- concise-reviews.md
`-- release-check/
    `-- SKILL.md
```

A simple file can use a heading and instructions:

```markdown
---
name: Concise review
description: Review changes for concrete defects and report evidence.
---

# Concise review

Start with the changed behavior. Report a finding only when you can explain
its trigger, impact, and a specific fix. Include file and line references.
```

Use `/skills` to reload discovery and confirm the file appears. Ask Eirene
explicitly to use the skill when the task is a match.

## Plugin skill commands

Enabled plugin skills can add `/plugin:skill` commands, plus unambiguous short
aliases. Locally added skill files are available as guidance through `/skills`;
they do not automatically become plugin slash commands.

```text
/superpowers:systematic-debugging Investigate the intermittent import failure.
```

Some upstream skills intentionally declare themselves non-user-invocable. Those
are available as guidance where appropriate but do not appear as slash commands.
Imported supporting rules and templates remain with the bundle. Script execution
and dependencies still need the normal environment and approvals.

See [plugins](plugins.md) for installation, [Anthropic Skills](plugins/anthropic-skills.md)
for document workflows, and [Superpowers](plugins/superpowers.md) for engineering
workflows. Put project-specific rules in [project instructions](project-instructions.md).

## Discovery identifiers and parsing limits

Local discovery checks `skills/*.md` and `skills/*/SKILL.md`; it does not recurse
through arbitrarily deep local directories. Flat-file IDs use the filename
stem, and directory skill IDs use the parent directory name. Plugin skill IDs
add `plugin:`. These IDs are the keys of the `skills` activation map in
[config.json](config-file.md#skill-and-plugin-maps); the display title can differ.

The front-matter parser reads simple `key: value` pairs and folded/indented
continuation text. It does not implement a general YAML schema. `name` determines
the title and `description` the summary; absent values fall back to the first
heading and first usable body line. Approximate size is file bytes divided by
four, not a tokenizer measurement.

A loaded body is bounded to 60000 characters. Inline guidance has a 24000-character
body budget and lists deferred skills with their paths. Tool-capable managed
models instead receive a catalog and can request `load_skill`. Discovery does
not install dependencies or execute support scripts. First launch does not copy
the example files from the source `skills/` directory into your data directory.
