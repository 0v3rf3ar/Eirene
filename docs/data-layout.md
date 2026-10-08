# Data layout and source structure

[Documentation](README.md) / Data layout and source structure

Three directories have different responsibilities: the installed executable,
the project selected by `-C`, and Eirene's data directory. File edits affect the
project. Configuration, conversations, and application artifacts live in the data
directory. Moving the executable does not move either of the other two.

## Application data tree

The default root is `~/.local/eirene` on all platforms. `EIRENE_HOME` overrides it
before launch. Some directories are created at startup; feature-specific files
and caches appear only when used. Identifiers below are placeholders.

```text
~/.local/eirene/
├── config.json                         saved preferences and connection settings
├── config.json.bak                     best-effort copy after malformed config
├── sessions/
│   └── <session-uuid>.jsonl             event log for one conversation
├── outputs/
│   └── <32-hex-artifact-id>.txt          bounded command/compaction evidence
├── plans/
│   └── <24-hex-identity-hash>.json       structured plan for workspace/session
├── projects/
│   └── <24-hex-workspace-hash>.json      cached project profile
├── skills/
│   ├── <local-skill>.md
│   └── <local-skill>/SKILL.md
├── plugins/
│   └── <installed-name>/               copied plugin bundle and resources
│       ├── plugin.json                 source declaration, when present
│       ├── .eirene-plugin.json          normalized imported index
│       ├── skills/                     optional guidance
│       ├── commands/                   optional task commands
│       └── agents/                     optional specialist profiles
├── plugin-data/
│   └── <plugin-name>/
│       ├── <session-uuid>/             per-session hook state, when used
│       ├── config/                     persistent hook settings, when used
│       └── mcp/                        cache for adapted MCP launchers
├── updates/                            verified standalone update staging
│   └── eirene-<version>[.exe]           downloaded executable awaiting installation
├── tasks.json                          saved task records, schema version 2
├── task-runs/
│   └── <12-hex-task-id>.jsonl           scheduler execution events
├── task-locks/
│   └── <task-id>.lock                  overlap lock containing PID/start time
└── logs/
    ├── eirene.jsonl                     rotating runtime diagnostics
    ├── eirene.jsonl.1                   newest rotated log, when present
    ├── eirene-<task-id>.log             launchd task stdout/stderr, when used
    └── ...
```

Plugin source layouts can use `.claude-plugin/plugin.json`,
`.codex-plugin/plugin.json`, `.agent-plugin/plugin.json`, or
`.github/plugin/plugin.json` instead of a root manifest. The copied bundle
retains supporting files and licenses. The generated `.eirene-plugin.json` is
the imported index; edit source declarations and refresh to rebuild it.

For Playwright, `plugin-data/playwright/mcp` holds npm cache and `browsers/`.
For Serena, `plugin-data/serena/mcp` holds uv cache, `python/`, and `serena/`.
These locations apply to Eirene's recognized launcher adapters; arbitrary MCP
servers use their own declared environment and paths.

## Sessions and artifacts

Session filenames are UUIDs, not titles. The `meta` record stores the workspace's
absolute path. Picker filtering compares that path with the resolved current
workspace, so moving a project can make its old sessions absent from the picker.
A symlink resolving to the same project path does not create a separate project
identity. A session log is created on the first actual user message, not merely
by opening the UI.

JSONL contains one JSON object per line. It is an event log, not the JSON object
accepted by `/sessions import`. See [session record formats](sessions.md#event-log-format)
for the record types and replay rules.

Tool results can refer to `artifact_id`; the corresponding text is in `outputs/`.
Artifacts are not organized under a session directory. Compaction also creates
an artifact with earlier messages. Copying only `sessions/` preserves the event
logs but can leave artifact references unresolved. There is no general artifact
cleanup command or automatic retention period in the artifact writer.

A plan filename is the first 24 hex characters of SHA-256 over the resolved
workspace path plus a NUL separator and session ID. Older workspace-only plans
use the workspace path alone. Plan JSON contains `root`, `objective`, `steps`,
`notes`, and `updated`. Project profiles use a 24-character SHA-256 prefix of
the workspace path and contain `signature` plus `profile`; they can be regenerated.

## Backup, transfer, and recovery

Close Eirene before copying its data tree so files and configuration agree.
Include `config.json`, sessions, referenced outputs, plans, plugin bundles and
state, and task records when you want a complete application-data backup.
Include the workspace itself separately; conversations do not contain a working
copy or Git snapshot.

POSIX configuration saves use `0600` for the config and `0700` for its parent.
Several state writers also set private file permissions. Windows uses the host's
account permissions and ACLs. A copied tree should retain restrictive permissions.

A data-tree copy does not contain OS keyring entries, Codex/Claude Code account
logins, external service databases, or installed OS scheduler entries.
Keyring references need the same credentials on the destination. Scheduler
entries contain executable/data paths and need reinstalling after relocation.
Linux scheduler units are under `~/.config/systemd/user/eirene-TASK_ID.service`
and `.timer`. macOS uses `~/Library/LaunchAgents/com.eirene.TASK_ID.plist`;
Windows registers `Eirene-TASK_ID` in Task Scheduler. These records are outside
the data tree. Project-path hashes and session workspace metadata also refer
to their original locations. For transferring a conversation to another workspace, use JSON export
and import rather than rewriting all path-bearing state by hand.

`/clear` removes the active session log and plan, but is not a complete data-tree
cleanup. It does not revert project changes or remove every referenced artifact.
Removing project-profile caches discards derived metadata; removing logs discards
diagnostics; removing sessions, plans, tasks, or plugin state discards user state.
Disable/remove OS scheduler entries through task controls before deleting their
saved records. Back up a damaged config and `config.json.bak` before recovery.

## Repository structure

This is the Python source tree, separate from the runtime data tree above:

```text
Eirene/
├── eirene/
│   ├── __main__.py           argument parsing and interactive/headless selection
│   ├── app.py                Textual application, interaction and session lifecycle
│   ├── headless.py           single-prompt and scheduled-task runner
│   ├── evaluate.py           evaluation entry points
│   ├── commands/             slash-command handlers and plugin command expansion
│   ├── core/                 agent loop, config, sessions, plans, permissions,
│   │                         context, plugins, MCP client and diagnostics
│   ├── providers/            API adapters and native CLI bridges
│   ├── tools/                tool schemas, filesystem/shell/search/browser helpers
│   ├── scheduling/           task schema, history, locks and OS scheduler backends
│   └── ui/                   composer, transcript, pickers, approvals and status
├── docs/                     user and technical documentation
│   └── plugins/              individual bundle guides
├── tests/                    behavior checks and fixtures
├── skills/                   example Markdown guidance in the source distribution
├── img/                      repository images
├── scripts/                  packaging, release metadata and benchmark helpers
├── pyproject.toml            package metadata and tool configuration
├── requirements.txt          source/build runtime dependencies
├── requirements-dev.txt      testing and build tools
├── build.py                  standalone build entry point
├── install.sh                POSIX release installer
├── install.ps1               PowerShell release installer
├── README.md
└── SECURITY.md
```

For API connections, the agent assembles instructions and tool schemas, streams
model events, checks permissions, dispatches tool calls, and appends results to
the session. The next model request receives those observations. For native CLI
connections, the provider bridge forwards a task and policy to the external
agent and translates its output; that CLI owns tools and context. This is why
identical configuration fields do not necessarily control both runtimes.

See [configuration reference](config-file.md), [sessions](sessions.md),
[plugins](plugins.md), and [scheduled tasks](scheduling.md) for the schemas.
