# Sessions

[Documentation](README.md) / Sessions

A session keeps the conversation for a workspace so you can return to a task.
Messages are saved as you work. Session history is context, not a snapshot of the
project: loading a session does not restore files to their earlier state.

## Resume from the terminal

```sh
eirene -C /path/to/project --resume
eirene -C /path/to/project --resume SESSION_ID
```

The first command opens a picker for saved sessions associated with that
workspace. The second opens a particular session. In a redirected, noninteractive
terminal, `--resume` without an ID lists matching sessions instead of opening the
interface. Use the actual saved identifier in place of `SESSION_ID`.

Every process starts with sandboxed permissions, including a resume. A previous
process's full-access choice is not restored.

## Find or switch inside Eirene

```text
/sessions
/sessions search invoice
```

F3 also opens the session picker. Searches are scoped to the current workspace.
Finish or stop active work before switching. Conversation and prompt history are
restored; the workspace contains whatever files currently exist on disk.

## Export

Get the session ID from `/usage` or the session picker, then choose an output path
inside the workspace:

```text
/sessions export SESSION_ID notes/invoice-session.md
/sessions export SESSION_ID backups/invoice-session.json
```

A `.json` extension selects the importable JSON format. Other extensions select
a readable Markdown export. Quote paths containing spaces. Exports contain
conversation content; review them before sharing when the task involved private
project data.

## Import

```text
/sessions import backups/invoice-session.json
```

Use a JSON export, not a Markdown transcript. Eirene creates an imported session
for the current workspace and reports its new ID. Use `/sessions` to switch to it.
An import does not execute commands from the transcript or restore project files.

## Clear

```text
/clear
```

This clears the active conversation and its saved log, session plan, and usage
counters. Stop current work first. There is no undo command for the cleared
history. Export a session beforehand if you want to keep it.

Clearing is not a revert: file edits and external actions remain. Use your version
control or backups to recover project state. For a long conversation you want to
keep working with, use [`/compact`](context-and-usage.md) rather than clearing it.

## Storage and exit

Session files live under `~/.local/eirene/sessions` by default, or beneath
`EIRENE_HOME` when you select another data directory. `/exit` and Ctrl+D leave the
application and stop its managed processes. See [configuration](configuration.md)
for data backup locations.
