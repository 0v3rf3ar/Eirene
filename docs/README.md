# Eirene documentation

Eirene is an AI agent that runs in your terminal and works on a project through conversation. It can read files, make edits, run commands and use installed plugins. A provider of your choice supplies the model, while Eirene supplies the tools, approvals and sandbox around it.

New to Eirene? Follow [Installation](getting-started/installation.md), then [Your first session](getting-started/first-session.md).

## Getting started

- [Installation](getting-started/installation.md): install, verify, and choose a version or directory.
- [Your first session](getting-started/first-session.md): connect a provider and complete a small task.
- [Updating](getting-started/updating.md): stable and prerelease updates.

## Providers and models

- [Providers and models](providers/README.md): choose and connect an API, local, subscription or custom provider.
- [Thinking and reasoning](providers/thinking.md): control how much a model reasons.
- [Fast mode](providers/fast-mode.md): the same model on a faster, pricier tier.
- [OmniRoute](providers/omniroute.md): route chat through a gateway and manage it.

## Guides

**Using the interface**

- [Terminal interface](guides/terminal-interface.md): compose messages, keyboard shortcuts, attachments, copying and SSH.
- [Modes and permissions](guides/modes-and-permissions.md): what Eirene may do without asking, and the sandbox.
- [Appearance and accessibility](guides/appearance.md): themes, reduced motion, colors and the companion.
- [Notifications](guides/notifications.md): desktop alerts when work finishes.

**Doing the work**

- [Project instructions](guides/project-instructions.md): give Eirene your conventions and test commands.
- [Working with code](guides/working-with-code.md): find, follow, edit and check code.
- [Running commands](guides/running-commands.md): tests, builds, servers and background work.
- [Web, browser and HTTP](guides/web-and-browser.md): research, rendered pages, screenshots and API calls.
- [Code review](guides/code-review.md): read-only reviews of your changes.
- [Plans](guides/plans.md): track progress across a long task.
- [Subagents](guides/subagents.md): delegate to independent agents and specialist profiles.

**Managing conversations**

- [Sessions](guides/sessions.md): resume, search, export, import and clear.
- [Context and usage](guides/context-and-usage.md): compaction, context limits, recaps, tokens and costs.
- [Context shifting](guides/context-shifting.md): how Eirene adapts to local models.
- [Side questions](guides/side-questions.md): ask something without adding it to the conversation.
- [Prompt suggestions](guides/prompt-suggestions.md): drafts of your next message.

## Extending Eirene

- [Skills](extending/skills.md): reusable Markdown guidance.
- [Plugins](extending/plugins.md): install, trust, update and remove bundles.
- [Plugin catalog](extending/plugin-catalog.md): the plugins available by name, and which to choose.
- [MCP servers](extending/mcp.md): connect external tools and services.
- [MCP examples](mcp-examples/README.md): ready-to-import server definitions.
- [Writing plugins](extending/writing-plugins.md): package format and hooks.

Guides to individual plugins:
[Arena](extending/plugins/arena.md) ·
[Eirene Skills](extending/plugins/eirene-skills.md) ·
[Feature Dev](extending/plugins/feature-dev.md) ·
[Obsidian](extending/plugins/obsidian.md) ·
[OmniRoute](providers/omniroute.md) ·
[Playwright](extending/plugins/playwright.md) ·
[Ponytail](extending/plugins/ponytail.md) ·
[PR Review Toolkit](extending/plugins/pr-review-toolkit.md) ·
[Serena](extending/plugins/serena.md) ·
[Superpowers](extending/plugins/superpowers.md)

## Automation

- [Headless runs](automation/headless.md): run one task from a shell or script.
- [Routines](automation/routines.md): run tasks on a schedule through your system's scheduler.

## Platforms

- [Platform support](platforms/platform-support.md): requirements and sandbox behavior on Linux, macOS and Windows.
- [Windows sandbox](platforms/windows-sandbox.md): how AppContainer isolation works.

## Reference

- [Commands](reference/commands.md): every slash command and launch option.
- [Configuration](reference/configuration.md): every field in `config.json`, credentials and environment variables.
- [Data directory](reference/data-directory.md): what Eirene stores, and how to back it up or move it.

## Help

- [Troubleshooting](help/troubleshooting.md): diagnose common problems.
- [Reporting bugs and crashes](help/reporting-issues.md): gather what is needed and open a GitHub issue.
- [Security policy](../SECURITY.md): report a vulnerability privately.
- [Releases](https://github.com/0v3rf3ar/Eirene/releases): downloads and what changed in each version.

## Reading these pages

Examples in `text` blocks are typed into Eirene's prompt. Examples marked `sh` or `powershell` run in your terminal. Uppercase names such as `SESSION_ID`, `NAME` and `MODEL_NAME` are placeholders for your own values.
