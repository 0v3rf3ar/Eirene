# Code navigation

Use `glob` and `search_text` to discover relevant files, `read_file` for focused
source ranges, and `find_symbol` and `find_references` to locate definitions and
callers. These tools use text matching; inspect the surrounding code to confirm
symbol identity.

`language_diagnostics` runs an installed parser or compiler for fast syntax
checks on a source file. Run the project's tests and type checker to verify
behavior after edits. Subscription providers retain their own tools.
