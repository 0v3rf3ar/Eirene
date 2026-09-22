# Execution and recovery

Eirene applies approved changes to the real workspace. The command runtime limits
host access; it does not create a disposable copy or undo external side effects.

## Kernel sandbox

Run `/sandbox` to inspect status. Commands automatically use Bubblewrap on Linux;
there are no Docker, Podman, image, or backend-selection options. Bubblewrap
(`bwrap`) must be installed and the system must permit user namespaces. Missing
support causes execution to fail closed, never to fall back to unprotected host
execution. Other operating systems currently cannot run native sandboxed commands.

The sandbox uses your installed system tools, mounts system executables and
selected runtime configuration read-only, keeps the project writable, and provides
private temporary storage, process/device views, and HOME. Tools installed outside
system directories need an explicit read mount. Desktop sockets and inherited API
credentials are not exposed. This shares the host kernel, not a virtual machine.

Old backend settings are normalized to automatic Bubblewrap isolation when loaded;
obsolete image settings are discarded. Network access is disabled by default.
An approved network grant enables host networking, not a per-domain firewall.

## External paths and network access

For a command that needs another directory, the agent supplies `read_paths` or
`write_paths`. The approval displays the requested paths and access. Grants last
only for that command (or the lifetime of a managed process). To create an external
file, grant its narrowest existing parent. `/` cannot be granted. Paths retain
their host absolute names inside the sandbox, so tool arguments need no remapping.

File tools and unified patches also support approved external paths, including
`~` paths. Those tools enforce resolved-path checks inside Eirene; they are not
executed inside a container. Do not use them against a hostile process actively
racing symlink changes. Review edits to sensitive configuration even when the
target path was approved.

`network_access: true` requests command networking separately from file access.
Browser, web-search and HTTP tools request approval when network isolation is on;
they run in the application, outside the command container. Approval does not
make arbitrary websites or responses trusted instructions.

MCP servers configured in Eirene run in the selected command environment and do not
start in plan mode. Server definitions may specify explicit `read_paths`,
`write_paths`, and `env` for their installed code and credentials. Treat these user
configuration entries as trusted grants. Server tools still require approval.
Hooks run within the configured command environment. Extension configuration is
not a safe place to put unreviewed third-party commands.

Codex and Claude Code subscription adapters delegate execution to their CLIs.
`/sandbox` identifies this distinction. The Codex auto policy permits requests for
additional access; Eirene forwards them to its approval UI. Claude is launched with
sandboxing enabled, unsandboxed retries disabled, and failure requested when its
sandbox is unavailable. Backend behavior depends on the installed CLI version.
Eirene's Bubblewrap runtime does not wrap those external CLIs.

## Output and interaction

Commands show two output lines in chat by default. Click a command to expand its
saved output inline; click again to collapse it, including after resuming a session.
Expanded output is limited to 200 KB for responsive rendering; larger artifacts
remain available through `read_output`. Native tools stream through a
bounded queue and save output under the private Eirene data directory. Each
artifact is capped at 20 MB with an explicit truncation marker. Transcript and
model context use shorter previews; `read_output` retrieves artifact byte ranges.
External CLI output is limited by what that CLI exposes.

Ordinary messages sent while working are queued for the next execution boundary.
Reasoning activity appears only in the live status line, not as transcript entries.
`/sandbox` opens a structured status popup like `/usage`.
`/prompt-suggest on` enables a muted AI-generated placeholder in the empty input
after completed replies, without adding anything to the chat. Generation starts
in the background while the answer streams, and a prepared suggestion is revealed
as soon as the turn completes. If the suggestion model is slower than the answer,
it appears when ready; the main answer is never held back. Tool activity invalidates
early suggestions so a new one can be prepared for the next answer. Suggestions
use neutral gray, including in the ANSI theme, and truncated fragments are rejected.
The feature is off by default and uses extra model requests. With an empty composer,
Tab or Right Arrow copies the suggestion into an editable draft; Enter sends it.
Typing your own draft dismisses the suggestion. `/prompt-suggest off` disables it;
the command without arguments opens a settings popup with an on/off switch.
Enabling it also requests a suggestion for the latest completed reply. The popup
shows generation status; failures and empty responses are reported there rather than
silently hidden. Turn the switch off and on to retry.
Pending sequential tool calls are skipped when new instructions arrive. Already
running commands and parallel read batches finish unless interrupted. Auto mode
can ask consequential requirement questions. Unattended runs stop when an answer
is required instead of inventing one.

## Recovery and context

Tool lifecycle records distinguish requested, started, succeeded, failed, blocked,
denied, and unknown outcomes. Interrupted calls receive a matching result before
history is reused; unknown writes are never automatically replayed. Iteration and
repetition guards produce an incomplete outcome and a failing headless exit code.
Persistent session write failures are surfaced rather than silently discarded.

Checkpoints preserve tracked and dirty files, symlinks, modes, and the Git index.
Rollback refuses changed HEAD and, for sealed agent checkpoints, later filesystem
edits. Checkpoints have a 100 MB content limit. This does not recover database,
network, ignored-file, external-mount, or other non-repository side effects.
Review checkpoint scope before restoring; concurrent writers during an agent turn
cannot always be distinguished from agent edits. Legacy checkpoints retain their
older format and do not gain staged/index fidelity retroactively.

Context is budgeted before every native model call, including headless runs.
Instructions, tool schemas, and response reserve count against configured model
limits. Counts are estimates; configure `model_context_limits` for your model.
Compaction prioritizes recent corrections and preserves complete recent tool
groups. It stops with a clear error if compaction cannot make the context fit.
Nested AGENTS.md/EIRENE.md/CLAUDE.md files are supplied before file-tool edits;
arbitrary shell scripts must still obey the agent's instruction-loading policy.

## Evaluation

`python -m pytest -q` covers deterministic recovery, permissions, Git, streaming,
steering, parallel reads, output-viewer behavior, and real Linux Bubblewrap mounts.
Kernel tests require user namespaces; an enclosing sandbox may block them.

Run real-model coding evaluations explicitly (these use provider tokens):

```sh
python -m eirene.evaluate --provider PROVIDER --model MODEL
```

The runner creates temporary task workspaces, retains them for inspection, and
prints JSON records with acceptance results, unexpected changes to protected
fixture files, tool errors, intervention requests, tokens, elapsed time, and cost
when pricing is configured. Compare the same cases and model across harness
versions. These small tasks are a starting evaluation set, not a claim of parity
with Codex or Claude Code. Live-provider evaluations are separate from unit tests.
