# Feature Dev

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / Feature Dev

Feature Dev guides a feature through discovery, codebase exploration, clarification,
architecture, implementation, and review. It is useful when a change needs a clear
understanding of existing behavior before editing.

## Install and start

```text
/plugins install feature-dev
/feature-dev Add CSV export to the invoice list, preserving the active filters and current authorization rules.
```

The canonical command is `/feature-dev:feature-dev`. Git and the project's real
build/test tools are needed for the relevant stages. No executable startup hook
or MCP server is required for the written workflow.

## Guided flow

```text
discover -> explore -> clarify -> compare approaches -> implement -> review -> summarize
```

The workflow first establishes the goal and maps similar code. It asks about
underspecified behavior, compares implementation approaches, and waits for the
relevant decisions before implementation. Include nonnegotiable constraints and
verification requirements in your initial request to reduce avoidable questions.

Implementation follows the agreed approach and uses a progress plan. Review
passes assess the result before the final report, including files changed and
checks performed. A reported review is not a replacement for inspecting the
actual diff or running the required environment checks.

## Specialist profiles

| Profile | Purpose | Main-agent command |
| --- | --- | --- |
| `code-explorer` | Trace existing behavior and identify important files. | `/feature-dev:agent-code-explorer` |
| `code-architect` | Propose approaches and integration boundaries. | `/feature-dev:agent-code-architect` |
| `code-reviewer` | Review correctness, conventions, and maintainability. | `/feature-dev:agent-code-reviewer` |

```text
/feature-dev:agent-code-explorer Trace how filters reach the invoice query and return the key paths. Do not edit.
```

A profile command guides the main agent. Independent exploration or review passes
use [specialist delegation](../specialists.md) where available and consume
additional model usage. API passes use your selected provider/model rather than
upstream model-tier names.

## Plan before edits

For initial exploration, start with `/agents plan` and request analysis only.
Plan mode cannot implement the feature. Switch to Manual or Auto after agreeing
to a design, then explicitly ask to continue with implementation. There is no
automatic permission upgrade because the workflow reached its implementation
stage.

For a skill-by-skill alternative, see [Superpowers](superpowers.md). Eirene's
[session plan](../plans.md) can retain progress across either workflow.

Source: [Anthropic official plugins](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/feature-dev).
