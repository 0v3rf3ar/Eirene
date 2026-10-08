# Commit Commands

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / Commit Commands

Commit Commands supplies Git workflows for making a commit, pushing and opening
a pull request, and cleaning local branches whose upstream branch is gone.
These commands perform repository changes; inspect the intended scope first.

## Install

```text
/plugins install commit-commands
/plugins doctor commit-commands
```

Git is required. Push needs a configured remote and working authentication. PR
creation also needs an authenticated GitHub CLI (`gh`) and repository access.
No plugin-specific hook or MCP activation is required.

## Commands

| Canonical command | Action |
| --- | --- |
| `/commit-commands:commit` | Inspect changes, stage them, and create a single commit. |
| `/commit-commands:commit-push-pr` | Prepare a branch as needed, commit, push, and open a PR. |
| `/commit-commands:clean_gone` | Remove stale local branches marked `[gone]`, including associated worktrees. |

Short aliases such as `/commit` are available when unambiguous. `/commit` is not
a separate built-in Eirene command. The `/commit-commands` entry can help select
a workflow, but does not imply that all three should run.

## Make a scoped commit

```text
/commit-commands:commit Commit only the invoice validation fix and its test. Leave the unrelated settings change unstaged.
```

The workflow inspects status, diffs, and recent commit conventions. State which
files or behavior belong in the commit when other work is present. Check the
resulting commit and staged state in your usual Git tools.

## Push and create a PR

```text
/commit-commands:commit-push-pr Publish the CSV export change in a new branch and open a PR against main. Include the verification results.
```

This explicitly requests remote actions. Normal permissions still apply; no
plugin metadata bypasses them. A failed push or PR creation does not necessarily
undo a commit that already succeeded.

## Clean stale branches

`clean_gone` is a destructive cleanup workflow. Its upstream instructions can
force-remove associated worktrees and delete local branches. Review the branch
and worktree list and preserve work you need before asking for cleanup. A `[gone]`
marker reflects the local tracking state; it is not a guarantee that a branch has
nothing valuable on it.

```text
/commit-commands:clean_gone First list the stale branches and worktrees. Wait for me to choose what to remove.
```

Use [modes and permissions](../harness.md) to choose the appropriate approval
behavior. Embedded upstream shell snippets are performed through normal tools,
with host-appropriate adaptations where necessary.

Source: [Anthropic official plugins](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/commit-commands).

## Configuration and Git state

`plugins.commit-commands` controls command availability; this written bundle
requires no executable hook trust or MCP grant. Git identity, remote URLs, and
GitHub CLI authentication are external Git/gh configuration, not provider API
keys in Eirene's file. A working model connection does not authenticate a push.

The session stores requests and results, not a rollback transaction over Git.
After a partial failure inspect both `git status` and the actual commit/remote
state before repeating the workflow. See [config.json](../config-file.md),
[session event records](../sessions.md#event-log-format), and
[execution boundaries](../harness.md).
