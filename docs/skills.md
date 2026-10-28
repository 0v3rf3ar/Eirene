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

`/skills` opens an inline menu, like `/connect`. Select a skill to toggle it;
the menu shows its description and approximate token size. Folders are listed
first with how many of their skills are enabled. Open a folder to enable or
disable all of its skills at once, or toggle them one by one; Esc returns to the
folder list.

Installing a plugin copies its skills into a folder named after the plugin,
such as `skills/superpowers/`. A disabled bundle's skills are unavailable even
when the individual skill's preference is enabled.

Eirene-managed tool-capable models receive a compact catalog and load relevant
skills as needed. Native CLI and text-only connections can receive guidance
inline, subject to instruction budgets. Enable only the skills relevant to your
work, particularly with a small local model.

## Add your own guidance

Place a Markdown file in `~/.local/share/eirene/skills`, or the corresponding directory
under `EIRENE_HOME`. Both flat `.md` files and a directory containing `SKILL.md`
are discovered. A subfolder without its own `SKILL.md` is a folder of skills that
`/skills` can enable or disable together.

Eirene ships without bundled example skills. Add your own files when needed or
install a plugin that provides skills.

```text
skills/
|-- concise-reviews.md
|-- release-check/
|   `-- SKILL.md
|-- writing/                 a folder of skills
|   |-- tone.md
|   `-- headlines/
|       `-- SKILL.md
`-- superpowers/             copied when the plugin was installed
    `-- systematic-debugging/
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
Each plugin skill's folder, with its supporting files, is copied into
`skills/<plugin>/`; that copy is what `load_skill` and `/plugin:skill` read.
The bundle keeps its own files for hooks and other resources. Plugins installed
before skill folders existed are moved over on the next launch. Script execution
and dependencies still need the normal environment and approvals.

See [plugins](plugins.md) for installation, [Anthropic Skills](plugins/anthropic-skills.md)
for document workflows, and [Superpowers](plugins/superpowers.md) for engineering
workflows. Put project-specific rules in [project instructions](project-instructions.md).

## Discovery identifiers and parsing limits

Local discovery checks `skills/*.md` and `skills/*/SKILL.md`, then, in each
folder without its own `SKILL.md`, `skills/FOLDER/*.md` and
`skills/FOLDER/*/SKILL.md`; it does not recurse deeper. Flat-file IDs use the
filename stem, and directory skill IDs use the parent directory name. Skills in
a folder add `FOLDER:`, so plugin skill IDs are `plugin:skill`. These IDs are the keys of the `skills` activation map in
[config.json](config-file.md#skill-and-plugin-maps); the display title can differ.

The front-matter parser reads simple `key: value` pairs and folded/indented
continuation text. It does not implement a general YAML schema. `name` determines
the title and `description` the summary; absent values fall back to the first
heading and first usable body line. Approximate size is file bytes divided by
four, not a tokenizer measurement.

A loaded body is bounded to 60000 characters. Inline guidance has a 24000-character
body budget and lists deferred skills with their paths. Tool-capable managed
models instead receive a catalog and can request `load_skill`. Discovery does
not install dependencies or execute support scripts. First launch leaves the
user skills directory empty until you add guidance.
