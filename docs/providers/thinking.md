# Thinking and reasoning

[Documentation](../README.md) / [Providers](README.md) / Thinking and reasoning

Some models can reason before they answer. How you control this depends on the connection.

| Connection | Control |
| --- | --- |
| `ollama-local`, `llamacpp` | `/think` |
| `deepseek`, `chatgpt-plan` | A level chosen per model, through `/connect` or `/model` |

More thinking can change speed, cost and resource use. It does not guarantee a correct answer, enlarge the context window, or add tool calling to a model
that lacks it.

## Local models

The `/think` command is available only while `ollama-local` or `llamacpp` is selected.

```text
/think
/think think
/think nothink
```

With no argument it toggles the setting, and `on` and `off` also work. Thinking is on by default. The choice is saved as `providers.<provider>.think` and
applies to later requests. It does not affect the separate `ollama` connection. The model must support the option for it to have any effect.

On llama.cpp, leaving it on sends nothing, so the server's own `--reasoning` setting decides. Turning it off asks the server to disable reasoning for each request.

## DeepSeek and ChatGPT plan

After you pick a model with `/connect` or `/model`, Eirene asks for a level. The choices come from that model's listing, so you only see supported levels.

| Choice | Effect |
| --- | --- |
| **Model default** | Eirene sends nothing, and the service decides. |
| **Off** (DeepSeek) | Thinking is disabled. |
| A level, such as `low`, `high` or `max` | Thinking is requested at that level. |

Each model's choice is saved separately under `reasoning_efforts`:

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

On DeepSeek, small background requests (titles, summaries, question choices, side questions and suggestions) always run without thinking, so their short
budgets produce text. This does not change your setting.

Reasoning from these models is preserved through tool calls, later turns, resumes and compaction, as the services require.
