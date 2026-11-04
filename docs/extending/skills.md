# Skills

[Documentation](../README.md) / Extending Eirene / Skills

A skill is a Markdown file of guidance for one kind of task, such as reviewing a UI, preparing a document, or following a release checklist. Eirene shows the model a short list of
enabled skills, and the model loads the full text when a task calls for it. Skills supply instructions only, and grant no extra tools or permissions.

No skills are installed by default. You can write your own, or install a bundle such as [Eirene Skills](plugins/eirene-skills.md).

## Turn skills on and off

```text
/skills
```

This opens a menu showing each skill with its description and approximate size in tokens. Select one to toggle it. Folders appear first, with a count of how many of their skills are
enabled. Open a folder to toggle them together or one by one, and press Escape to return.

Every enabled skill uses some context, which matters most on small local models, so keep only the ones you use. A skill from a plugin stays unavailable until you
[trust that plugin](plugins.md#trust-a-plugin), whatever its own setting says.

## Write a skill

Put a Markdown file in the `skills` folder of your [data directory](../reference/data-directory.md), which is `~/.local/share/eirene/skills` by default:

```markdown
---
name: Concise review
description: Review changes for concrete defects and report evidence.
---

# Concise review

Start with the changed behavior. Report a finding only when you can explain
its trigger, impact, and a specific fix. Include file and line references.
```

`description` is what the model sees when deciding whether to load the skill, so make it specific. If `name` or `description` is missing, Eirene uses the first heading and the first line
of the body. Only simple `key: value` front matter and indented continuation lines are understood, not full YAML.

Run `/skills` to reload the list and confirm your skill appears.

### Folder layout

```text
skills/
├── concise-reviews.md          a skill in one file
├── release-check/
│   ├── SKILL.md                a skill with supporting files
│   ├── scripts/
│   └── commands/
│       └── tag.md              adds the command /tag
├── writing/                    no SKILL.md, so this is a folder of skills
│   ├── tone.md
│   ├── headlines/
│   │   └── SKILL.md
│   └── commands/
│       └── draft.md            adds the command /draft
└── superpowers/                copied here when the plugin was installed
    └── systematic-debugging/
        └── SKILL.md
```

Eirene looks only this deep: folders of skills cannot contain further folders of skills.

### Scripts

Skill files live outside the workspace, so scripts must be run by their full path. Write `${SKILL_DIR}/scripts/tool.py` in the skill, and Eirene substitutes the real folder when the skill
loads. `${CLAUDE_SKILL_DIR}` and `${CLAUDE_PLUGIN_ROOT}` also work, for compatibility. Skills are read-only inside the sandbox. Commands in a skill still need the usual approvals, and their
dependencies must be installed.

## Use a skill as a command

Each enabled skill adds a slash command:

```text
/concise-reviews
/superpowers:systematic-debugging Investigate the intermittent import failure.
```

If the short name is taken by another skill or by a built-in command, the menu shows a longer form instead: `/plugin:skill` for a plugin's skill, `/folder:skill` for one in your own folder, or
`/skill:name` for one directly in `skills/`.

Some skills declare themselves as not user-invocable. Those can be loaded by the model but do not appear as commands.

A skill can add further commands from a `commands/` folder beside its `SKILL.md`, and a folder of skills can have one for the whole group. Each Markdown file becomes a command named after the
file, with the same format as a [plugin command](writing-plugins.md#commands). Turning off the skill removes them too.

## Install skills from elsewhere

```text
/skills add obsidian@obsidian-skills
/skills add owner/repository/path/to/skill
/skills add /absolute/path/to/skill-folder
```

`/skills add` accepts the same sources as [`/plugins install`](plugins.md#install-a-plugin), and puts the result in `skills/<name>/`. Like any plugin, it stays off until you run
`/plugins trust NAME`. Remove it with `/plugins uninstall NAME`.

## Size limits

- A loaded skill can be up to 60,000 characters.
- On connections where the model cannot load skills on demand, such as text-only connections and external CLIs, enabled skills are sent inline up to a total of 24,000 characters. The rest are
  listed by path.
- The size shown in `/skills` is the file size divided by four, which is only an estimate.

Skill settings are saved in the [`skills` map](../reference/configuration.md#skills-and-plugins). For rules specific to one project, use [project instructions](../guides/project-instructions.md).
