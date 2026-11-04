# Context and usage

[Documentation](../README.md) / Guides / Context and usage

Every model has a limit on how much text it can consider at once: its context window. The conversation,
project instructions, enabled skills and tool definitions all count towards it. This page explains how
Eirene keeps long sessions inside that limit and how to see what they use.

## Compaction

When a conversation grows too large, Eirene replaces its older part with a summary so work can continue.
This is called compaction. Automatic compaction is on by default for connections where Eirene runs the
agent loop. To do it yourself, wait for the current response to finish and run:

```text
/compact
```

Eirene reports the approximate context size before and after, and shows a preview of the summary. A small
progress panel appears above the input while it works.

### What is kept

| Kept in the model's context | Kept only on disk |
| --- | --- |
| A summary of earlier requests, decisions and progress | The original messages, in the session log |
| A factual record of recent tool results, kept separately from the summary | The full earlier context, as a saved output |
| Your latest request, word for word | |
| The last few messages, with their tool calls complete | |

Compaction is one extra model request and can lose detail, so restate an exact requirement if it still
matters, or point to a file. It does not undo edits or rerun commands. You can still scroll through the old
messages, even though the model now sees only the summary.

It needs at least three messages. Summarizing has a 60-second limit. If it fails, automatic compaction falls
back to quoting your earlier instructions, while `/compact` reports the failure.

### When it runs

Eirene checks the budget before every model request, including those after tool calls:

1. It reserves room for the reply, then caps input at a share of the context window: 80% for most providers,
   and 95% by default for ChatGPT plan connections.
2. If `context_warning` is set to a positive number, that lowers the cap further.
3. Above the cap, it compacts down to about 65% of the budget for history, or higher if the latest request needs
   more room.

With `auto_compact` set to `false`, Eirene skips compacting early but still compacts when a request would not
otherwise fit. The session can continue indefinitely; the context limit only recycles older history.

Above 85% of a known window, an indicator appears above the input, such as
`context ~86% · 430k / 500k`.

Codex and Claude Code connections manage context themselves. See
[External CLI connections](#external-cli-connections).

## Set context limits

Eirene normally learns each model's capacity from the provider. You can override it in
[`config.json`](../reference/configuration.md). Merge these fields into the file with Eirene closed:

```json
{
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
    "ollama-local": {
      "model_context_limits": {"your-local-model:tag": 65536}
    }
  }
}
```

Eirene uses the first of these that applies:

1. `providers.<provider>.model_context_limits`: one model on one provider.
2. `model_context_limits`: one model on any provider.
3. `providers.<provider>.context_limit`: every model on one provider.
4. The capacity the provider advertises, or Eirene's built-in value.
5. If none is known, a 60,000-token input threshold.

Values are token counts. Model IDs must match exactly, including any slashes or colons, and wildcards are not
supported. Setting a limit only changes how Eirene budgets; it cannot enlarge what the model really supports,
and a local Ollama or llama.cpp model can impose a smaller limit of its own.

ChatGPT plan connections use the capacity from their model catalog. Without one, they fall back to 500,000
tokens for every model, which is an operational default and not a statement about a model's real capacity.

### External CLI connections

- **Codex** (`chatgpt-subscription`): Eirene forwards your configured capacity and a positive `context_warning`
  to Codex. Without them, Codex uses its own defaults.
- **Claude Code**: Claude Code compacts on its own. These settings only affect the summary that `/compact`
  produces.

## Recaps

In a long chat, Eirene shows a one-line recap so you can pick the thread back up:

```text
※ recap: You're adding CSV export; the endpoint and tests are done. Next, wire up the button. (/recap off to disable)
```

A recap appears after a turn once the transcript has grown by about two screen heights since the last one. Each
is one extra model request. It is only displayed and never joins the conversation, so it uses no context. Starting
a new turn before it is ready skips it.

Run `/recap` to choose, or `/recap on` and `/recap off` directly.

## See your usage

```text
/usage
```

This shows input and output token totals, the number of turns, the estimated conversation size, elapsed time, a
per-model breakdown and the session ID.

Token counts reported by a provider are accurate; the context size is an estimate, at roughly one token per four
characters. CLI connections and side requests may report less. For billing, trust your provider's dashboard.

Totals are kept in memory and reset when you switch sessions.

### Estimate cost

Eirene does not know every provider's prices. To see an estimated cost, add your model's rates, in US dollars per
million tokens:

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

These numbers only illustrate the format. If any model used in the session has no rate, the estimate is unavailable.
Subscriptions, caching and discounts can all make your real bill differ.

## Use less context

- Name the relevant paths, and ask for the part of a log around the error instead of all of it.
- Keep [project instructions](project-instructions.md) short.
- Turn off [skills](../extending/skills.md) and [plugins](../extending/plugins.md) you are not using.
- With a local model, read about [context shifting](context-shifting.md), which adapts to smaller windows.
