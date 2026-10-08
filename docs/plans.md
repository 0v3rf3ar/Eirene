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

## Stored schema and validation

Plan JSON contains `root`, `objective`, `steps`, `notes`, and a numeric Unix
`updated` timestamp. Each step contains `text`, `status`, and `verification`:

```json
{
  "root": "/absolute/path/to/project",
  "objective": "Implement CSV export",
  "steps": [
    {"text": "Define exported columns", "status": "completed", "verification": "Reviewed the field mapping"},
    {"text": "Implement endpoint", "status": "in_progress", "verification": ""}
  ],
  "notes": "Preserve the existing authorization rules",
  "updated": 1700000000.0
}
```

The allowed statuses are `pending`, `in_progress`, `completed`, and `blocked`.
Updates accept at most 100 steps and at most one step in progress. Step text and
verification are each truncated to 500 characters; text must not be empty.
Setting a step in progress through the status operation returns any previous
in-progress step to pending. Step indices are one-based.

Plans are saved atomically under `plans/` using a hash of workspace/session
identity, rather than a human-readable filename. The UI can clear a fully
completed plan when refreshing it; use a separate project document when you need
a permanent completion record. See [data layout](data-layout.md) for identities
and [sessions](sessions.md) for the event log, which is a separate file.
