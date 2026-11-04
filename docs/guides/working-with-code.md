# Working with code

[Documentation](../README.md) / Guides / Working with code

You describe what you want in ordinary language, and Eirene chooses the tools. This page
explains what those tools can do and how to get better results from them.

## Find code

```text
Find the code that displays "Login failed" and explain the path from the API response to that message.
```

Exact error text, a filename fragment, a symbol or a directory all narrow the search. Broad
searches normally skip generated and ignored directories, so name a hidden or ignored file
when it matters:

```text
Inspect the hidden configuration file .env.example. Do not read .env.
Search only src/auth for callers of authenticate.
```

Search results are limited in size. If a result says it was cut off, there may be more matches,
so narrow the directory or ask for the next range.

## Follow symbols

```text
Find the definition of InvoiceValidator and its callers. Explain which callers depend on its current return value.
```

Built-in navigation works from source text and needs no index. It can be confused by
same-named symbols, generated code and dynamic calls. When you need language-aware references
and symbol edits, add the [Serena plugin](../extending/plugins/serena.md).

## Edit files

Eirene can create files, replace exact text, and apply patches across several files. Edits go
straight to your working tree and follow the [approval rules of your mode](modes-and-permissions.md#modes).

Name the behavior to preserve:

```text
Update the validation message in src/auth/login.ts. Preserve the existing error code and localization keys.
```

Nothing is rolled back automatically. Stopping a response, switching sessions or running
`/clear` all leave the edits in place, so review them in Git or with [`/diff`](terminal-interface.md#follow-what-eirene-is-doing).

## Check the result

Eirene can check a file's syntax with the tools you have installed:

| File type | Check |
| --- | --- |
| JSON | Parsed by Eirene. |
| Python | Compiled for syntax, without running it. |
| JavaScript | `node --check` |
| TypeScript, TSX | `tsc --noEmit`, using a root `tsconfig.json` when present. |
| C, C++ | `clang` or `gcc` with `-fsyntax-only`. |
| Go module | `go test -run ^$ ./...`, which compiles without running tests. |
| Rust (Cargo) | Offline `cargo check`, with a temporary target directory. |

If the tool is missing, Eirene reports the check as unsupported, which is not the same as passing.

These checks are fast but shallow. For real verification, ask for your project's own commands
and for a report of anything that could not run:

```text
Check this change with the project's type checker and auth tests. Report the commands you ran and any checks you could not run.
```

To have this happen on every task, put the commands in your
[project instructions](project-instructions.md). For a read-only second pass, use
[`/review`](code-review.md).
