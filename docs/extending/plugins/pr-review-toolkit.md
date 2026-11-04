# PR Review Toolkit

[Documentation](../../README.md) / [Plugin catalog](../plugin-catalog.md) / PR Review Toolkit

This plugin organizes reviews around specific concerns: tests, errors, comments, types, general code quality and simplification. Choose the ones that fit a change. For a quick read-only review with no plugin, use the built-in [`/review`](../../guides/code-review.md).

## Install

```text
/plugins install pr-review-toolkit
/plugins trust pr-review-toolkit
/plugins doctor pr-review-toolkit
```

It uses Git for the changes, and the GitHub CLI (`gh`) when a workflow needs pull request information.

## Run a review

```text
/pr-review-toolkit:review-pr tests errors
/pr-review-toolkit:review-pr all parallel. Keep every pass read-only and report findings before proposing changes.
```

`/pr-review-toolkit` forwards to `review-pr`, and `/review-pr` works when the short name is unambiguous. Use the full form in saved procedures. State the change or pull request if it is not obvious from the workspace.

| Argument | Focus |
| --- | --- |
| `comments` | Accuracy and maintainability of comments and documentation. |
| `tests` | Test coverage quality and completeness. |
| `errors` | Error handling and silent failures. |
| `types` | Type design, invariants and encapsulation. |
| `code` | General quality and project conventions. |
| `simplify` | Clarity and maintainability. Can lead to edits. |
| `all` | All applicable reviews. This is the default. |
| `parallel` | Ask for independent passes at the same time, where supported. |

The command finds the changed files, selects relevant passes, collects their reports, and groups critical issues, important issues and suggestions into an action plan.

`simplify` is not necessarily read-only, so say if you want analysis only. Read-only subagents cannot use plugin MCP servers or hooks. See [Subagents](../../guides/subagents.md#how-delegation-works) for limits on parallel work.

## Specialist profiles

| Profile | Purpose |
| --- | --- |
| `code-reviewer` | General review against project guidance. |
| `code-simplifier` | Improve clarity while preserving behavior. |
| `comment-analyzer` | Check comment accuracy and long-term value. |
| `pr-test-analyzer` | Evaluate behavior coverage and test quality. |
| `silent-failure-hunter` | Find swallowed errors and misleading fallback behavior. |
| `type-design-analyzer` | Assess type constraints and design invariants. |

`/agents list` shows them. To use one in the main conversation, run `/pr-review-toolkit:agent-PROFILE`, such as `/pr-review-toolkit:agent-silent-failure-hunter`.

## Origin

Made by Anthropic, with thanks. Source: [Anthropic official plugins](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/pr-review-toolkit).
