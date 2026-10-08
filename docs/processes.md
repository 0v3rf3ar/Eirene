# Running commands and background work

[Documentation](README.md) / Running commands

Eirene can run your project's tests, builds, and other shell commands using the
host environment. It can also manage long-running servers and watchers while you
continue the conversation.

## Run a check

```text
Run the auth test suite from the server directory and show me the failing test output.
```

Commands use the workspace or a specified working directory. A directory change
in one command is not a persistent change for later commands. Mention the relevant
package when a repository contains several projects.

Manual mode asks for approval except for recognized harmless read operations.
Auto mode permits commands within the available
sandbox, but network and external host access can still need approval. Windows
commands have additional approval requirements; see [permissions](harness.md).

## Inspect output

Command blocks show a short preview and can be expanded. The model receives
bounded output rather than every byte of a large log. Eirene keeps a bounded
saved output artifact so you can ask for a particular error, tail, or later range.

```text
Read the saved build output around the first compiler error and explain the cause.
```

Expanded transcript output is limited to about 200 KB and saved artifacts to
about 20 MB per output. A truncated preview is not the complete result. Native
Codex and Claude Code connections can show only the output exposed by their CLI.

## Manage background work

A command that runs longer than the brief foreground allowance can continue in
the background without restarting. Builds and tests may start there immediately.
The background line appears below the model name while work is active.

Press Ctrl+B or select that line to view output, see state, or stop a command.
Ask Eirene to wait for the result before treating a check as complete. Silence
from a command is not a successful exit or evidence of a hang.

## Start a server or watcher

```text
Start the development server as a managed process. Tell me its local URL and keep it running while we inspect the page.
```

Managed services normally remain until you stop them or exit Eirene. Ask for an
automatic stop time when appropriate. Eirene attempts to stop descendant processes
as well as the main command. Do not rely on a managed service surviving application
exit or an execution-access change.

A service started under a temporary full-host approval is stopped when that
response's grant ends. To run a service beyond Eirene's lifecycle, start it
separately in your own terminal.

## Timeouts

Default command deadlines depend on the type of work:

| Work | Typical default deadline |
| --- | --- |
| Simple reads | 30 seconds |
| Unclassified commands | 120 seconds |
| Tests and package operations | 300 seconds |
| Builds | 600 seconds |

Ask for a longer deadline when a legitimate task needs it; explicit command
timeouts can be as long as 24 hours. A timeout stops the command and is a failed
or incomplete check, not a passed result. Headless prompts and scheduled tasks
also have a separate overall run timeout; see [headless](headless.md).
