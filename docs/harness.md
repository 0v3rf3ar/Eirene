# Execution and recovery

Eirene applies approved changes to the real workspace. The command runtime limits
host access; it does not create a disposable copy or undo external side effects.

## Kernel sandbox

Run `/sandbox` to inspect status. Native command execution follows the host:

| Host | Execution policy | Requirements |
| --- | --- | --- |
| Linux | Bubblewrap isolation; no unprotected fallback | `bwrap` and working user namespaces |
| macOS | sandbox-exec (Seatbelt) isolation; no unprotected fallback | `sandbox-exec` |
| Windows | Explicit approval for every native command; no kernel isolation | Interactive approval; plan mode blocks native commands |

On Linux, the runtime mounts system executables and selected runtime configuration
read-only, keeps the project writable, and provides private temporary storage,
process/device views, and HOME. Tools installed outside system directories need
an explicit read mount. Desktop sockets and inherited API credentials are not
exposed.

On macOS, a deny-by-default Seatbelt profile permits the project, approved paths,
system runtime directories, and a private scratch directory used for HOME and
TMPDIR. Homebrew's `/opt/homebrew` directory is readable when present. Seatbelt
restricts access to host paths rather than creating Linux-style mount namespaces.
Both backends share the host kernel, not a virtual machine.

Windows commands run with the user's account permissions after approval. Portable
file/search/edit tools retain their application-level path checks. Native commands
cannot enforce read-only plan mode and are blocked there. Headless Windows runs
fail closed when a command needs approval. See [platform support](platforms.md)
for external CLI behavior and WSL2 guidance.

Old backend settings are normalized to automatic platform isolation when loaded;
obsolete image settings are discarded. Network access is disabled by default in
the Linux and macOS backends. An approved network grant permits networking, not
a per-domain firewall. Windows native commands have no network isolation.

## External paths and network access

For a command that needs another directory, the agent supplies `read_paths` or
`write_paths`. The approval displays the requested paths and access. Grants last
only for that command (or the lifetime of a managed process). To create an external
file, grant its narrowest existing parent. `/` cannot be granted. Paths retain
their host absolute names inside the sandbox, so tool arguments need no remapping.

File tools and unified patches also support approved external paths, including
`~` paths. Those tools enforce resolved-path checks inside Eirene; they are not
executed inside the native command sandbox. Do not use them against a hostile process actively
racing symlink changes. Review edits to sensitive configuration even when the
target path was approved.

`network_access: true` requests command networking separately from file access.
Browser, web-search and HTTP tools request approval when network isolation is on;
they run in the application, outside the native command sandbox. Approval does not
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

## Host awareness

At agent startup, Eirene records the operating system, architecture, shell,
CPU thread count, estimated RAM/GPU model memory, and a bounded inventory of
common tools on host PATH. These checks use local APIs and files; they do not
invoke a model or launch probe commands. The snapshot is reused for model turns.
Hardware figures are estimates, and undetected GPU memory is reported as unknown.

Provider and local-model prompts receive only their host's command profile.
Windows uses CMD and, when detected, PowerShell; macOS uses its BSD/POSIX profile;
Linux uses its own profile. Bounded read examples are chosen from installed
utilities. Command schemas omit PowerShell on other systems and omit PTY on
Windows. Small local prompts retain the same concise hardware/tool facts.
Project-installed tools may differ from host PATH; sandbox access still follows
execution policy. Codex and Claude Code retain their own tool harnesses.

## Output and interaction

Commands show two output lines in chat by default. Click a command to expand its
saved output inline; click again to collapse it, including after resuming a session.
Expanded output is limited to 200 KB for responsive rendering; larger artifacts
remain available through `read_output`. Native tools stream through a
bounded queue and save output under the private Eirene data directory. Each
artifact is capped at 20 MB with an explicit truncation marker. Transcript and
model context use shorter previews. Every native tool result, including MCP,
commands, directory listings, web tools, process polling, and artifact reads, uses
the remaining context after instructions, schemas, history, and reply reserve.
Cloud previews are capped at 12,000 characters; local previews have a smaller
profile cap. Parallel reads divide the available allowance across their batch.
Saved-output pages report exact byte ranges and `next_offset`; pass that value
as `offset` to `read_output`, preferably with `limit=1024`. UTF-8 continuation
boundaries are preserved. A partial preview cannot establish absence of errors
or matches. Very small budgets return a short deferral or no body, followed by
normal context compaction before the next model request.
External CLI output is limited by what that CLI exposes.

`read_file` checks file size and counts lines with bounded buffers before choosing
its output. Small files are read fully when they fit; larger reads give numbered
ranges and continuation offsets. `pattern`/`context` selects grep-style evidence,
`tail` retains the ending, and `byte_offset` pages oversized lines without splitting
UTF-8 characters. Local models receive a smaller allowance based on remaining
estimated context, instructions, tool schemas and reply reserve. Shell guidance
uses `wc -lc`, `file`, `head`/`tail`, `sed -n` and bounded `rg` searches, with
PowerShell equivalents in the compact local prompt. `rg -m` is a per-file limit,
so models are instructed to narrow paths and choose names/counts when sufficient.
Directory and glob tools retain at most 500 entries while counting omitted
entries. Text search bounds physical-line allocations and identifies clipped
lines. HTTP bodies are streamed with a 2 MB decoded download cap and an elapsed
time deadline; Chromium stdout and stderr are drained into bounded buffers.
Binary files are rejected by text reads; use image tools or bounded `od`/`xxd`.
Terminal displays and headless output strip control and escape sequences while
preserving printable Unicode. Local web search cards show status and errors while
keeping successful result bodies hidden.

`/search-api` configures an optional Tavily fallback through a masked key prompt.
Keys use the configured file or OS credential store and do not change the model
provider. Setup checks Tavily's `/usage` endpoint without spending a search credit.
Search always tries DuckDuckGo first; without a saved key no Tavily request is
made. A fallback makes one basic search request (one credit), with automatic depth
upgrades and generated answers disabled. Relevance-ranked page content is reused
when available; otherwise at most four candidate URLs are fetched within a
20-second page budget, stopping after two readable sources. URLs and compact
query-related passages reach the model in the original search result, with no
extra tool cards or provider-switch announcements.

Successful searches and page text are cached in memory for ten minutes, with at
most 64 entries each; duplicate concurrent searches share one operation. Page and
search failures have short negative caches. Authentication failures pause API
requests until the key changes; credit/spending limits pause them for an hour,
and rate limits respect a bounded `Retry-After`. Normal search remains available
during API cooldowns. Reopening `/search-api` and replacing the key clears the
agent's cached results and cooldown. Search POSTs are not automatically retried,
because a lost response may already have consumed a credit. API error bodies and
credentials are never returned to the model. Sources are evidence, not trusted
instructions. See Tavily's [Search reference](https://docs.tavily.com/documentation/api-reference/endpoint/search),
[Usage reference](https://docs.tavily.com/documentation/api-reference/endpoint/usage),
and [credit costs](https://docs.tavily.com/documentation/api-credits).

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
the command without arguments opens a compact popup with an immediate
`<  ON  >` / `<  OFF  >` control. Click it or focus it and press Enter or Space.
Enabling it also requests a suggestion for the latest completed reply. The popup
shows generation status; failures and empty responses are reported there rather than
silently hidden. Turn suggestions off and on to retry. Ctrl + P toggles them directly.
`/keybindings` or Ctrl + K opens the shortcut reference; F1 shows commands and
tips, F2 picks a model, and F3 switches sessions. Shortcuts preserve input drafts
and leave active pickers and text requests undisturbed.
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

Context is budgeted before every native model call, including headless runs.
Instructions, tool schemas, and response reserve count against configured model
limits. Counts are estimates; configure `model_context_limits` for your model.
Compaction prioritizes recent corrections and preserves complete recent tool
groups. Ollama local budgets also include the advertised model context limit.
Routine compaction and connection retries use the live status line, without warning
cards. A request that cannot fit still receives an actionable explanation.

Compaction carries a bounded execution record derived from tool results alongside
the model's summary. Earlier evidence is saved as an output artifact, and the
latest user request remains verbatim. An empty or timed-out automatic summary
falls back to quoted instructions and observed results. Duplicate unchanged calls
within a turn reuse previous results; mutations invalidate cached observations.
Active processes and hooks bypass caching. Malformed and truncated tool requests
are returned to the model for correction without executing them.

Foreground commands get workload-based deadlines (30 seconds for simple reads,
120 by default, 300 for tests/package work, 600 for builds), capped at one hour.
Explicit timeouts override these defaults. After 10 seconds, commands without
explicit stdin hand off to the process manager without restarting; their original
deadline remains in force. A handed-off command is still pending, not successful.
Managed processes default to a one-hour lifetime and stop when Eirene exits.
On systems with `/bin/bash`, pipelines enable `pipefail`. Commands can receive
literal text through the `stdin` argument, which closes after writing; stderr
remains captured alongside stdout. Output previews keep the beginning and end,
with bounded full artifacts accessible through `read_output`.

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
