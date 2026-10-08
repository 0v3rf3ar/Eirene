# Native discovery and command execution

Eirene's `glob`, `list_dir`, `search_text`, `read_file`, `find_symbol`, and
`find_references` use installed command-line utilities. Python validates paths,
supervises processes, and formats results; it does not recursively walk source
trees or search file contents for these tools. Edits remain exact file operations.

## Discovery

Use filename fragments and exact text first, batch independent searches, inspect
bounded candidate ranges, then follow definitions and callers. Widen the search
only when the first scope is insufficient. These are textual results, not a
semantic index; confirm symbol identity from surrounding code.

Examples:

```json
{"pattern":"**/*auth*","query":"auth.py"}
{"pattern":"Login failed","literal":true,"output":"files","path":"src"}
{"pattern":"authenticate","whole_word":true,"context":2,"path":"src"}
{"path":"src/auth.py","offset":20,"limit":60}
```

`search_text` supports `literal`, `case_sensitive`, `whole_word`, additional
`patterns`, `glob`, `exclude`, `context`, and `output` (`content`, `files`, `count`).
Existing calls default to regex matching. Results identify the active engine:
ripgrep, POSIX awk ERE, or PowerShell/.NET. Regex dialects differ; unsupported
expressions fail explicitly. Literal mode avoids regex escaping for ordinary text.

`glob` uses stable path ordering. Its optional `query` ranks exact paths, exact
basenames, components, and substrings ahead of other matches. Both discovery and
search accept `hidden` and `ignored`, defaulting to false. Generated directories
are excluded by default and `.git` is always excluded from recursive discovery.
Explicit file reads can still inspect a requested hidden or ignored file.

Ripgrep is preferred when installed. POSIX fallbacks use find/awk; Windows uses
fixed PowerShell templates with data supplied through stdin. Git supplies ignore
information in fallback repository discovery. Without ripgrep or Git, results
state that ignore-file interpretation is unavailable. Eirene installs no utilities.

Results distinguish no matches, failures, and partial output. Match limits,
long lines, and artifact limits are not proof that no other occurrences exist.
Narrow the path or use `read_file` ranges/byte continuation to inspect more.

## Execution

`run_command` accepts `cwd`, `shell`, `execution`, `timeout`, and `stdin`.
Shell choices are restricted to those supported on the host:

- Linux: Bash without startup files, with a POSIX sh fallback.
- macOS: system Bash/sh and BSD-compatible utilities.
- Windows: PowerShell 7 or Windows PowerShell, then CMD if neither exists.
  Select `shell="cmd"` for CMD/batch syntax. `powershell=true` remains supported.

The OS executes pipelines and success chaining. Bash uses `pipefail`; PowerShell
propagates terminating errors and native exit codes. PowerShell 5.1 has no `&&`:
check `$LASTEXITCODE` before dependent native commands. Use `cwd` rather than
assuming a previous tool call changed directories.

Short commands have a one-second foreground allowance. Unknown commands, builds,
and tests start in the background; `execution="background"` requests this
explicitly. Each process keeps one ID, reader, output artifact, and original
deadline throughout execution. Quiet output is not evidence of a hang.

Default deadlines are 30 seconds for simple reads, 120 seconds for unknown work,
300 seconds for tests/package operations, and 600 seconds for builds. Explicit
`timeout` overrides the default, up to 86,400 seconds. Successful command timings
are retained in a bounded in-memory history during the app run; three samples
allow more informed scheduling. Estimates are not promises of completion time.

Use `start_process` for development servers and watchers. They remain owned by
Eirene until stopped or app exit, unless `auto_stop` supplies a deadline. Do not
detach them with shell `&`, `nohup`, or daemon mode. POSIX process groups and Windows
Job Objects provide cancellation and descendant cleanup. Every startup and cleanup
wait is bounded. OS-level failures are reported rather than treated as success.

The background line appears immediately below the model name only while there
is background work. Select it to view output or stop a command. Ctrl+B opens
controls for background, foreground, and subscription-provider commands.
The line has no idle timer and updates elapsed times once per second while visible.

Continue independent work after a command returns its process ID. If only that
command remains, use `poll_process` with `wait=true`. The wait is asynchronous;
no repeated model polling is needed. Finite background results are delivered to
the owning agent before it finishes the task. A running process is not successful
verification. Subscription CLIs retain their own execution lifecycle.

## Verification and performance

`language_diagnostics` still invokes installed parsers/compilers. Follow it with
the project's actual tests and type checker as appropriate. Root project profiling
reads manifests and instructions; native repository inventory is loaded on demand
by `project_info`, avoiding recursive startup scans.

Run deterministic tests before spending model tokens. The offline benchmark uses
no AI or network calls:

```sh
python scripts/benchmark_commands.py --source . --samples 15
```

Compare median and p95 times against another checkout on the same machine.
`eirene.evaluate` includes ambiguous-file and generated-decoy tasks for opt-in
real-model evaluation; those runs use provider tokens.
