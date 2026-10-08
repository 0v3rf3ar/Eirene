# Plans

[Documentation](README.md) / Plans

A session plan records the objective, steps, progress, and verification notes for
work that spans several actions. It helps you see what remains and gives Eirene
something durable to return to after a resume or context summary.

## Create a plan

Ask in ordinary language:

```text
Make a plan for adding CSV export. Include the data contract, implementation, and verification steps. Wait for me to review it before editing.
```

Use `/agents plan` when you want to keep the investigation read-only. The plan
itself is session metadata, so Eirene can maintain it without changing project
files. Plan mode and a saved plan are different: a saved plan does not enable or
disable execution.

## Inspect progress

```text
/plan
```

Steps can be pending, in progress, completed, or blocked. Ask Eirene to record
verification results as it completes work. A completed step is the agent's
reported state; inspect the actual result and command output when a check matters.

```text
Update the plan with the failed export test and the remaining compatibility check.
```

The plan belongs to the current workspace and session. Resume that session to
continue with its plan. A different session has its own plan.

## Clear a plan

```text
/plan clear
```

Eirene asks for confirmation because clearing the plan cannot be undone through
this command. It clears progress metadata, not project files. `/clear` also clears
the current session plan while clearing the conversation.

For a more structured design-to-implementation workflow, see
[Superpowers](plugins/superpowers.md) and [Feature Dev](plugins/feature-dev.md).
