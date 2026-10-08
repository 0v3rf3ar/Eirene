# Project instructions

[Documentation](README.md) / Project instructions

Project instructions give Eirene stable guidance it should use across requests:
what the project does, where changes belong, which conventions matter, and how
to verify work. Keep task-specific requirements in your prompt and recurring
requirements in a project instruction file.

## Add an instruction file

Create `EIRENE.md` at the workspace root. Eirene also recognizes root
`AGENTS.md`, `.eirene.md`, `CLAUDE.md`, and `.github/copilot-instructions.md`.
Existing agent instructions can be reused; you do not need duplicate files with
the same content.

```markdown
# Project guidance

This service handles invoice imports. Keep validation in the import layer.

## Working conventions

Use the existing error types. Do not add a new dependency without explaining why.
Keep public API behavior compatible unless the task explicitly changes it.

## Verification

Run the relevant unit tests after changing validation.
For API changes, also run the integration suite against the local test database.
```

List actual verification commands for your project when possible. Eirene detects
common project manifests and can suggest checks, but your own instructions are
more precise than a guess based on a framework.

## Scope guidance to a directory

Nested `AGENTS.md`, `EIRENE.md`, and `CLAUDE.md` files are read as guidance for the
files beneath their directory. Use them for a frontend, service, or package with
different conventions. Eirene checks relevant scoped guidance before file edits.

```text
project/
|-- EIRENE.md            project-wide conventions
|-- frontend/
|   `-- AGENTS.md        frontend conventions
`-- services/
    `-- EIRENE.md        service conventions
```

Keep outer and inner rules compatible and state exceptions clearly. Very long
instruction files consume context and can be truncated; write concise guidance
and point to supporting documents for detailed procedures.

## Give a usable task

A useful prompt identifies the result, its scope, and how to assess it:

```text
Fix duplicate invoice imports in services/imports. Preserve the current API response shape. Add a regression check and run the import tests.
```

For an unfamiliar project, begin in Plan mode and ask Eirene to explain its
structure and verification commands. For a reusable workflow across many projects,
use a [skill](skills.md) instead of copying the same project instructions around.
