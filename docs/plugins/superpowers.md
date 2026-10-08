# Superpowers

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / Superpowers

Superpowers supplies explicit engineering workflows: clarify a design, write a
plan, implement with verification, debug systematically, and review before
finishing a branch. Use the workflow matching the current task rather than
running every skill in sequence.

## Install

```text
/plugins install superpowers
/plugins inspect superpowers
/superpowers
```

The entry command helps choose a relevant workflow. The written skills work
without trusted executable hooks. For automatic session-start guidance, inspect
and then use `/plugins trust superpowers`. The startup hook needs Bash; on Windows,
the upstream wrapper needs Git Bash. Git is required for worktree and branch
workflows.

## Skill commands

Each command below uses the prefix `/superpowers:`. An unambiguous short alias
can also be used; the namespaced form is the reliable form across bundles.

| Command suffix | Purpose |
| --- | --- |
| `brainstorming` | Clarify intent, requirements, tradeoffs, and a design before implementation. |
| `writing-plans` | Turn requirements into an implementation and verification plan. |
| `executing-plans` | Carry out a plan in the current session. |
| `subagent-driven-development` | Use focused implementation and review passes for planned tasks. |
| `dispatching-parallel-agents` | Split independent investigations into separate passes. |
| `systematic-debugging` | Gather evidence and identify a cause before proposing a fix. |
| `test-driven-development` | Work through a failing check, minimal fix, and refactoring cycle. |
| `verification-before-completion` | Check evidence before claiming a result is complete. |
| `requesting-code-review` | Ask for a review at an appropriate point in the workflow. |
| `receiving-code-review` | Evaluate feedback and verify proposed changes. |
| `using-git-worktrees` | Prepare an isolated Git worktree for feature work. |
| `finishing-a-development-branch` | Verify work and decide how to integrate a completed branch. |
| `using-superpowers` | Explain the bundle's skill-selection workflow. |
| `writing-skills` | Create, refine, and validate reusable skill guidance. |
| `diagnosing-superpowers` | Investigate a workflow that ignored plans, repeated work, or gave poor results. |

## Example: design to completion

```text
/superpowers:brainstorming Add CSV export to the invoice list. Preserve filters and limit access to existing roles.
/superpowers:writing-plans Turn the agreed design into a plan with verification steps.
/superpowers:executing-plans Implement the agreed CSV export plan.
/superpowers:verification-before-completion Check the result against the agreed requirements.
```

Each invocation is a separate task. Review the design and plan before asking for
implementation. Some skills create design or plan documents; those writes need
a normal mode and the applicable approval. Eirene's `/plan` is separate saved
session progress, even when a skill also writes its own plan file.

## Debugging and review

```text
/superpowers:systematic-debugging Investigate the intermittent duplicate-import test. Show evidence before changing behavior.
```

The debugging workflow aims to establish the cause, not just silence the symptom.
Testing skills require your project's real tools and environment. Visual
brainstorming extras may need Node.js and normal execution access.

Specialist workflows use the selected provider/model on API connections. Native
CLI delegation depends on that CLI, with sequential fallback where necessary.
See [specialists](../specialists.md) for concurrency and read-only limits.

Older upstream instructions may mention `/brainstorm`, `/write-plan`, or
`/execute-plan`. The imported skill names listed here use the current names;
check `/help` for your installed version. Refresh does not fetch upstream updates.

Source: [obra/superpowers](https://github.com/obra/superpowers).
