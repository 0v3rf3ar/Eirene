# Superpowers

[Documentation](../../README.md) / [Plugin catalog](../plugin-catalog.md) / Superpowers

Superpowers provides explicit engineering workflows: clarify a design, write a plan, implement with verification, debug systematically, and review before finishing a branch. Use the workflow that fits the task at hand, rather than running every skill in sequence.

## Install

```text
/plugins install superpowers
/plugins inspect superpowers
/plugins trust superpowers
/superpowers
```

Eirene ships this bundle, so installing needs no network. `/superpowers` helps you choose a workflow. Trusting also turns on the automatic session-start guidance, which needs Bash, or Git Bash on Windows. Worktree and branch workflows need Git. Visual brainstorming may need Node.js.

## Workflows

Each command begins with `/superpowers:`, and the short form works when it is unambiguous.

| Command suffix | Purpose |
| --- | --- |
| `brainstorming` | Clarify intent, requirements, tradeoffs and a design before implementation. |
| `writing-plans` | Turn requirements into an implementation and verification plan. |
| `executing-plans` | Carry out a plan in the current session. |
| `subagent-driven-development` | Use focused implementation and review passes for planned tasks. |
| `dispatching-parallel-agents` | Split independent investigations into separate passes. |
| `systematic-debugging` | Gather evidence and identify a cause before proposing a fix. |
| `test-driven-development` | Work through a failing check, minimal fix and refactoring cycle. |
| `verification-before-completion` | Check the evidence before claiming a result is complete. |
| `requesting-code-review` | Ask for a review at an appropriate point. |
| `receiving-code-review` | Evaluate feedback and verify proposed changes. |
| `using-git-worktrees` | Prepare an isolated Git worktree for feature work. |
| `finishing-a-development-branch` | Verify work and decide how to integrate a finished branch. |
| `using-superpowers` | Explain how the bundle chooses skills. |
| `writing-skills` | Create, refine and validate reusable skills. |

## Example: from design to completion

```text
/superpowers:brainstorming Add CSV export to the invoice list. Preserve filters and limit access to existing roles.
/superpowers:writing-plans Turn the agreed design into a plan with verification steps.
/superpowers:executing-plans Implement the agreed CSV export plan.
/superpowers:verification-before-completion Check the result against the agreed requirements.
```

Each command is a separate task, so review the design and plan before asking for implementation. Some skills write design or plan documents to your workspace, by default under `docs/superpowers/`. That needs a normal mode and the usual approval. These documents are separate from Eirene's [session plan](../../guides/plans.md), and the two are not synchronized.

## Example: debugging

```text
/superpowers:systematic-debugging Investigate the intermittent duplicate-import test. Show evidence before changing behavior.
```

## Differences from the original

- Subagent workflows run on your selected model, because Eirene's delegation cannot choose another per task. Skills that want a stronger model ask you to use `/model`.
- Tasks that change files run one at a time, and finished subagents cannot be resumed. See [Subagents](../../guides/subagents.md#how-delegation-works).
- `using-git-worktrees` uses Git directly.
- `diagnosing-superpowers` is left out, because it reads another host's transcripts.
- The visual brainstorming page does not load the original's remote logo.

Older upstream instructions may mention `/brainstorm`, `/write-plan` or `/execute-plan`. Use the names above, or check `/help`.

## Origin

Made by Jesse Vincent, with thanks. Eirene ships a copy adapted from version 7.0.2 of [obra/superpowers](https://github.com/obra/superpowers). `/plugins update superpowers` fetches the newest copy from [Eirene's repository](https://github.com/0v3rf3ar/Eirene/tree/master/eirene/plugins/superpowers). If you installed Superpowers from GitHub earlier, this replaces it, and you need to trust it again.
