# DeepSeek integration and compatibility audit

[Documentation](README.md) / [Providers](providers.md) / DeepSeek

Reviewed against the official API documentation and live service on 2026-10-19.
Eirene uses Chat Completions for `/connect deepseek`; Eirene runs workspace,
browser, search, plugin and MCP tools locally under its normal permissions.

## Models, thinking and limits

The current fallback models are `deepseek-flash` and `deepseek-v4-pro`. Live
`/models` metadata supplies context capacity, output capacity, input modalities
and available thinking efforts. Discovery failure retains the documented
fallbacks; authentication errors still surface. See the
[model API](https://api-docs.deepseek.com/api/list-models/).

`/connect deepseek` and `/model` offer model-default thinking, off, and supported
effort levels. Choices are saved per model in
`providers.deepseek.reasoning_efforts`. For example:

```json
{
  "providers": {
    "deepseek": {
      "reasoning_efforts": {
        "deepseek-flash": "high",
        "deepseek-v4-pro": "max"
      }
    }
  }
}
```

The default leaves the server's choice unchanged. Off sends disabled thinking.
Explicit efforts enable thinking. Titles, compaction summaries, question choices,
side conversations and prompt suggestions use isolated non-thinking requests so
their small output budgets produce text; this does not change the main setting.
See [thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/).

Context budgeting uses discovered capacity, with existing configured overrides
taking precedence. The current fallback capacity is 1048576 tokens for the
current models. Output is capped by the discovered maximum, falling back to
393216 tokens. The default output request remains 16384. Context token counts
remain estimates; preserved reasoning and attached images count toward them.

## Conversations, tools and failures

Original model reasoning is preserved through tool loops, later turns, session
resume, compaction tails and JSON transfer. Assistant messages without original
reasoning receive an empty field on the wire. This does not reconstruct reasoning
that an old client discarded.

DeepSeek documents that Chat Completions cannot insert client-generated tool
calls. Eirene converts its automatic background-process poll/result pairs to
labeled observations in the request, including pairs in old logs. Actual model
tool calls and raw session files remain intact. Long or otherwise incompatible
MCP names receive deterministic wire aliases and map back before dispatch.
See [tool calls](https://api-docs.deepseek.com/guides/tool_calls/).

Stream handling covers keep-alive comments, empty deltas, split reasoning,
interleaved parallel call arguments, and usage on the terminal content chunk.
A terminal finish reason is required. Truncated, filtered, aborted, or
resource-interrupted responses cannot release tools. Complete calls require
valid object arguments and unique, nonempty IDs; malformed JSON is not repaired
into an executable DeepSeek call. Ordinary argument validation and approvals
still apply. See the [chat API](https://api-docs.deepseek.com/api/create-chat-completion/).

HTTP 400/422 request errors, 401 authentication failures, and 402 balance
failures stop the request. HTTP 429 and server failures are eligible for existing
bounded retries and shared cooldowns. Retries do not restart a response after
text or reasoning has already been shown. Cancellation closes the stream.
See [errors](https://api-docs.deepseek.com/quick_start/error_codes/) and
[keep-alive and rate limits](https://api-docs.deepseek.com/quick_start/rate_limit/).

## Images and usage

Flash accepts inline JPEG, PNG, GIF and WebP images. Pro is text-only according
to the current catalog. Image tools on Pro return feedback without inserting an
unsupported image into the conversation. Switching to Pro with existing image
history produces a local diagnostic. Request size, image count, format and
dimensions are checked before sending. Eirene's own attachment/file limits also
apply. See [vision](https://api-docs.deepseek.com/guides/vision/).

`/usage` counts the API's complete input/output totals; cached input and reasoning
are already included in those totals and are not added twice. Eirene does not
currently retain separate cache-hit/miss or reasoning-token counters. Configured
cost estimates are not exact billing: DeepSeek prices vary with caching and time.
See [caching](https://api-docs.deepseek.com/guides/kv_cache/) and
[pricing](https://api-docs.deepseek.com/quick_start/pricing/).

## Other API surfaces reviewed

These are separate DeepSeek facilities, not additional features enabled by the
Eirene DeepSeek connection:

| API surface | Eirene behavior |
| --- | --- |
| [JSON mode](https://api-docs.deepseek.com/guides/json_mode/) | No forced `response_format`; normal text and local structured tool arguments are used. |
| [Strict tools](https://api-docs.deepseek.com/guides/tool_calls/), [prefix completion](https://api-docs.deepseek.com/guides/chat_prefix_completion/) | Beta strict schemas and assistant prefix continuation are not enabled. Optional tool parameters remain optional; local validation applies. |
| [FIM](https://api-docs.deepseek.com/api/create-completion/) | No FIM/autocomplete endpoint; file editing uses Eirene tools. |
| [Files](https://api-docs.deepseek.com/guides/files_api/) | Local attachments and inline images are used. No remote upload, remote file management or automatic Files API fallback for oversized images. |
| [Balance](https://api-docs.deepseek.com/api/get-user-balance/) | Balance errors are handled; there is no account-balance dashboard. |
| [Search and Fetch](https://api-docs.deepseek.com/guides/search/) | Eirene's existing web tools run independently; no automatic use of these separately billed DeepSeek endpoints. |
| [Responses](https://api-docs.deepseek.com/guides/responses_api/) | Not the protocol for `/connect deepseek`. No assumption of server-side response storage, encrypted reasoning or hosted tools. |
| [Anthropic compatibility](https://api-docs.deepseek.com/guides/anthropic_api/) | Separate custom-provider route, not covered by the native DeepSeek adapter's live checks. |
| Sampling, log probabilities, stop sequences, user isolation | No product controls for these optional request fields; the adapter leaves them unset. |

## Verification and limits of evidence

`tests/test_deepseek.py` exercises current and changed model metadata, output
budgets, reasoning choices and persistence, isolated requests, documented errors,
stream interruptions and malformed tools, images, MCP aliases and background
history. Shared provider, session, compaction and agent suites cover the remaining
lifecycle paths.

Fourteen live checks passed: model discovery, off/low/high/max requests on both
current models, a real harmless function-call round trip with reasoning replay
on each model, Flash vision, existing saved history, and isolated small-budget
text generation. These checks did not execute model-requested workspace actions.
Two additional live checks ran the final frozen executable in an isolated
temporary workspace: a real file read and shell command through the agent loop,
then a second turn resuming its saved conversation. Both passed, as did frozen
startup/UI smoke checks.

The full repository suite passed 2021 tests with 17 skips. After the final stream
and MCP changes, all 366 affected provider, agent, context, attachment, session
and configuration tests passed, including 38 DeepSeek-specific cases. Ruff and
diff-whitespace checks passed. No deliberate rate-limit, balance-exhaustion or
maximum-context calls were made.

This is evidence for the native integration on the reviewed service version,
not certification of every possible prompt, MCP server, outage, account limit,
future model, or optional API surface. Mock tests cover failure conditions without
deliberately exhausting account balance, rate limits or maximum context.
