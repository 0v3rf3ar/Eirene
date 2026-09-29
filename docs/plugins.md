# Plugins in Eirene

Install a catalog shortcut, local directory, `owner/repo`, repository subdirectory,
or GitHub repository/tree URL:

```text
/plugins install DietrichGebert/ponytail
/plugins inspect ponytail
/plugins trust ponytail
/ponytail ultra
/ponytail-review
/ponytail off
```

Individual plugins inside a larger repository can be installed without importing
the other plugins:

```text
/plugins install frontend-design
/plugins install anthropics/claude-plugins-official/plugins/commit-commands
/plugins install https://github.com/anthropics/claude-plugins-official/tree/main/plugins/feature-dev
```

`owner/repo/path` uses the repository's default branch. Tree URLs select a branch
or tag with a single path segment; branch names containing `/` are not supported.
Catalog shortcuts resolve to repository paths, and a matching local directory
takes precedence. `/plugins install anthropic-skills` installs the bundle as
`skills`; inspect, trust, and toggle using the installed name printed by Eirene.

`trust` shows executable hook commands and MCP servers before asking whether to
allow them. Installation does not run repository installers. Markdown skills and
commands are available immediately; imported hooks and MCP processes stay disabled
until trusted. `/plugins untrust <name>` revokes executable access. `/plugins`
toggles the whole bundle; `/skills` toggles individual skills. Changes apply on the
next turn. Plan mode never launches plugin hooks or imported MCP servers.

For a Ponytail installation made by the older skills-only importer:

```text
/plugins refresh ponytail
/plugins inspect ponytail
/plugins trust ponytail
```

Refresh reindexes the files already installed, including preserved Claude/Codex
manifests; it does not fetch updates or replace supporting files. It revokes
executable trust so changed declarations can be reviewed. Installation refuses to
overwrite an existing plugin. Repositories containing symlinks are rejected.

## Commands and provider support

Skills and `commands/*.md` become `/plugin:command`. A short `/command` alias is
also available when unique and not reserved by Eirene. They appear in completion
and `/help`. Arguments replace `$ARGUMENTS`, `$ARGUMENTS[0]`, and `$0` (zero based).
Without placeholders, arguments are appended. Expansion is literal: shell snippets
are instructions for the model and do not execute during command expansion.

Eirene resolves commands before invoking a provider. API providers receive the
expanded instructions and lifecycle context in their system prompt. The Codex
app-server and Claude Code headless providers receive the same instructions;
trusted stdio MCP definitions are translated into their native configuration.
Eirene does not modify either CLI's global plugin installation or configuration.
Native threads are recreated, with Eirene conversation history, when instructions
or MCP definitions change, so disabled plugins cannot leave stale host guidance.
Large native skill bundles retain a path catalogue for skills exceeding the inline
budget; the native agent can read those files when needed.

Ponytail controls (`/ponytail`, mode switches, `default`, and `/ponytail-help`)
are handled by Eirene without starting an AI turn. Invalid arguments, missing
hooks, untrusted hooks, and plan mode produce local errors. Markdown task commands
such as reviews and audits start an AI turn with the resolved plugin instructions.

| Component | Portable behavior |
| --- | --- |
| Claude `.claude-plugin/plugin.json`, Codex `.codex-plugin/plugin.json`, `.agent-plugin/plugin.json`, `.github/plugin/plugin.json`, root `plugin.json` | Import metadata and supported declarations; semantic plugin versions are accepted |
| `skills/*/SKILL.md`, `skills/*.md`, root `SKILL.md` | Skill catalogue, loading, and explicit slash commands |
| Markdown commands, including declared custom directories | Slash commands and argument expansion |
| `agents/*.md` | `/plugin:agent-name` instruction commands; does not spawn an isolated subagent |
| `SessionStart`, `UserPromptSubmit` command hooks | Run in Eirene with JSON stdin, plugin-root environment variables, timeout, and configured isolation |
| Hook context and blocking | Plain text or `hookSpecificOutput.additionalContext`; `systemMessage` notices; failures and block decisions stop the turn |
| Stdio MCP (`command`, `args`, `env`) in `.mcp.json`, `mcp.json`, or manifest declarations | Eirene tools for API providers; native configuration for Codex/Claude Code |
| HTTP/SSE MCP, OAuth/app connectors | Not imported; reported by inspection |
| Other lifecycle events, prompt/agent/async hooks, LSP, output styles | Not emulated; declared unsupported features are reported |
| Native statuslines, marketplace management, automatic dependency installation | Not provided by Eirene |

`/plugins inspect <name>` reports commands, executable declarations, and known
compatibility limits. This is a portable subset, not complete Claude Code runtime
emulation. Model-specific instructions may still refer to unavailable tools;
Eirene asks models to use equivalent host tools without widening permissions.
Dependencies and model capability still matter, especially for small local models.

## Ponytail

Ponytail needs `node` on the non-interactive PATH. Its upstream activation and mode
tracking scripts run in Eirene, with separate state for each Eirene session. The
adapter uses Ponytail's own instruction generator when modes change, so `off`
removes the startup rules and `lite`, `full`, `ultra`, and review mode load the
corresponding rules. `/ponytail default <mode>` persists defaults in Eirene's
plugin data directory. `PONYTAIL_DEFAULT_MODE` is also supported.

Ponytail state lives under `~/.local/eirene/plugin-data/ponytail/` (or
`EIRENE_HOME/plugin-data/ponytail/`). It does not write Claude's statusline settings.
Native `SubagentStart` injection is not emulated; the main agent receives the rules.

## Bundles to try

Use `/plugins browse` for installation suggestions:

- [Ponytail](https://github.com/DietrichGebert/ponytail): minimal implementations,
  reuse, and over-engineering reviews. Install `DietrichGebert/ponytail`.
- [Superpowers](https://github.com/obra/superpowers): planning, systematic debugging,
  and testing workflows. Install `obra/superpowers`; trust its startup hook to
  activate its workflow guidance automatically. Delegation instructions remain
  dependent on the host's available tools.
- [Anthropic Skills](https://github.com/anthropics/skills): frontend design,
  document workflows, and skill authoring. Install `anthropics/skills` and enable
  the skills you need. This imports the repository's skill collection as one
  bundle, rather than its marketplace's separate products. Document skills may
  need external libraries or executables; review each skill's prerequisites and
  license.

Additional catalog shortcuts install individual bundles from
[Anthropic's official plugins](https://github.com/anthropics/claude-plugins-official)
and [Vercel's agent skills](https://github.com/vercel-labs/agent-skills):

| Shortcut (`/plugins install <shortcut>`) | Portable functionality / prerequisites |
| --- | --- |
| `frontend-design` | Frontend design skill |
| `code-review` | PR review command; requires GitHub CLI for GitHub operations |
| `commit-commands` | Commit, cleanup, and PR commands; requires Git/GitHub CLI |
| `pr-review-toolkit` | PR review command and specialist agent instruction commands |
| `feature-dev` | Feature development command and specialist agent instruction commands |
| `playwright` | Microsoft Playwright stdio MCP; requires Node.js/npx, browser dependencies, and trust |
| `serena` | Serena stdio MCP for code navigation; requires uv/uvx and trust |
| `react-best-practices` | Vercel React/Next.js performance guidance |
| `react-native-skills` | Vercel React Native guidance |
| `web-design-guidelines` | Vercel web design/accessibility review guidance |

Review and feature workflows include Claude-specific delegation instructions.
Eirene imports their prompts and agents as commands; it does not reproduce native
parallel subagent execution or model routing. MCP dependencies are not installed
by the plugin importer. Inspect the bundle and install its dependencies before
trusting it. Vercel skills are installed individually to avoid unrelated files
and symlinks in the repository root.

Format references: [Claude plugin reference](https://code.claude.com/docs/en/plugins-reference),
[OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins),
and [Codex app-server](https://learn.chatgpt.com/docs/app-server).
