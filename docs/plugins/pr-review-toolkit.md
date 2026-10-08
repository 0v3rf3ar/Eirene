# PR Review Toolkit

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / PR Review Toolkit

PR Review Toolkit organizes reviews around specific concerns: tests, errors,
comments, types, general code quality, and simplification. Choose the concerns
that match a change rather than running unrelated passes.

## Install and invoke

```text
/plugins install pr-review-toolkit
/plugins doctor pr-review-toolkit
/pr-review-toolkit:review-pr tests errors
```

Git supplies change context. GitHub CLI (`gh`) is used when the workflow needs
PR information. The root `/pr-review-toolkit` forwards to `review-pr`; `/review-pr`
is available as a short alias when unambiguous.

## Review aspects

| Argument | Focus |
| --- | --- |
| `comments` | Accuracy and maintainability of comments and documentation. |
| `tests` | Test coverage quality and completeness. |
| `errors` | Error handling and silent failures. |
| `types` | Type design, invariants, and encapsulation. |
| `code` | General quality and project conventions. |
| `simplify` | Clarity and maintainability; can lead to edits. |
| `all` | All applicable reviews; the default. |
| `parallel` | Request concurrent independent passes where supported. |

Arguments can be combined, such as `tests errors` or `all parallel`. State the
change or PR scope when it is not obvious from the current workspace.

## Specialist profiles

| Profile | Purpose |
| --- | --- |
| `code-reviewer` | General review against project guidance. |
| `code-simplifier` | Improve clarity while preserving behavior. |
| `comment-analyzer` | Check comment accuracy and long-term value. |
| `pr-test-analyzer` | Evaluate behavior coverage and test quality. |
| `silent-failure-hunter` | Find swallowed errors and misleading fallback behavior. |
| `type-design-analyzer` | Assess type constraints and design invariants. |

View them with `/agents list`. A main-agent profile command uses the form
`/pr-review-toolkit:agent-PROFILE`, for example
`/pr-review-toolkit:agent-silent-failure-hunter`.

## Workflow and output

The command finds changed files, selects relevant passes, collects their reports,
and groups critical issues, important issues, and suggestions into an action plan.
It can run passes sequentially or independently, according to the available
provider and runtime.

```text
/pr-review-toolkit:review-pr all parallel. Keep every pass read-only and report findings before proposing changes.
```

The `simplify` aspect is not inherently a read-only audit. State that you want
analysis only if you do not want edits. Independent read-only tasks cannot use
imported MCP or hooks on Eirene-managed API connections. See
[specialists](../specialists.md) for limits and model usage.

For a local read-only review without plugins, use [built-in `/review`](../review.md).
For the upstream GitHub commenting workflow, see [Code Review](code-review.md).

Source: [Anthropic official plugins](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/pr-review-toolkit).

## Profiles, aliases, and permissions

`plugins.pr-review-toolkit` controls the installed bundle. Its agent profiles
produce `agent-PROFILE` command suffixes and are indexed separately from skills.
The root entry forwards to an installed `review-pr` command when present. Short
aliases depend on all enabled plugins, so use the canonical namespaced command
in saved procedures.

`parallel` is workflow text interpreted by the agent; the managed delegation
tool enforces its own batch/concurrency limits. A requested simplification edit
changes which permissions the turn requires. See
[delegation state](../specialists.md#state-and-configuration-of-delegated-passes),
[plugin adaptation](../plugins.md#command-adaptation), and
[config maps](../config-file.md#skill-and-plugin-maps).
