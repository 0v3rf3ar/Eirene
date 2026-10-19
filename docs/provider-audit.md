# Provider communication audit

[Documentation](README.md) / [Providers](providers.md) / Communication audit

Audited on 2026-10-19. This records the scope and evidence of the audit; it is
not a guarantee against service outages, account restrictions, model changes,
or incompatible third-party endpoints.

## Connections checked

Every registered connection was inspected, including shared adapters and their
provider-specific settings. HTTP protocol checks use deterministic mock
responses. CLI checks use local fake executables to exercise JSONL events,
approvals, cancellation, and errors. Live checks are listed separately.

| Connection | Official protocol reference | Result and live coverage |
| --- | --- | --- |
| OpenAI API (`chatgpt`) | [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) | Fixed completion-token parameter; mock streaming/tool/auth/error coverage. No API credential available for live inference. |
| ChatGPT plan (`chatgpt-plan`) | [Sign in with ChatGPT](https://developers.openai.com/siwc), [Responses](https://developers.openai.com/api/reference/resources/responses/methods/create) | Live catalog and synthetic tool round trip passed. Response items and encrypted reasoning persist through sessions and JSON import. |
| Codex CLI (`chatgpt-subscription`) | [App Server](https://developers.openai.com/codex/app-server), [ChatGPT integration](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) | Live account/catalog and text inference passed. Mock lifecycle, permissions, tool events, retries, cancellation, and failure coverage. |
| Anthropic (`anthropic`) | [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming), [Models](https://platform.claude.com/docs/en/api/models/list) | Fixed signed/redacted thinking history, initial tool input, completion handling, and model pagination. No live API credential. |
| Claude Code (`claude-code`) | [CLI reference](https://code.claude.com/docs/en/cli-reference) | Fake-CLI tests cover its integration. Manual mode now uses the older-compatible `default` spelling. Executable absent locally; no live check. |
| Gemini (`gemini`) | [Thought signatures](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures), [Models](https://ai.google.dev/api/models) | Live catalog and signed tool round trip passed. Fixed completion/truncation handling and model pagination; signed parts survive session resume/export/import. |
| Groq (`groq`) | [OpenAI compatibility](https://console.groq.com/docs/openai), [API](https://console.groq.com/docs/api-reference) | Mock token-limit, streaming, tool, usage, and authorization coverage. No live API credential. |
| DeepSeek (`deepseek`) | [Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/) | Fixed reasoning-content replay for tool loops and later turns. Mock coverage; no live API credential. |
| Kimi (`kimi`) | [Thinking models](https://platform.kimi.ai/docs/guide/use-thinking-models) | Fixed reasoning-content replay for tool loops and later turns. Mock coverage; no live API credential. |
| Ollama cloud (`ollama`) | [Chat](https://docs.ollama.com/api/chat), [Tools](https://docs.ollama.com/capabilities/tool-calling) | Fixed thinking history and image forwarding. Mock NDJSON/tool/usage/error coverage. No live hosted credential. |
| Local Ollama (`ollama-local`) | [Thinking](https://docs.ollama.com/capabilities/thinking), [Vision](https://docs.ollama.com/capabilities/vision) | Same wire fixes, plus existing local context/profile checks. Live model discovery failed; local inference remains unverified. |
| Perplexity (`perplexity`) | [Sonar migration and compatibility](https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview) | Mock text streaming and disabled-workspace-tool coverage. Existing synchronous/streaming Sonar compatibility retained; no live credential. |
| OmniRoute (`omniroute`) | [Gateway API](https://github.com/diegosouzapw/OmniRoute/blob/main/docs/reference/API_REFERENCE.md) | Shared OpenAI adapter fixes apply; mock catalog/routing/tool round-trip coverage. No running gateway verified. |
| Custom OpenAI (`custom-openai`) | [Baseline protocol](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) | Mock baseline and reasoning replay coverage. Each deployed endpoint's extensions and model capabilities require its own live check. |
| Custom Anthropic (`custom-anthropic`) | [Baseline protocol](https://platform.claude.com/docs/en/build-with-claude/streaming) | Shared Anthropic fixes apply. Mock baseline coverage; deployment-specific behavior is unverified. |

## Corrections made

- OpenAI API uses `max_completion_tokens`; other services retain their supported
  token field, including Groq's existing completion-token field.
- DeepSeek, Kimi, compatible custom endpoints, and OmniRoute retain received
  `reasoning_content`. Standard OpenAI/Groq/Perplexity requests do not receive
  that extension. Ollama receives its native `thinking` field.
- Anthropic preserves response block order, signed thinking, redacted thinking,
  streamed text, and tool inputs. Blocks persist through save/resume and JSON
  export/import.
- OpenAI-compatible, Anthropic, and Gemini adapters require a completion marker
  before releasing tool calls. Length-limit responses retain their stop reason
  so the agent's existing truncation guard can prevent execution. Filtered
  OpenAI and Gemini responses do not release tool calls.
- Shared SSE parsing handles multi-line event data. Gemini and Anthropic model
  discovery follow their next-page tokens.
- Host-generated calls such as automatic background `poll_process` events, and
  imported tool history without original Gemini parts, use Google's documented
  client-call signature sentinel. Real Gemini parts are returned unchanged,
  including unsigned secondary calls in parallel responses. This covers the
  background-command failure observed in session `a7995d56`.
- Ollama forwards attached images as base64 `images` entries.
- Context estimates include preserved provider reasoning and signed blocks.
  An output reserve larger than a small model's context window no longer
  disables its context warning.
- Claude Code's final aggregate token usage is forwarded instead of relying
  only on the per-request usage events from its internal model rounds.
- JSON session import retains Responses items as well as the other provider
  metadata. A factory integration fixture now supplies actual Responses events
  and mock OAuth for the direct ChatGPT connection.

## Validation and limits

After the connection-pooling, shared-rate-limit, session-index, preflight, and
popup changes, the full suite passed **1,977 tests**, with **17 skips**. Additional
final runtime checks (including staggered cooldown recovery and active stream
cancellation) passed. Lint and `git diff --check` passed.

`tests/test_provider_runtime.py` checks pool ownership, credential-scoped request
limits, shared cooldowns, cancellation, and local validation. Session-index tests
check warm-cache reuse and source-log changes. Popup tests exercise checkout to a
child and back to its mother, Escape during active work, and plugin catalog
installation and toggling. The combined provider workflow test exercises
compaction, session reopening, switching providers, and returning to Gemini while
retaining original signed tool parts.

A synthetic benchmark with 300 sessions (80 messages each) measured an uncached
metadata scan at 61.86 ms and the median of five warm index reads at 3.03 ms,
about 20.4 times faster for that workload. This measures metadata browsing, not
model response speed. HTTP pool lifetime follows [HTTPX's async-client guidance](https://www.python-httpx.org/async/).

Regression checks are in `tests/test_provider_audit.py` and the existing provider,
CLI, ChatGPT authentication, session, and agent suites. Live tests used synthetic
status data; they did not ask models to modify the project. Credentials and
response signatures are not included in this report.

Model catalogs are not entitlement checks. Bundled lists remain fallbacks, and
an account can reject an otherwise valid model ID. Tool and image support vary
by model. Eirene's Perplexity adapter intentionally exposes text responses only;
this audit does not add Perplexity's newer Agent API features. Perplexity's
official migration guide says existing synchronous and streaming Sonar requests
continue through compatibility handling.

A previous session that lost required signatures or reasoning cannot have the
original metadata reconstructed. Start a new conversation if old history still
fails validation after upgrading. Native CLI delegation and integrations remain
subject to the installed CLI version and its own capabilities.

The live checks cover connection basics and one tool loop where available, not
every model, modality, rate-limit condition, or third-party MCP server. Mock
coverage cannot establish live service availability. Additional accounts and a
running local service are required to complete those remaining live checks.
