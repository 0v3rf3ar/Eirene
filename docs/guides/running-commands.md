# Running commands

[Documentation](../README.md) / Guides / Running commands

Eirene can run your tests, builds and other shell commands, and can keep servers and watchers
running while you continue the conversation.

## Run a check

```text
Run the auth test suite from the server directory and show me the failing test output.
```

Commands run in the workspace or in a directory you name. A `cd` in one command does not carry
over to the next, so mention the right package when a repository contains several.

Whether a command asks first depends on your [mode](modes-and-permissions.md#modes). Commands run
in the [sandbox](modes-and-permissions.md#the-sandbox), without network access until you approve
it. They start without your shell profile, so aliases and `PATH` changes from `.bashrc` are not
available.

## Read the output

Each command block shows a short preview, and selecting it expands it to about 200 KB. The full
output is saved separately, up to about 20 MB, and the model receives a bounded excerpt, so a long
log does not fill its context. You can ask for any part of the saved copy:

```text
Read the saved build output around the first compiler error and explain the cause.
```

Codex and Claude Code connections can show only the output their CLI exposes.

## Background work

A command that runs past a brief foreground period continues in the background without
restarting, and builds and tests may start there straight away. A line below the model name shows
that work is active.

Press Ctrl+B, or select that line, to read a command's output and state. Press S to stop the
command; the view stays open on its final output.

When only background commands remain, Eirene waits locally and sends no API requests. When a
command finishes or times out, Eirene sends the model the output and exit code. New input from you
also interrupts the wait.

A quiet command has not necessarily stopped. Check its output before assuming it is stuck.

## Servers and watchers

```text
Start the development server as a managed process. Tell me its local URL and keep it running while we inspect the page.
```

Eirene runs it until you stop it or exit, and you can ask for an automatic stop time. Stopping
also tries to stop the command's child processes.

Managed processes end in these cases:

- You exit Eirene.
- Host access was granted for one response and that response ends.
- You change permissions with `/permissions sandboxed`.

To keep a service running beyond any of these, start it yourself in another terminal. Resuming a
session restores references to saved output, but it cannot bring back a process that has exited.

## Timeouts

| Kind of command | Default limit |
| --- | --- |
| Simple reads | 30 seconds |
| Other commands | 120 seconds, set by [`shell_timeout`](../reference/configuration.md#numeric-limits) |
| Tests and package operations | 300 seconds |
| Builds | 600 seconds |

Ask for a longer limit when a task needs one, up to 24 hours. A command that times out is stopped
and counts as failed. [Headless runs](../automation/headless.md#limits) also have an overall limit.
