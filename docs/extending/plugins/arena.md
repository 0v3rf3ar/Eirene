# Arena

[Documentation](../../README.md) / [Plugin catalog](../plugin-catalog.md) / Arena

Arena is for when an answer keeps falling short. Instead of asking again, it gives the same task to many subagents, each with a different strategy. They attack each other's answers, defend and revise their own, and a judge scores every match against a written rubric until one answer is left.

## Install

```text
/plugins install arena
/plugins trust arena
```

Arena needs Python 3.8 or newer and a provider that can use tools. It does not work in Plan mode.

## Use it

```text
/arena
/arena write the headline for our pricing page
/arena --agents 32 fix the flaky test in tests/test_api.py
/arena --seed 7 plan my launch week
```

With no task, it takes your last request and tries to beat the answer you did not like. If it starts because you said an answer was bad, it asks before spending anything.

## Cost and time

| Agents | Rounds | Subagent calls |
| --- | --- | --- |
| 16 (default) | 4 | 91 |
| 100 | 7 | 595 |

Every subagent writes a file, and Eirene runs [subagents that write](../../guides/subagents.md#how-delegation-works) one at a time. A run therefore takes about as long as all its subagents added together, and uses tokens for each on your selected model. Start with a small run on a metered provider or a local model.

Subagents ask for approval to write their files unless the session already allows edits. Switch to [Accept or Auto mode](../../guides/modes-and-permissions.md#modes), or choose "don't ask again" at the first approval.

## What it touches

Subagents write only inside `.arena/` in your workspace. The winning answer comes back to you in the chat, and using it is up to you. Add `.arena/` to `.gitignore` if you do not want runs to show up in Git. If a run stops, ask Eirene to continue the arena, since its progress is saved in that folder.

## Origin

Arena was made by Jake Schincariol. Eirene ships a copy adapted from [Jakeschincariol/arena-skill](https://github.com/Jakeschincariol/arena-skill), running on Eirene's subagents with a smaller default. `/plugins update arena` fetches the newest copy from [Eirene's repository](https://github.com/0v3rf3ar/Eirene/tree/master/eirene/plugins/arena).
