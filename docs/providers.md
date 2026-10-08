# Providers and models

[Documentation](README.md) / Providers and models

A provider connects Eirene to a model service or an installed agent CLI. Choose a
connection based on the account or local service you want to use, then select a
model available through that connection.

## Connect and switch

```text
/connect
/connect anthropic
/connect ollama-local
/model
/model MODEL_NAME
```

`/connect` opens the provider picker. Giving a provider name goes directly to that
connection. Eirene validates API connections and offers a model picker; it can
fall back to a bundled model list when a service cannot list models. A model
appearing in a list does not guarantee access under your account.

Saved API credentials are reused when switching. Add `!` to replace saved API
connection settings rather than reuse them:

```text
/connect custom-openai!
```

Enter keys in the hidden credential prompt, rather than in chat. The CLI-backed
providers use their own authentication flow; the suffix does not replace their
account login.

## Available connections

| Name for `/connect` | Connection | What you need |
| --- | --- | --- |
| `chatgpt` | OpenAI API | API key with access to the selected model. |
| `anthropic` | Anthropic API | Anthropic API key. |
| `gemini` | Google Gemini API | Google AI Studio API key. |
| `groq` | Groq API | Groq API key. |
| `deepseek` | DeepSeek API | DeepSeek API key. |
| `kimi` | Moonshot API | Moonshot API key. |
| `ollama` | Ollama hosted API | Ollama API key. |
| `ollama-local` | Local Ollama | Running Ollama service and a downloaded model. |
| `perplexity` | Perplexity search models | Perplexity API key; text responses only. |
| `custom-openai` | OpenAI-compatible endpoint | Base URL and key accepted by that endpoint. |
| `custom-anthropic` | Anthropic-compatible endpoint | Base URL and key accepted by that endpoint. |
| `chatgpt-subscription` | Installed Codex CLI | `codex` on PATH and a supported ChatGPT account login. |
| `claude-code` | Installed Claude Code CLI | `claude` on PATH with its own working login. |
| `omniroute` | OmniRoute gateway | Installed Eirene adapter and a running gateway. |

Common aliases include `openai` or `gpt` for `chatgpt`, `claude` for `anthropic`,
`codex` for `chatgpt-subscription`, `claude-cli` for `claude-code`, `google` for
`gemini`, `moonshot` for `kimi`, and `custom` for `custom-openai`.

## API providers

Eirene manages workspace tools for API providers. A model must support tool
calling to inspect files, edit them, execute commands, or call MCP tools. Text-only
connections can answer questions and follow written guidance, but cannot perform
those actions. The Perplexity connection is explicitly text-only.

Vision also depends on the selected model and endpoint. Ask Eirene to inspect a
local screenshot only when that connection supports images. A compatible API
protocol alone does not guarantee tools, images, or every model parameter.

## Local Ollama

Start Ollama and download a model using your normal Ollama setup. Eirene's local
connection defaults to `http://localhost:11434` and does not require an API key.
Its model picker uses the models available from that service.

A local model's memory requirements, context size, and tool reliability determine
which tasks it can handle. Smaller models receive a compact tool and instruction
set. They still need usable tool calling for workspace work. Use
[`/think`](thinking.md) to change the local thinking option; this does not change
an incapable model into a tool-capable one.

## Custom endpoints

```text
/connect custom-openai
```

Enter the API base URL, ending at `/v1`, and the key expected by the service. Use
`custom-anthropic` for an Anthropic-compatible interface. Eirene uses the selected
protocol; the service must actually implement the required requests and model
behavior. If discovery fails, use `/model MODEL_NAME` with an identifier your
service accepts after establishing the connection.

## Subscription CLI connections

For Codex, `/connect codex` can use an existing ChatGPT login or present browser
and device-code sign-in choices. Eirene displays the URL or code for you to open
and waits for login completion.

For Claude Code, authenticate the `claude` CLI separately first, then use
`/connect claude-code`. Eirene checks that CLI connection and offers its model
choices.

These connections use the CLI's own execution tools, context handling, and
subscription limits. Eirene forwards its approval requests and plugin guidance;
output and feature availability depend on what the installed CLI exposes. See
[platform support](platforms.md) for native Windows behavior.

## OmniRoute

Install the adapter with `/plugins install omniroute`, then use
`/connect omniroute`. The gateway controls provider routing and model combinations.
Chat access and management MCP access are configured separately. Follow the
[OmniRoute guide](omniroute.md).

## Credentials and failures

Keys can be stored in Eirene's configuration or an OS credential store. Environment
variables can override saved provider keys; see [configuration](configuration.md).
Subscription credentials remain with the external CLI.

A rejected key, exhausted quota, inaccessible model, or unsupported endpoint must
be resolved with the provider. Switching models does not increase an account's
quota. See [troubleshooting](troubleshooting.md) for connection and retry behavior.
