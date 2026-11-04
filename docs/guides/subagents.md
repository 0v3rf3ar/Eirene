# Subagents

[Documentation](../README.md) / Guides / Subagents

Eirene can hand parts of a task to subagents: separate agents with their own fresh context. This is useful for independent reviews
and for investigating several things at once without filling the main conversation.

## Request subagents

Ask in ordinary language:

```text
Have independent reviewers inspect error handling and test coverage for this change. Keep both passes read-only, then combine their findings.
```

The main agent names each subagent after its job, such as `error-handling-reviewer`. The names appear in the tool output, the
result and `/subagents`.

## How delegation works

On connections where Eirene runs the agent loop:

| Rule | Limit |
| --- | --- |
| Tasks in one batch | Up to 8 |
| Running at the same time | Up to 4 read-only tasks. A batch containing any task that writes runs one at a time. |
| Length of one task | Up to 40 model rounds and 10 minutes |
| Nesting | Subagents cannot delegate further |

**Context.** A subagent receives its task and any enabled Eirene and plugin guidance, not the parent conversation. It uses the same
provider, model and workspace. If you need something specific, such as paths, revisions or requirements, make sure the task says so.

**Access.** Subagents are read-only by default, running in Plan mode without plugin hooks or MCP servers. Implementation tasks can run
in a normal mode, under the parent's permissions.

**Approvals.** Answers are shared. Choosing "yes, and don't ask again for this tool" in the main agent or any subagent stops that
prompt across the session.

**Cost.** Every subagent uses tokens or plan allowance, added to the parent's totals. Results can be partial or fail, and getting
several opinions does not make any finding correct.

## External CLI connections

Codex and Claude Code use their own delegation when it is available. If it is not, specialist passes run one after another, and Eirene
says so. Their subagents appear in `/subagents` only if the CLI exposes them as separate sessions.

## Specialist profiles

Some plugins include profiles for particular jobs, such as exploring code or analyzing tests. List the ones from your enabled plugins:

```text
/agents list
```

[Feature Dev](../extending/plugins/feature-dev.md) provides exploration, architecture and review profiles.
[PR Review Toolkit](../extending/plugins/pr-review-toolkit.md) provides six review specialists.

A profile can be used in two ways:

- **As a command**, which runs in the main conversation and follows the profile's instructions. It does not create a separate agent:

  ```text
  /feature-dev:agent-code-explorer Trace invoice validation and identify the key files. Do not edit.
  ```

- **As a subagent**, when you ask for an independent pass and the model delegates to that profile.

A profile supplies instructions only. It does not select a different provider or model tier, even if the plugin's original text
mentions one.

## Browse subagent sessions

Once a session has subagents, a line under the mode line shows how many, such as `◆ 4 subagents`. The diamond animates while any of them
is working. Click it, or run this command, to open a tree of the session and its subagents:

```text
/subagents
```

| Key | Action |
| --- | --- |
| Up, Down | Move between sessions. |
| Left, Right | Collapse or expand a branch. |
| Enter | Open the selected conversation. |
| M | Open the top-level session. |
| Escape | Close the tree. |

You can look at the tree while work is running, but finish the turn before switching. Opening a subagent's session shows its prompts,
replies, tool calls and results, and you can continue that conversation.

From a subagent's session:

```text
/subagents parent
/subagents root
/subagents SESSION_ID
```

Each subagent's conversation is saved as its own [session](sessions.md), linked to its parent.
