# Fast mode

[Documentation](../README.md) / [Providers](README.md) / Fast mode

Fast mode runs the same model on its provider's faster serving tier. The model and its abilities stay the same; output arrives sooner and costs more per token.
It suits interactive work where waiting matters more than price. Leave it off for long autonomous or cost-sensitive runs.

```text
/fast
/fast on
/fast off
/fast status
```

`/fast` alone opens an On/Off menu. The choice is saved as `fast_mode` and applies from the next request, even during a running turn. While it is active, the mode
line ends with `· fast`.

## Where it is available

`/fast` is listed in the `/` menu and in `/help` only while the current model has a fast tier. If you type `/fast on` on another model, Eirene names the models that
do. `/fast off` always works. A saved choice sends nothing on a model without a tier, and takes effect again when you switch back to one that has it.

| Provider | Models | What Eirene sends |
| --- | --- | --- |
| Anthropic | Claude Opus 5.5, Opus 5 and Opus 4.8 on `api.anthropic.com` | `speed: "fast"`, plus the `fast-mode-2026-02-01` beta header for Opus 5 and 4.8 |
| Claude Code | `opus` | Claude Code's `fastMode` setting. Billed to usage credits, not plan limits. |
| OpenAI API | GPT-5 and GPT-6 models, GPT-4.1, GPT-4o, o3, o4-mini | `service_tier: "priority"` |
| ChatGPT plan | Models the plan's catalog lists with a Fast tier | `service_tier: "priority"` |
| Codex | Models the Codex app server lists with a Fast tier | That tier, on each turn |

For ChatGPT and Codex, the tier comes from the model catalog, so `/fast` appears once the catalog has been read after you connect or change model.

Custom endpoints, Gemini, Ollama, DeepSeek and the other providers have no fast tier.

## Cost

Each provider bills fast requests at its own higher rate, so check its pricing page. Fast and standard requests use separate prompt caches, which means the first fast
request in a long conversation re-reads the whole context uncached. Turning fast mode on at the start of a session is therefore the cheapest way to use it.

## Rate limits

Anthropic's fast tier has its own rate limit. When it is reached, Eirene repeats the request at standard speed, tells you once, and shows `· fast (cooling down)` in the
mode line. Fast mode resumes after the provider's `retry-after` delay, or one minute if none is given. Running `/fast` again ends the cooldown early.

OpenAI's fast tier shares the model's normal rate limit, so ordinary retries apply.
