# Command reference

[Documentation](../README.md) / Reference / Commands

Slash commands are typed into Eirene's prompt. Launch options are passed to `eirene` in your shell.

Type `/` to browse commands, or run `/help`. Commands that open a menu expect you to choose there. Some are listed only when they apply: `/think` for local models, `/fast` for models with a fast tier, and `/companion` in terminals that show images.

## Connections and access

| Command | Action |
| --- | --- |
| `/connect [provider]` | [Connect or switch provider](../providers/README.md#connect-and-switch). Add `!` to replace saved API settings. |
| `/model [name]` | Choose a model for the active provider. |
| `/fast [on\|off\|status]` | [Use the provider's faster, pricier tier](../providers/fast-mode.md). |
| `/think [think\|nothink]` | [Set thinking](../providers/thinking.md) for local Ollama or llama.cpp. |
| `/agents [auto\|manual\|accept\|plan]` | [Choose the mode](../guides/modes-and-permissions.md#modes). |
| `/agents list` | [List specialist profiles](../guides/subagents.md#specialist-profiles) from enabled plugins. |
| `/permissions [sandboxed\|full-access]` | [Change access](../guides/modes-and-permissions.md#full-access) for this process. |
| `/sandbox` | [Show sandbox status](../guides/modes-and-permissions.md#the-sandbox). |

## Conversation and project work

| Command | Action |
| --- | --- |
| `/review [base]` | [Read-only review](../guides/code-review.md) of working changes, or changes against a Git revision. |
| `/security-review [base]` | [The same, looking for exploitable vulnerabilities](../guides/code-review.md#security-reviews). |
| `/diff [on\|off]` | [Toggle a side panel](../guides/terminal-interface.md#follow-what-eirene-is-doing) of uncommitted Git changes. |
| `/plan`, `/plan clear` | [Show or clear](../guides/plans.md) the session plan. |
| `/sessions` | [Choose a session](../guides/sessions.md#find-and-switch-sessions) in this workspace. |
| `/sessions search TEXT` | Find sessions by text. |
| `/sessions export ID PATH` | [Export](../guides/sessions.md#export-a-conversation) to Markdown, or to JSON if the path ends in `.json`. |
| `/sessions import PATH` | [Import](../guides/sessions.md#import-a-conversation) an exported JSON session. |
| `/subagents [parent\|root\|SESSION_ID]` | [Browse](../guides/subagents.md#browse-subagent-sessions) subagent sessions. |
| `/compact` | [Summarize](../guides/context-and-usage.md#compaction) the conversation to reduce context. |
| `/clear` | [Delete](../guides/sessions.md#clear-a-conversation) the current conversation, plan and usage counters. |
| `/btw QUESTION` | [Ask a side question](../guides/side-questions.md) that is not saved. |
| `/usage` | [Show](../guides/context-and-usage.md#see-your-usage) tokens, context estimate, model breakdown and cost estimate. |

## Skills, plugins and external tools

| Command | Action |
| --- | --- |
| `/skills` | [Turn skills on and off](../extending/skills.md). |
| `/skills add SOURCE` | [Install skills](../extending/skills.md#install-skills-from-elsewhere) from any source `/plugins install` accepts. |
| `/plugins` | [Open the plugins menu](../extending/plugins.md#the-plugins-menu). `/plugin` is an alias. |
| `/plugins browse` | List the [catalog](../extending/plugin-catalog.md). |
| `/plugins install SOURCE` | [Install](../extending/plugins.md#install-a-plugin) by name, `NAME@MARKETPLACE`, GitHub path or local folder. |
| `/plugins list` | List installed plugins. |
| `/plugins inspect NAME` | Show a plugin's commands, dependencies and compatibility notes. |
| `/plugins doctor [NAME]` | [Check](../extending/plugins.md#check-for-problems) requirements and activation, without running plugin code. |
| `/plugins trust NAME`, `/plugins untrust NAME` | [Turn all of a plugin on or off](../extending/plugins.md#trust-a-plugin). |
| `/plugins enable NAME`, `/plugins disable NAME` | [Turn a trusted plugin on or off](../extending/plugins.md#turn-parts-off) for now. |
| `/plugins update [NAME]` | [Download](../extending/plugins.md#update-a-plugin) one or all plugins again. |
| `/plugins refresh NAME` | [Reread](../extending/plugins.md#refresh) installed files. Removes trust. |
| `/plugins uninstall NAME` | [Delete](../extending/plugins.md#uninstall-a-plugin) a plugin after confirmation. |
| `/plugins marketplace add\|list\|update\|remove` | [Manage marketplaces](../extending/plugins.md#marketplaces). |
| `/mcp` | [Turn MCP servers on and off](../extending/mcp.md#turn-servers-on-and-off). |
| `/mcp add\|import\|test\|login\|remove` | [Add](../extending/mcp.md#add-a-server), test, authenticate or remove MCP servers. |
| `/search-api` | [Configure the Tavily fallback](../guides/web-and-browser.md#optional-tavily-fallback). |

Plugins and skills add their own commands. Use `/plugin:command` when a short name is ambiguous. Built-in names always take priority.

## Automation

| Command | Action |
| --- | --- |
| `/schedule [prompt]` | [Create a routine](../automation/routines.md#create-a-routine). |
| `/routines` | [Review, edit, run or remove](../automation/routines.md#review-and-manage-routines) routines. |

## Interface and Eirene itself

| Command | Action |
| --- | --- |
| `/theme [name]` | [Choose a theme](../guides/appearance.md#themes). |
| `/companion [on\|off]` | [Toggle the companion](../guides/appearance.md#companion). |
| `/notification [on\|off\|test]` | [Set or test](../guides/notifications.md) desktop notifications. |
| `/prompt-suggest [on\|off]` | [Set follow-up suggestions](../guides/prompt-suggestions.md). |
| `/recap [on\|off]` | [Set session recaps](../guides/context-and-usage.md#recaps). |
| `/keybindings` | Show [keyboard shortcuts](../guides/terminal-interface.md#keyboard-shortcuts). |
| `/config` | Open [`config.json`](configuration.md#edit-the-file) in your editor. |
| `/help` | Show commands and shortcuts. |
| `/update [edge] [check]` | [Check for or install](../getting-started/updating.md) a new version. |
| `/restart` | Restart Eirene and reopen this session, typically after `/update`. Asks again if work is running. |
| `/pwd` | Show the workspace. |
| `/exit` | Close Eirene. |

## Launch options

```sh
eirene [options]
```

### General

| Option | Purpose |
| --- | --- |
| `-h`, `--help` | Show help. |
| `-v`, `--version` | Print the version. |
| `-C DIR`, `--directory DIR` | Set the workspace, which must exist. Defaults to the current directory. |
| `--resume [UUID]` | [Open a saved session](../guides/sessions.md#resume-from-your-shell), or choose from a list. |
| `--continue` | Open the most recent session in this workspace. |
| `--doctor` | Print [read-only diagnostics](../help/troubleshooting.md#run-the-diagnostics). |
| `--no-color` | Disable color. |
| `--reduce-motion` | Reduce motion. |
| `--debug` | [Log at debug level](../help/reporting-issues.md#step-3-reproduce-with-debug-logging) and name the failing handler in error warnings. |

### Headless runs

See [Headless runs](../automation/headless.md) for details. These flags are refused without `-p`, unless noted.

| Option | Purpose |
| --- | --- |
| `-p TEXT`, `--prompt TEXT` | Run one task and exit. `-p -` reads the prompt from stdin. |
| `--provider NAME`, `--model NAME` | Override the provider or model. |
| `--mode auto\|manual\|accept\|plan` | Set the mode. Default `auto`. |
| `--tools LIST` | Limit tools: `read`, `edit`, `commands`, `web`, `mcp`, `agents` or `all`. |
| `--mcp SERVERS` | Allow MCP servers: names, `all` or `none` (default). |
| `--skills NAMES` | Allow skills: names, `all` or `none`. Default follows `/skills`. |
| `--access sandboxed\|full-access` | Set sandbox level for this run only. |
| `--timeout SECONDS` | Stop the run after this long. Default 3600. |
| `--max-steps N` | Stop after N tool rounds. |
| `--max-tokens N` | Stop once input plus output tokens reach N. |
| `-q`, `--quiet` | Hide tool activity on stderr. |
| `--json` | Print a final JSON result. Also changes `--doctor` and discovery output. |
| `--stream-json` | Write one JSON event per line. |
| `--choice KEY` | Supply a slash-command choice. Repeat in order. |
| `--command-input TEXT` | Supply non-secret slash-command text. Repeat in order. |
| `--task ID` | Run a saved [routine](../automation/routines.md) with its recorded settings. |

### Discovery

| Option | Purpose |
| --- | --- |
| `--list-providers` | List available providers. |
| `--configured-providers` | List saved connections, without credentials. |
| `--list-models [PROVIDER]` | List models for the named or active provider. |
