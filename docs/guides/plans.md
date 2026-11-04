# Plans

[Documentation](../README.md) / Guides / Plans

A session plan records the objective, steps and progress of work that takes many actions. It helps you
see what remains, and gives Eirene something to return to after a resume or a context summary.

A session plan and [Plan mode](modes-and-permissions.md#modes) are separate things. Plan mode blocks
changes; a session plan is a progress list and blocks nothing. They do work well together, because
Eirene can write a plan in Plan mode: the plan is stored outside your project.

## Create a plan

Ask for one in ordinary language:

```text
Make a plan for adding CSV export. Include the data contract, implementation and verification steps. Wait for me to review it before editing.
```

## Check progress

```text
/plan
```

Each step is pending, in progress, completed or blocked, and at most one is in progress at a time. A
plan can hold up to 100 steps. Ask Eirene to record results as it goes:

```text
Update the plan with the failed export test and the remaining compatibility check.
```

A completed step is what the agent reported. When a check matters, look at the command output too.

A plan belongs to one session in one workspace. Resume that session to continue with it.

## Clear a plan

```text
/plan clear
```

Eirene asks for confirmation, since this cannot be undone. It removes the progress record, not any
project files. `/clear` also removes the plan along with the conversation. The interface may also clear a
fully completed plan when it refreshes, so use a project document if you want a permanent record.

For more structured workflows from design to implementation, see the
[Superpowers](../extending/plugins/superpowers.md) and
[Feature Dev](../extending/plugins/feature-dev.md) plugins.
