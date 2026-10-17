# Context and usage

[Documentation](README.md) / Context and usage

The conversation, project guidance, enabled skills, and tool information all
consume model context. Long transcripts and large outputs can leave less room
for the next request. Eirene uses bounded reads and summaries to keep ongoing
work manageable.

See [dynamic context shifting](context-shifting.md) for the request flow,
adaptive local-model profiles, budget calculation, and execution handoff.

## Compact a conversation

```text
/compact
```

Wait for the current response to finish before compacting. Eirene asks the active
model to summarize the conversation, reports approximate context before and
after, and shows a short summary preview. The summary is meant to preserve the
current task, decisions, and action evidence while reducing active context.
The terminal shows a short, visible activity bar and stage labels during manual
and automatic compaction. The bar stays in a small panel above the input rather
than stretching across the screen or scrolling away with the transcript.
It is indeterminate while waiting for
the model. It disappears on completion, failure, or cancellation.

Compaction makes an additional model request. It can lose detail; restate an
exact requirement or point to a file when it remains important. It does not undo
edits or rerun commands. Export a transcript beforehand when you need a separate
record of the conversation.

Automatic compaction is enabled by default for Eirene-managed API conversations.
Context budgeting considers the selected model, tools, and configured limits.
Native CLI connections manage their own context and may differ in how summaries
and limits behave.

### Configure any provider and model

Merge settings into your existing configuration, then restart Eirene. The file
is `~/.local/share/eirene/config.json` by default on Linux/macOS, and
`%USERPROFILE%\.local\share\eirene\config.json` on Windows. If `EIRENE_HOME` is set,
edit `config.json` inside that directory instead. Keep existing credentials and
provider entries; the examples below are partial configurations.

Use the exact provider key shown by `/connect` and the exact model identifier
selected with `/model`. A global `model_context_limits` entry applies to that
model on every provider. To set different limits for the same model on different
services, put `model_context_limits` inside each provider's entry:

```json
{
  "auto_compact": true,
  "context_warning": 0,
  "model_context_limits": {
    "your-shared-model-id": 128000
  },
  "providers": {
    "chatgpt-plan": {
      "context_limit": 500000
    },
    "custom-openai": {
      "model_context_limits": {"your-shared-model-id": 256000}
    },
    "anthropic": {
      "model_context_limits": {"your-claude-model-id": 200000}
    },
    "gemini": {
      "model_context_limits": {"your-gemini-model-id": 1000000}
    },
    "ollama-local": {
      "model_context_limits": {"your-local-model:tag": 65536}
    }
  }
}
```

These are token counts, not character counts or subscription usage allowances.
The non-ChatGPT numbers illustrate the configuration format; use the capacity
your actual service supports. Exact identifiers can contain slashes or colons;
keep the full identifier as the JSON key. Wildcards are not supported.
Positive integers are accepted; invalid values are ignored.

`providers.<provider>.context_limit` sets one context limit for **all models**
on that provider, including models added later. The ChatGPT example above
therefore applies to every ChatGPT plan model. Specific model entries can
override it.

Resolution order is provider/model override, global model override, provider-wide
`context_limit`, then provider-advertised or built-in capacity. Local Ollama may impose a smaller
effective capacity based on the model and hardware.

`context_warning: 0` selects an automatic threshold based on model capacity.
Set a positive number, such as `200000`, to compact earlier across managed
providers. `max_tokens` reserves room for each reply; it is separate from the
context window. For unknown providers/models with no configured or advertised
capacity, Eirene uses a 60000-token input threshold. `auto_compact: false`
disables proactive shrinking; required compaction still runs before a request
would exceed the available context. A context limit recycles older history,
rather than limiting the duration of a session.

API providers, including custom compatible endpoints, use these settings in
Eirene's automatic and manual compaction. For `chatgpt-subscription` (Codex),
Eirene forwards configured capacity and a positive `context_warning` to Codex's
`model_context_window` and `model_auto_compact_token_limit`; Codex retains its
own defaults when these are unset. Claude Code owns its live context and uses
its native automatic compaction; these settings budget Eirene's `/compact`
summary but cannot change Claude Code's internal context capacity.

### ChatGPT plan defaults

ChatGPT plan connections prefer the model catalog's advertised capacity.
Without it, Eirene uses the same **500000-token operational default for every
ChatGPT plan model**, including future models. This is a shared application
default rather than a claim that every model supports that capacity. An
advertised capacity takes precedence over the built-in default. Explicit
configuration overrides both; use a smaller per-model entry when needed.

Eirene checks context before each model request, including requests after tool
calls. ChatGPT plan input uses the catalog's effective-context percentage,
defaulting to 95% like Codex; other managed providers use 80%. Eirene also
reserves `max_tokens` plus overhead. It normally compacts to 65% of the remaining
history budget, raising that target when needed to preserve the latest request, leaving room for
more work. Large transcripts are summarised in bounded chunks. The latest
request, recent complete tool exchanges, and execution evidence are preserved;
earlier history remains in the session log and an output artifact. These are
local summaries; they do not require a server compaction endpoint.

Above 85% of a known context window, a right-aligned indicator appears directly
above the input, for example `context ~86% · 430k / 500k`. It disappears when
usage drops after compaction. The count includes estimated history and the
instruction/tool overhead from the latest budget calculation. Local models use
their effective model/hardware window; a large configured number does not
override local context shifting. Counts are approximate, not subscription usage.

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

## Budget calculation and persistence

For managed providers, the budget considers the estimated history, system
instructions, and serialized tool schemas. A configured exact-model limit or
local Ollama effective limit or ChatGPT plan catalog supplies the context boundary.
The runtime reserves response tokens and overhead, caps input at the effective
percentage of known capacity, then applies a positive `context_warning`. The
[configuration reference](config-file.md#context-limits-and-cost-rates) documents
the arithmetic and numeric ranges. `context_warning: 0` selects model-aware
budgeting; it does not disable compaction.

The token estimator uses roughly one token per four characters and also counts
tool arguments. It is not a provider tokenizer. Large catalogs, project guidance,
and output can consume budget before the conversational text becomes large.
Older history is compacted before an over-budget request. The session continues
afterward; only a request whose current instructions or required memory cannot
fit the available window needs a smaller request or a larger supported window.

Compaction requires at least three messages. It requests a bounded summary with
a 60-second overall summarization wait, keeps a safe recent tail of roughly four
messages, and preserves a bounded execution-memory block based on actual tool
observations. Earlier message JSON is also saved as an output artifact. Automatic
compaction can fall back to quoted earlier instructions if summarization fails;
manual compaction reports the failure instead.
Small local windows can shorten the handoff prose while retaining the latest
request verbatim and a reference to the saved evidence. Local profile selection,
response reserves, bounded reads, and Ollama's `num_ctx` remain in force.

The session log appends a `compact` record rather than deleting its earlier
records. Active context is rebuilt from that replacement history, while the UI
can still replay earlier transcript content. JSON/Markdown session exports use
active context, not the entire raw log. See [session formats](sessions.md#event-log-format).
Usage counters are held in memory and reset on session switching; they are not
restored as historical billing totals from JSONL.
