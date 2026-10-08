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
