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

## Provider and runtime limits

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
