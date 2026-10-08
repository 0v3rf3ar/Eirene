# Code Review plugin

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / Code Review plugin

Code Review adds a GitHub pull-request review workflow with multiple independent
passes and confidence filtering. It differs from Eirene's built-in `/review`,
which reviews local Git changes in a read-only turn.

## Prerequisites and installation

Install Git and GitHub CLI (`gh`) separately, authenticate `gh`, and open the
relevant repository in Eirene.

```text
/plugins install code-review
/plugins doctor code-review
/code-review Review PR 123 and keep the findings in this conversation. Do not post a GitHub comment.
```

The canonical command is `/code-review:code-review`. Supply the PR or clear review
scope. An authenticated CLI still needs account permission to read or comment on
the target repository.

## Review flow

The upstream workflow checks whether the PR is eligible for review, finds relevant
project guidance, summarizes the change, and uses different passes for defects,
instructions, history, previous review context, and code comments. Candidate issues
are checked for confidence, with findings below 80 filtered out.

```text
PR scope -> eligibility -> context -> independent passes -> confidence check -> findings
```

The upstream command also includes posting a result through `gh`. State explicitly
if you want local findings only, or if you are requesting a posted review. Posting
is an external action subject to your task and normal execution policy. Installation
does not itself authorize comments on GitHub.

## Provider behavior

On API connections, Eirene uses the selected provider and model for independent
passes rather than routing upstream model-tier references to Claude. On native
CLIs, delegation uses their available mechanism or an explicit sequential fallback.
See [specialists](../specialists.md).

Multiple passes cost more model usage and can still miss defects or produce false
positives. Confidence is a workflow score, not a measured probability. This review
workflow does not replace CI; upstream guidance focuses on review findings rather
than running a build and type checker as its primary step.

Use [built-in review](../review.md) for working-tree checks or
[PR Review Toolkit](pr-review-toolkit.md) for tests, errors, types, and other
focused concerns.

Source: [Anthropic official plugins](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/code-review).
