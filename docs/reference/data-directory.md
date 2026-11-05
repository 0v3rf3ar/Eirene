# Data directory

[Documentation](../README.md) / Reference / Data directory

Three locations matter when you use Eirene, and they are independent of each other:

| Location | Contains | Default |
| --- | --- | --- |
| Executable | The program. | `~/.local/bin` or `%LOCALAPPDATA%\Programs\eirene` |
| Workspace | Your project. File edits happen here. | The directory you start in, or `-C` |
| Data directory | Settings, conversations and everything else on this page. | `~/.local/share/eirene` |

The data directory is the same on every system; on Windows, `~` is your user folder. Set `EIRENE_HOME` before launch to use a different one. `eirene --doctor` prints the one in use.

If an older `~/.local/eirene` exists and the new location does not, Eirene moves it at startup. If both exist, it uses the new one without merging. Setting `EIRENE_HOME` turns off this move.

## Contents

Some items appear only once a feature has been used.

```text
~/.local/share/eirene/
├── config.json                 settings and saved connections
├── config.json.bak             copy made after a malformed config
├── session-index.sqlite3       cache for session lists; safe to delete
├── sessions/
│   └── <session-uuid>.jsonl    one conversation's event log
├── outputs/
│   └── <artifact-id>.txt       saved command output and compaction history
├── attachments/                private copies of files you attached
├── plans/
│   └── <hash>.json             one session's plan
├── projects/
│   └── <hash>.json             cached project profile; regenerated when needed
├── skills/                     your skills, and copies of plugin skills
├── plugins/
│   └── <name>/                 installed plugin files
├── plugin-data/
│   └── <name>/                 plugin state, caches and downloaded runtimes
├── marketplaces/               added marketplaces and their catalogs
├── chatgpt/auth.json           ChatGPT plan sign-in
├── mcp-auth/                   MCP tokens and header credentials
├── updates/                    verified downloads awaiting installation
├── windows-sandbox/            Windows sandbox state
├── tasks.json                  saved routines
├── task-runs/
│   └── <task-id>.jsonl         run history
├── task-outputs/
│   └── <task-id>/<run-id>.json full output of the last 50 runs
├── task-worktrees/
│   └── <task-id>/<run-id>/     isolated Git copies kept by runs that changed files
├── task-locks/
│   └── <task-id>.lock          prevents overlapping runs
└── logs/
    ├── eirene.jsonl            runtime log
    ├── eirene.jsonl.1          most recent rotated log
    ├── crashes/
    │   └── crash-*.txt         crash reports; newest 20 kept
    └── eirene-<task-id>.log    routine output on macOS
```

## Sessions and saved output

Session files are named by ID, not by title. Each stores the workspace's absolute path, and session lists filter on it, so sessions from a project you moved will not appear at the new path. To move a conversation, use [JSON export and import](../guides/sessions.md#export-a-conversation). A session log is created by your first message, not by opening Eirene.

Tool results can refer to an `artifact_id`, whose text is saved in `outputs/`. Outputs are not grouped by session and are not cleaned up automatically. Each is capped at about 20 MB. Copying `sessions/` alone leaves those references unresolved.

### Session log format

Each line of a session log is a JSON object with a type field `t` and usually a Unix timestamp `ts`. This format differs from a JSON export.

```json
{"t":"meta","schema":2,"id":"SESSION_UUID","name":"Example","sandbox":"/absolute/project","started":1700000000.0,"ts":1700000000.0}
{"t":"user","content":"Explain the importer","ts":1700000001.0}
{"t":"assistant","content":"The importer validates each row.","ts":1700000002.0}
```

| Type | Contains |
| --- | --- |
| `meta` | Session ID, name, workspace (`sandbox`) and start time. |
| `user` | `content`, and any `attachments`. |
| `assistant` | `content`, and any `tool_calls` and `thinking`. |
| `tool_result` | `tool_call_id`, `name`, `content`, `is_error`, `seconds` and `artifact_id`. |
| `rename` | A later title. |
| `compact` | `summary` and `messages`, which replace the active context. Earlier lines stay in the file. |
| `provider_tool` | Activity from an external CLI. |
| `turn_status` | `status`, `seconds` and `output_tokens` of a finished turn. The last one is shown again on resume. |
| Others | Diagnostics such as `tool_state`, `permissions`, `guard`, `cancelled` and `error`. |

Blank and malformed lines are skipped on reading, so a damaged log can be partly recovered. Tool calls left pending when a session ended are marked with an unknown outcome and are never re-run on resume.

### Runtime log format

Each line of `logs/eirene.jsonl` has a UTC `ts`, `level`, `event` and `logger`, plus details for that event such as the session ID or a duration. Failures can include a traceback. Set [`log_level`](configuration.md#numeric-limits) or use `--debug` for more detail. [Reporting bugs and crashes](../help/reporting-issues.md) explains how to share logs safely.

## Back up

Close Eirene and copy the whole data directory. Back up your projects separately, since sessions contain no working copy or Git snapshot. Keep the copy's permissions restrictive, because it can contain your API keys.

A copy does not include:

- system keyring entries;
- Codex and Claude Code logins;
- databases of external services, such as an [OmniRoute](../providers/omniroute.md) gateway;
- OS scheduler entries.

## Move to another computer

Copying the data directory carries over settings, sessions and plugins, but paths inside them still refer to the old locations.

- **Keyring keys** must be entered again on the new computer.
- **Conversations** are best moved with JSON export and import.
- **Routines** contain executable and data paths, and their scheduler entries stay behind. Remove them with `/routines` on the old computer, then create them again on the new one.

Scheduler entries live outside the data directory:

| System | Location |
| --- | --- |
| Linux | `~/.config/systemd/user/eirene-TASK_ID.service` and `.timer` |
| macOS | `~/Library/LaunchAgents/com.eirene.TASK_ID.plist` |
| Windows | `Eirene-TASK_ID` in Task Scheduler |

## Clean up

| To remove | Effect |
| --- | --- |
| `session-index.sqlite3`, `projects/` | Nothing lost; rebuilt when needed. |
| `logs/` | Diagnostics lost. |
| `outputs/` | Older command output can no longer be read back, and `read_output` references fail. |
| `sessions/`, `plans/`, `tasks.json`, `plugin-data/` | Your data lost. Remove routines through `/routines` first. |

`/clear` removes only the active session's log and plan. It does not remove referenced outputs or revert project changes.
