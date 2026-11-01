# Fast mode

[Documentation](README.md) / Fast mode

Fast mode runs the same model on its provider's faster serving tier. Quality and
capabilities do not change; output arrives sooner and costs more per token. Use it
for interactive work where waiting matters more than price, and turn it off for
long autonomous or cost-sensitive runs.

```text
/fast            pick On or Off from the menu
/fast on
/fast off
/fast status
```

The choice is saved as `fast_mode` in `config.json` and applies from the next
request, including during a running turn. While it is in effect the mode line
under the input ends with `· fast`.

## Where it works

`/fast` appears in the `/` menu and `/help` only while the current model has a
fast tier. Typed anyway, `/fast on` names the models that do; `/fast off` always
works. A saved choice survives switching to a model without a tier: it sends
nothing there and comes back into effect when you switch to one that has it.
For Codex and ChatGPT the tier comes from the model catalog, so `/fast` shows up
once that list has been read after connecting or changing model.

| Provider | Models | What Eirene sends |
| --- | --- | --- |
| Anthropic (Claude) | Claude Opus 5.5, Opus 5, Opus 4.8 on `api.anthropic.com` | `speed: "fast"`; Opus 5 and 4.8 also need the `fast-mode-2026-02-01` beta header, which Eirene adds |
| Claude Code (headless) | `opus` | Claude Code's own `fastMode` setting; billed to usage credits, not plan limits |
| OpenAI (API) | GPT-5 and GPT-6 models, GPT-4.1, GPT-4o, o3, o4-mini | `service_tier: "priority"` (OpenAI's Fast mode, formerly Priority processing) |
| ChatGPT | Models the plan's catalog lists with a Fast tier | That tier, `service_tier: "priority"` |
| Codex (headless) | Models `codex app-server` lists with a Fast tier | That tier, per turn (`serviceTierForTurn`) |

Custom Anthropic- or OpenAI-compatible endpoints, Gemini, Ollama, DeepSeek and the
other providers have no fast tier, so `/fast` is not listed for them.

## Cost

Each provider bills fast requests at its own higher rate; see its pricing page.
Fast and standard requests keep separate prompt caches, so the first fast request
in a long conversation re-reads the whole context uncached. Turning fast mode on
at the start of a session is cheapest.

## Rate limits

Anthropic's fast tier has its own rate limit. When it is reached, Eirene repeats
the request at standard speed, says so once, shows `· fast (cooling down)` in the
mode line, and returns to fast after the provider's `retry-after` delay (one
minute when none is given). Standard requests are not slowed by a fast limit.
Running `/fast` again ends the cooldown early. OpenAI's fast tier shares the
model's normal rate limit, so ordinary retries apply.
