# Eirene Tool Mapping

These skills speak in actions ("dispatch a subagent", "create a todo", "read a file"). In Eirene they
resolve to the tools below.

| Action | Eirene tool |
| --- | --- |
| Invoke a skill | `load_skill`, with a name such as `superpowers:brainstorming` |
| Read a skill's supporting file | `load_plugin_resource`, or `read_file` on the path `load_skill` gives |
| Read a file | `read_file` |
| Create or edit a file | `write_file`, `edit_file` |
| Run a shell command | `run_command` |
| Keep a server or watcher running | `start_process`, then `poll_process` and `stop_process` |
| Search contents, find files | `search_text`, `glob` |
| Find definitions and uses | `find_symbol`, `find_references` |
| Fetch a page, search the web | `web_fetch`, `web_search` |
| Ask your human partner | `ask_user` |
| Dispatch a subagent | `delegate_tasks` |
| Create a todo, mark it complete | `plan_update`, `plan_set_status` |

## Instructions file

When a skill mentions "your instructions file", that is `EIRENE.md` at the workspace root. Eirene also
reads `AGENTS.md`, `.eirene.md`, `CLAUDE.md` and `.github/copilot-instructions.md` if they are there.

## Personal skills

Personal skills live in `~/.local/share/eirene/skills/`, or `$EIRENE_HOME/skills/`. Each is a `.md` file
or a folder with a `SKILL.md`, and appears in `/skills`.

## Subagents

`delegate_tasks` takes 1 to 8 tasks. Each has a unique `name`, a `prompt`, and `read_only`.

- Set `read_only: false` for a task that changes files, including one that writes a report. Read-only
  agents run in plan mode and cannot write.
- Read-only tasks run up to 4 at a time. **Tasks that can write run one at a time**, whatever you send.
- Every agent starts fresh and sees only its prompt. You cannot send a finished agent another message.
- Delegated agents cannot start more agents, and each has a 600 second limit.
- Delegation is unavailable in plan mode and on providers without tools. On a native CLI connection,
  use that CLI's own subagent tool. Never fabricate a dispatch: if none is available, do the work here
  and say so.

## Models

Every delegated agent uses the provider and model selected for the session, and you cannot choose
another per task. Where a skill calls for a more capable model, ask your human partner whether to
switch with `/model`. Do not wait for an answer if the work can safely go on as it is.
