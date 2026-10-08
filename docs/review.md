# Code review

[Documentation](README.md) / Code review

The built-in review command checks Git changes for concrete defects. It works
without an installed review plugin and keeps the review turn read-only.

## Review current changes

```text
/review
```

Eirene inspects staged and unstaged diffs, reads relevant surrounding code, and
looks for actionable bugs, regressions, security problems, races, data loss, and
missing validation or tests. Finish or stop the current response before starting
a review. The workspace must be in a Git repository.

## Compare with a base

```text
/review main
/review HEAD~1
```

The argument is a Git base revision, not a file path or a review instruction.
Choose a revision that exists in the repository. The review uses changes against
that base, which may include more than your currently uncommitted edits.

## Read the findings

Findings appear first, ordered by severity, with a file and line, supporting
evidence, impact, and a suggested fix. If there are no findings, Eirene says
`No findings` and mentions any verification gap.

The review does not automatically edit files or prove every behavior is correct.
Missing dependencies, incomplete context, and checks that could not be run remain
limits on the result. Ask for fixes in a later normal turn if you want changes.

```text
Fix the first finding, add a regression test, and leave the unrelated cleanup alone.
```

## Choose a plugin review workflow

| Workflow | Use it for |
| --- | --- |
| [Code Review](plugins/code-review.md) | GitHub PR review with multiple passes and the upstream commenting workflow. |
| [PR Review Toolkit](plugins/pr-review-toolkit.md) | Specialized reviews of tests, errors, comments, types, and maintainability. |
| [Ponytail](plugins/ponytail.md) | Over-engineering and shortcut audits. |
| [React Best Practices](plugins/react-best-practices.md) | React and Next.js performance issues. |
| [Web Design Guidelines](plugins/web-design-guidelines.md) | Accessibility, usability, and interface quality. |

Plugin commands follow their own written workflow and can include edits or
external actions. The built-in `/review` read-only behavior does not automatically
apply to every plugin command. State the scope you want before invoking one.

## Revision semantics and mode restoration

The built-in handler temporarily sets the agent to Plan mode and restores the
previous mode when the review finishes. Its initial requested commands are
`git status --short`, `git diff`, and `git diff --cached`, or `git diff BASE`
when a base is supplied. This is a comparison with the specified revision,
not an automatic merge-base/three-dot comparison.

Untracked files do not appear in ordinary `git diff`; mention relevant new files
explicitly when they must be included in the review. Base arguments are restricted
to a revision-like character set, rather than accepted as arbitrary shell text.
A review's observations are recorded as a turn in the active session. Runtime
limits still come from [configuration](config-file.md), and tests needing writes
or arbitrary execution can be unavailable in this read-only pass.
