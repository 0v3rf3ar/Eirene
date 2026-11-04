# Eirene Skills

Skills that ship with Eirene. Install them with:

```text
/plugins install eirene-skills
```

Each skill is a folder under `skills/` with a `SKILL.md` and any scripts,
templates or references it uses. Scripts are plain Python, Node.js or shell
programs; nothing runs at install time. Read a skill's "Requirements" section
before using it, and install only the packages that skill needs.

`frontend-design` is adapted from an Apache-2.0 skill and changed for Eirene; see
Eirene's NOTICE file. The other skills here were written for Eirene. They follow the structure of the public
Agent Skills format so other agents that read `SKILL.md` folders can use them
too.
