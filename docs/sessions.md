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

## Event log format

The on-disk log is `sessions/SESSION_UUID.jsonl`, schema version 2. Every line is
an independent JSON object with a `t` discriminator and usually a numeric `ts`
Unix timestamp. It is different from the object returned by JSON export.

```json
{"t":"meta","schema":2,"id":"SESSION_UUID","name":"Example","sandbox":"/absolute/project","started":1700000000.0,"ts":1700000000.0}
{"t":"user","content":"Explain the importer","ts":1700000001.0}
{"t":"assistant","content":"The importer validates each row.","ts":1700000002.0}
```

| Record | Fields and purpose |
| --- | --- |
| `meta` | `schema`, `id`, `name`, `sandbox`, `started`; initial session identity and workspace. |
| `user` | `content`, optional `attachments`; user input. |
| `assistant` | `content`, optional `tool_calls` and `thinking`; response and requested tools. |
| `tool_result` | `tool_call_id`, `name`, `content`, `is_error`, `seconds`, `artifact_id`; result associated with a call. |
| `rename` | `name`; later title, independent of the filename. |
| `compact` | `summary`, `messages`; replacement active context. Earlier lines remain in the log. |
| `provider_tool` | Native CLI activity, with `id`, `name`, `finished`, result/error/artifact metadata. |
| Other notes | `tool_state`, `permissions`, `guard`, `cancelled`, `error`, `turn_status`, and headless/recovery events; diagnostics rather than chat messages. |

The reader skips blank, malformed, and non-object lines. Reopening a log whose
last line has no newline inserts one before appending, so a torn record does not
swallow the next record. This supports partial recovery, not a guarantee that
missing records can be reconstructed. Writes are flushed; assistant, tool-state,
tool-result, compaction, and native tool records also sync the file.

Resume rebuilds active messages by applying `compact` records. The transcript
can replay the earlier messages without applying compaction, so visible history
and the model's current context can differ. Pending tool calls are repaired with
an unknown-outcome result; they are not executed merely by replaying the log.
Inspect current state before requesting a repeated action.

## Search, export, and import details

Picker listing uses newest file modification time first, with a default recent
list limit of 50. Search examines up to 500 recent workspace sessions, matches
normalized case-insensitive substrings in titles and user/assistant content,
and returns at most 20 results with up to two short snippets. It is not a
full-text database over every tool artifact.

JSON export has `schema`, `id`, `name`, `sandbox`, and `messages`. It exports the
replayed active context, so after compaction it is not an archive of every raw
record. Markdown export also uses active messages. Neither export copies the
artifact files, the plan file, provider credentials, or the project itself.
Keep the raw log and referenced outputs when you need a full archive.

Import assigns a new session UUID and the current workspace; the exported ID
and original workspace are not reused as storage identity. Supported message
roles are user, assistant, and tool. Notes, original log timestamps, and native
CLI execution state are not restored as executable state. A bare `.jsonl` file
is not an importable JSON export.

Switching sessions resets the in-memory usage accumulator and native provider
thread state. Historical token totals are not reconstructed from the log, so
`/usage` after a switch is not lifetime billing for that conversation. See
[data layout](data-layout.md) for backup paths and artifact relationships.
