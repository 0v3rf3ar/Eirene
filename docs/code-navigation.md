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

## Text edits and diagnostic engines

Exact-text editing fails when the old text is absent or occurs more than once
without an explicit replace-all request. Include enough surrounding text to make
a replacement unique. Identical old/new strings are rejected. File writes and
replacements operate on the actual resolved workspace path.

Built-in language diagnostics choose installed engines by file type:

| Input | Diagnostic operation |
| --- | --- |
| JSON | Parse JSON in the application. |
| Python | Compile source syntax without executing the module. |
| JavaScript | `node --check`. |
| TypeScript/TSX | `tsc --noEmit`; a root `tsconfig.json` uses the project configuration. |
| C/C++ | Installed clang or gcc with `-fsyntax-only`. |
| Go module | `go test -run ^$ ./...` to compile without running ordinary tests. |
| Rust Cargo project | Offline `cargo check`, with a temporary target directory. |

These operations have compiler-specific side effects and dependency needs. A
missing engine reports unsupported diagnostics; it is not a clean result.
Search/reference discovery uses bounded text and fixed native templates, not a
persistent language-server index. [Serena](plugins/serena.md) supplies that separate
integration. Settings affecting command limits are in [config.json](config-file.md#numeric-limits).
