# Context and usage

[Documentation](README.md) / Context and usage

The conversation, project guidance, enabled skills, and tool information all
consume model context. Long transcripts and large outputs can leave less room
for the next request. Eirene uses bounded reads and summaries to keep ongoing
work manageable.

## Compact a conversation

```text
/compact
```

Wait for the current response to finish before compacting. Eirene asks the active
model to summarize the conversation, reports approximate context before and
after, and shows a short summary preview. The summary is meant to preserve the
current task, decisions, and action evidence while reducing active context.

Compaction makes an additional model request. It can lose detail; restate an
exact requirement or point to a file when it remains important. It does not undo
edits or rerun commands. Export a transcript beforehand when you need a separate
record of the conversation.

Automatic compaction is enabled by default for Eirene-managed API conversations.
Context budgeting considers the selected model, tools, and configured limits.
Native CLI connections manage their own context and may differ in how summaries
and limits behave.

## Inspect usage

```text
/usage
```

The dashboard shows input and output token totals, the number of recorded turns,
an estimate of current conversation size, elapsed session time, and a per-model
breakdown. It also displays the session ID for exports and resumes.

Counts supplied by a provider are more precise than estimates. The current
context display is approximate and does not reproduce the provider's full
billing calculation. CLI connections and auxiliary requests may expose different
usage information; use the service's own dashboard for authoritative billing.

## Configure a cost estimate

Eirene does not assume a price for every provider. Add your model's rates to
`model_costs` in [configuration](configuration.md):

```json
{
  "model_costs": {
    "your-model-id": {
      "input_per_million": 1.25,
      "output_per_million": 5.00
    }
  }
}
```

These numbers illustrate the format, not a service's current prices. Use the
model identifier exactly as Eirene records it. If any model used in the session
has no configured rate, the estimated cost is unavailable. Subscription plans,
cache pricing, and provider discounts can make a simple token estimate differ
from the actual charge.

## Keep requests focused

Name relevant paths, ask for the error range rather than an entire log, and use
[project instructions](project-instructions.md) for concise recurring rules.
Disable irrelevant [skills](skills.md) or plugin bundles. For a local model, use a
context limit that fits the model and available memory; a larger configured number
does not increase the model's supported context.
