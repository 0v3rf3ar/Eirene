# Sessions

[Documentation](../README.md) / Guides / Sessions

A session is one saved conversation in a workspace. Messages are saved as you work, so you can return to
a task later.

A session holds the conversation, not a copy of your project. Loading one does not put your files back
the way they were.

## Resume from your shell

```sh
eirene --continue             # the most recent session in this workspace
eirene --resume               # choose from a list
eirene --resume SESSION_ID    # open a specific session
```

Add `-C /path/to/project` to resume for another directory. Only sessions from that exact workspace are
listed, so a project you moved to a new path will not show its old sessions.

Every process starts [sandboxed](modes-and-permissions.md#the-sandbox), even if the earlier one used full
access.

## Find and switch sessions

```text
/sessions
/sessions search invoice
```

F3 also opens the session list. Search covers titles and messages in up to 500 recent sessions of the
current workspace, and it returns up to 20 results. It does not search saved command output.

Finish or stop any running work before switching. The conversation and your prompt history come back,
while the workspace stays as it is on disk.

## Export a conversation

Get the session ID from `/usage` or the session list, then export it to a path in the workspace:

```text
/sessions export SESSION_ID notes/invoice-session.md
/sessions export SESSION_ID backups/invoice-session.json
```

A path ending in `.json` creates a file you can import. Anything else creates readable Markdown. Quote
paths that contain spaces.

An export contains the current context, so after [compaction](context-and-usage.md#compaction) it has the
summary rather than every earlier message. It does not include saved command output, the plan, or
credentials. For a complete archive, copy the session log and its outputs from the
[data directory](../reference/data-directory.md#sessions-and-saved-output).

Exports contain your conversation content, so review them before sharing.

## Import a conversation

```text
/sessions import backups/invoice-session.json
```

Eirene creates a new session for the current workspace and reports its ID, and you can switch to it with
`/sessions`. This is the right way to move a conversation to another workspace or computer. It accepts a
JSON export only, not Markdown or a raw `.jsonl` log. Importing never runs commands from the transcript.

## Clear a conversation

```text
/clear
```

This deletes the active conversation's log, its plan and its usage counters, and there is no undo. Export
first if you want to keep it. It does not revert file edits or external actions, which you recover through
version control.

To keep working in a long conversation, use [`/compact`](context-and-usage.md#compaction) instead.

## Workspace trust

The first time you open a workspace interactively, Eirene shows its resolved path and asks whether you
trust its files, before it loads any project instructions, skills or providers. Choose **Yes, trust this
workspace** to continue, or **No, exit Eirene** to leave. Escape, Ctrl+C and Ctrl+D also leave.

Your answer is saved in `trusted_workspaces` in [`config.json`](../reference/configuration.md). Each path
needs its own approval, including subdirectories. Remove a path from the list to be asked again.

Trust does not grant full access or skip approvals. Headless runs and routines do not show this prompt.

## Other commands

- `/pwd` shows the workspace Eirene was started in.
- `/exit` or Ctrl+D leaves Eirene and stops the processes it manages.
- `/usage` shows the current session's ID and totals. Totals reset when you switch sessions, so they do not
  add up to a conversation's lifetime usage.
- [`/subagents`](subagents.md#browse-subagent-sessions) opens the sessions of delegated work.

The [data directory reference](../reference/data-directory.md#session-log-format) describes the session
log format.
