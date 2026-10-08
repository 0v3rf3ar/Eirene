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
