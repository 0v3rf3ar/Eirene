# Code review

[Documentation](../README.md) / Guides / Code review

Eirene has two built-in review commands. Both need a Git repository and a connected provider, and
both are read-only: they run temporarily in Plan mode, then restore your mode.

| Command | Looks for |
| --- | --- |
| `/review` | Defects in general: bugs, regressions, races, data loss, and missing validation or tests. |
| `/security-review` | Vulnerabilities a real attacker could use. |

## Choose what to review

With no argument, a review covers your staged, unstaged and untracked changes:

```text
/review
```

Give a Git revision to review everything since your branch split from it, including uncommitted
edits. Newer commits on the base are not counted as yours.

```text
/review main
/review HEAD~1
/security-review main
```

The argument must be a revision, not a path or an instruction. If there is nothing to review, Eirene
says so without calling the model. Finish or stop the current response first.

## Read the findings

Findings come first, ordered by severity. Each has a file and line, the evidence, the impact and a
suggested fix. Suspicions it could not confirm are listed once at the end, under `Not verified`. If
it finds nothing, it says `No findings` and mentions any gaps, such as checks it could not run.

The review changes nothing. Ask for fixes in your next message:

```text
Fix the first finding, add a regression test, and leave the unrelated cleanup alone.
```

## Security reviews

`/security-review` covers injection, access control, secrets and cryptography, web flaws, file and
process handling, dependencies, and untrusted content reaching AI prompts or tools. Each finding
states its category, the attack steps, the impact and a fix. Theoretical issues are left out, and
secrets are never quoted in full.

`No findings` means this pass traced nothing exploitable in these changes. It only looks at changes,
not the whole repository, and is no substitute for a professional audit of a sensitive system.

## How much to rely on a review

- A review runs in one pass and cannot run tests that need writes or arbitrary commands.
- A diff of up to 30,000 characters is sent directly. A larger one is read file by file.
- Git runs with external diff and text-conversion programs turned off, so a repository's own
  configuration cannot run anything during the review.
- Text in the reviewed code is treated as data rather than instructions, but a model can still be
  misled, so read the findings critically.

## Plugin review workflows

| Plugin | Adds |
| --- | --- |
| [PR Review Toolkit](../extending/plugins/pr-review-toolkit.md) | Separate reviews for tests, error handling, comments, types and maintainability. |
| [Ponytail](../extending/plugins/ponytail.md) | Audits for over-engineering and shortcuts. |

Plugin commands follow their own instructions and may edit files. The read-only guarantee applies only
to the built-in commands, so say so if you want a plugin's review to stay read-only.
