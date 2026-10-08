# Files and code navigation

[Documentation](README.md) / Files and code navigation

Describe what you need to find or change in normal language. Eirene can discover
files, search text, read relevant ranges, follow definitions and references, and
apply edits in the workspace. You do not need to call its internal tools yourself.

## Find the right files

```text
Find the code that displays "Login failed" and explain the path from the API response to that message.
```

Exact error text, a filename fragment, a symbol, and a directory make a search
more focused. Eirene normally excludes generated and ignored directories from
broad discovery. Ask explicitly when a hidden file, ignored file, or generated
artifact is relevant.

```text
Inspect the hidden configuration file .env.example. Do not read .env.
Search only src/auth for callers of authenticate.
```

Results are bounded. A partial result or match limit does not establish that
there are no other matches. Ask to narrow the directory or inspect a later range
when necessary.

## Follow symbols and references

```text
Find the definition of InvoiceValidator and its callers. Explain which callers depend on its current return value.
```

Built-in symbol navigation uses source text and surrounding context. It is useful
without an index, but same-named symbols, generated code, and dynamic calls can
need extra inspection. [Serena](plugins/serena.md) adds language-server navigation
when you need semantic references and supported symbol editing.

## Inspect and edit

Ask for a bounded change and name the behavior to preserve. Eirene can create a
file, replace exact text, or apply a patch across several files. Changes are
written directly to the workspace and follow the current mode's approval rules.

```text
Update the validation message in src/auth/login.ts. Preserve the existing error code and localization keys.
```

Use Plan mode for explanation without edits. A conversation reset, session switch,
or stop action does not roll back edits. Review your working tree in Git or your
usual editor before accepting the result.

## Check syntax and behavior

Eirene can use installed parsers or compilers for fast file diagnostics. Those
checks require the corresponding language tools to be installed and do not
replace your project's tests, type checker, or integration checks.

```text
Check this change with the project's type checker and auth tests. Report the commands and any checks you could not run.
```

A command still running is not a passed check. See [running commands](processes.md)
for output and background work, [review](review.md) for a read-only second pass,
and [project instructions](project-instructions.md) for recurring verification
rules.
