# Specialist agents

[Documentation](README.md) / Specialist agents

Some plugins include focused profiles for exploration, architecture, code review,
or test analysis. A profile supplies a role and instructions. It can guide the
main agent or be used for an independent task pass.

## Find profiles

```text
/agents list
```

This lists profiles from enabled plugins and their profile commands. It does not
change the working mode. The normal `/agents auto`, `/agents manual`, and
`/agents plan` commands still select modes.

[Feature Dev](plugins/feature-dev.md) supplies exploration, architecture, and
review profiles. [PR Review Toolkit](plugins/pr-review-toolkit.md) supplies six
specialists for code, tests, errors, types, comments, and simplification.

## Use a profile in the main turn

```text
/feature-dev:agent-code-explorer Trace invoice validation and identify the key files. Do not edit.
```

A profile command is a main-agent turn following that specialist's guidance. It
does not by itself create a separate agent or guarantee an independent review.
Give the scope and expected report in its arguments.

## Request independent passes

```text
Have independent reviewers inspect error handling and test coverage for this change. Keep both passes read-only, then combine their findings.
```

On Eirene-managed API connections, delegated tasks use fresh contexts on the
selected provider and model. Each receives its task plus enabled host/plugin
guidance, rather than the complete parent conversation. Provide enough context
in the task for a useful result.

A batch can include up to eight tasks. Up to four read-only tasks can run at once;
a batch containing any write task runs sequentially. Delegated tasks default to
read-only Plan mode, without imported hooks or MCP. Authorized implementation
passes can use a normal mode, but still follow the parent policy. Child tasks
cannot delegate again.

Delegation is available on tool-capable API connections whether or not a plugin
is enabled; compact and balanced local profiles offer it only with an enabled
plugin. The main agent names every subagent for its job, such as
`football-historian`; names are unique within a batch and appear in the tool
output, the result, and `/subagents`.

Once a session has subagents, a line under the mode line shows how many, such as
`◆ 4 subagents`. While any of them is working the diamond turns
(`◇ ◈ ◆ ◈`); with `reduce_motion` it stays still. Click it to
open `/subagents`. The count is rebuilt from the
session log when you resume.

Approval answers are shared: choosing "yes, and don't ask again for this tool"
in the main agent or any subagent stops the prompt for that tool everywhere in
the session, including subagents already waiting to ask.

## Provider and runtime limits

Use `/subagents` to open a draggable popup tree with the mother session and its
subagents. Up/Down browses nodes; Left/Right collapses or expands branches; Enter
opens the selected conversation's transcript, including saved prompts, replies,
tool calls, and results. Press M to open the mother session or Esc to close the
popup. Reopen `/subagents` from a child to browse its siblings or return to its
mother. While work is running, the tree permits inspection but blocks switching.
From a child, use `/subagents parent` to return to its immediate parent or
`/subagents root` to return to the top-level session. You can also open a listed
session directly with `/subagents SESSION_ID`. Finish the active turn before
switching sessions; the hierarchy can still be displayed while work is running.

Parent links and completion status are saved for managed delegated tasks. Older
sessions can be linked when their saved delegation results contain child session
IDs. Native CLI subagents are visible only if exposed as separate linked Eirene
sessions. Opening a saved session uses the normal session viewer and allows you
to continue that conversation.

Codex and Claude Code use their native delegation when available. If the CLI does
not offer it, specialist passes can run sequentially with that limitation stated.
Upstream references to particular Claude model tiers do not automatically route
work to different providers in Eirene.

Delegated API tasks have bounded execution: up to 40 model rounds and a ten-minute
timeout per task. Results can be partial or failed. Their sessions are saved and
usage contributes to the parent totals. More reviewers consume more tokens or
subscription allowance; independent passes do not guarantee that a finding is
correct.

Use read-only review passes for independent assessment, then request a specific
fix in the main conversation or an authorized implementation pass. See
[permissions](harness.md) and [review](review.md).

## State and configuration of delegated passes

A delegated managed task has its own session UUID and JSONL log in the same
application data root. It shares the workspace and provider connection but gets
fresh conversation context. A profile supplies additional task instructions;
it does not define a separate API credential or paid model tier.

The child receives the supplied prompt and enabled host/plugin guidance. Pass
paths, revisions, exact requirements, and expected output in that prompt rather
than assuming the parent transcript is visible. Its reported usage is combined
with parent accounting during the live turn, while the saved child session is
separate. Read-only children use Plan mode and cannot start imported executable
integrations. See [config selection](config-file.md#provider-selection-and-credentials)
and [session storage](data-layout.md#sessions-and-artifacts).
