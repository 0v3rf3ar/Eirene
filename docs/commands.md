# Command reference

[Documentation](README.md) / Command reference

Enter slash commands in Eirene's prompt. Type `/` to open completion or use
`/help` for the command list. A command that opens a picker expects you to select
an item there; it does not automatically accept a name as an argument.

## Connections and access

| Command | Action | Guide |
| --- | --- | --- |
| `/connect [provider]` | Connect or switch provider; append `!` to replace saved API settings. | [Providers](providers.md) |
| `/model [name]` | Pick or set a model for the active provider. | [Providers](providers.md) |
| `/think [think\|nothink]` | Toggle or set thinking for local Ollama only. | [Thinking](thinking.md) |
| `/agents [auto\|manual\|plan]` | Pick or set the working mode. | [Permissions](harness.md) |
| `/agents list` | List enabled plugin specialist profiles. | [Specialists](specialists.md) |
| `/permissions [sandboxed\|full-access]` | Change host access for this Eirene process. | [Permissions](harness.md) |
| `/sandbox` | Show execution isolation and workspace status. | [Platforms](platforms.md) |

## Project work and conversation

| Command | Action | Guide |
| --- | --- | --- |
| `/review [base]` | Read-only review of working changes, or changes against a Git revision. | [Review](review.md) |
| `/plan` | Show the saved session plan. | [Plans](plans.md) |
| `/plan clear` | Clear that plan after confirmation. | [Plans](plans.md) |
| `/sessions` | Pick a session in the current workspace. | [Sessions](sessions.md) |
| `/sessions search TEXT` | Find sessions matching text. | [Sessions](sessions.md) |
| `/sessions export ID PATH` | Export to Markdown, or JSON when the path ends in `.json`. | [Sessions](sessions.md) |
| `/sessions import PATH` | Import an exported JSON session. | [Sessions](sessions.md) |
| `/compact` | Summarize a long conversation to reduce active context. | [Context](context-and-usage.md) |
| `/clear` | Clear the current conversation, plan, and usage counters. | [Sessions](sessions.md) |
| `/btw QUESTION` | Ask a side question that is not saved in the session. | [Side questions](side-questions.md) |
| `/usage` | Show token totals, context estimate, model breakdown, and configured cost estimate. | [Usage](context-and-usage.md) |

## Skills, plugins, and external tools

| Command | Action | Guide |
| --- | --- | --- |
| `/skills` | Enable or disable individual Markdown skills. | [Skills](skills.md) |
| `/plugins` | Enable or disable installed bundles. | [Plugins](plugins.md) |
| `/plugins browse` | List named installation shortcuts. | [Catalog](plugin-catalog.md) |
| `/plugins install SOURCE` | Install a shortcut, GitHub bundle, or local directory. | [Plugins](plugins.md) |
| `/plugins inspect NAME` | Show imported commands, dependencies, and compatibility notes. | [Plugins](plugins.md) |
| `/plugins doctor [NAME]` | Check prerequisites and activation without executing the plugin. | [Troubleshooting](troubleshooting.md) |
| `/plugins trust NAME` | Allow hook execution after confirmation. | [Plugins](plugins.md) |
| `/plugins untrust NAME` | Revoke hook trust and disable the plugin's MCP servers. | [Plugins](plugins.md) |
| `/plugins refresh NAME` | Reindex installed files and revoke executable activation; does not download updates. | [Plugins](plugins.md) |
| `/mcp` | Enable or disable each available MCP server. | [MCP](mcp.md) |
| `/search-api` | Configure, replace, or remove the optional Tavily key through hidden input. | [Web search](web-search.md) |

`/plugin` is an alias for `/plugins`. Installed bundles add their own commands;
see the [catalog](plugin-catalog.md) and individual guides. Use `/bundle:command`
when a short alias is ambiguous. Built-in names always take precedence.

## Automation and interface

| Command | Action | Guide |
| --- | --- | --- |
| `/schedule [prompt]` | Create a task through an interactive schedule and confirmation flow. | [Scheduling](scheduling.md) |
| `/tasks` | List tasks, run one now, toggle it, inspect history, or remove it. | [Scheduling](scheduling.md) |
| `/theme [name]` | Pick or apply an interface theme. | [Appearance](appearance.md) |
| `/notification [on\|off\|test]` | Toggle, set, or test desktop notifications. | [Notifications](notifications.md) |
| `/prompt-suggest [on\|off]` | Show controls or set optional follow-up suggestions. | [Suggestions](prompt-suggestions.md) |
| `/keybindings` | Show keyboard shortcuts. | [Terminal interface](terminal-interface.md) |
| `/help` | Show commands, shortcuts, and usage tips. | [Terminal interface](terminal-interface.md) |
| `/update check` | Check for a newer release without installing it. | [Updates](updates.md) |
| `/update` | Download and install the latest available release. | [Updates](updates.md) |
| `/exit` | Close Eirene. | [Sessions](sessions.md) |

## Launch options

Run these in your shell, outside the interactive prompt.

```sh
eirene [options]
```

| Option | Purpose |
| --- | --- |
| `-h`, `--help` | Show launch help. |
| `-v`, `--version` | Print the version. |
| `-C DIR`, `--directory DIR` | Set the existing workspace directory; defaults to the current directory. |
| `--resume` | Open the saved-session picker for that workspace. |
| `--resume UUID` | Open a particular saved interactive session. |
| `-p TEXT`, `--prompt TEXT` | Run a single headless task. |
| `--provider NAME` | Override the provider for a headless prompt. |
| `--model NAME` | Override the model for a headless prompt. |
| `--mode auto\|manual\|plan` | Set the mode for a headless prompt; default `auto`. |
| `--task ID` | Run a saved scheduled task with its recorded workspace and settings. |
| `--doctor` | Print read-only installation and configuration diagnostics. |
| `--json` | Format `--doctor` output as JSON. |
| `--no-color` | Disable colored output. |
| `--reduce-motion` | Use reduced-motion interface behavior. |

Provider, model, and mode overrides apply to `-p` runs. Interactive launches use
saved settings and their slash commands. `--json` does not make headless agent
answers JSON. Headless prompts are task text, not an interactive slash-command
interface. See [headless runs](headless.md) for output, exit codes, and limitations.
