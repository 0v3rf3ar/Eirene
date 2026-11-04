# Project instructions

[Documentation](../README.md) / Guides / Project instructions

Project instructions are files in your repository that Eirene reads on every request. Use
them for what stays true across tasks: what the project does, where code belongs, which
conventions matter, and how to verify a change. Put one-off requirements in your prompt.

## Add an instruction file

Create `EIRENE.md` at the root of the workspace:

```markdown
# Project guidance

This service handles invoice imports. Keep validation in the import layer.

## Conventions

Use the existing error types. Explain why before adding a dependency.
Keep public API behavior compatible unless the task changes it.

## Verification

After changing validation, run: pytest tests/imports
For API changes, also run: make integration
```

List your real test commands. Eirene detects common project files and can suggest checks on
its own, but your instructions are more precise than a guess from a framework.

## Which files are read

Eirene reads these files from the workspace root, in this order, and combines all that exist:

1. `AGENTS.md`
2. `EIRENE.md`
3. `.eirene.md`
4. `CLAUDE.md`
5. `.github/copilot-instructions.md`

Instructions you already keep for other tools therefore work as they are. Later files do not
override earlier ones, so resolve any conflicts in the text itself. The combined limit is
16,000 characters, and anything past it is cut off.

## Rules for part of a project

`AGENTS.md`, `EIRENE.md` and `CLAUDE.md` in a subdirectory apply to the files beneath it. Use
them for a frontend, service or package with its own conventions. Eirene checks them before
editing a file there, working from the outermost directory inward. Each nested file can use up
to 16,000 characters.

```text
project/
├── EIRENE.md          project-wide conventions
├── frontend/
│   └── AGENTS.md      frontend conventions
└── services/
    └── EIRENE.md      service conventions
```

Keep outer and inner rules compatible, and state any exception plainly. Long instruction files
use up context on every request, so keep them short and point to other documents for detailed
procedures.

Instructions guide the model only. They do not change file permissions or grant access.

## Write a useful request

A good prompt names the result, the scope, and how to check it:

```text
Fix duplicate invoice imports in services/imports. Preserve the current API response shape. Add a regression test and run the import tests.
```

In an unfamiliar project, start in [Plan mode](modes-and-permissions.md#modes) and ask Eirene to
explain the structure and test commands.

For guidance you want across many projects, write a [skill](../extending/skills.md) instead of
copying the same text around.
