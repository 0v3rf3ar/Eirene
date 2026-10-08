# Eirene documentation

Eirene is a terminal agent for working on a project through conversation. It can
inspect files, make edits, run checks, and use installed plugins. Your selected
provider supplies the model; Eirene supplies the workspace and the controls for
working in it.

Start with [installation](installation.md) and [your first session](getting-started.md).
If Eirene is already configured, use the [command reference](commands.md) to find
an action or the [plugin catalog](plugin-catalog.md) to choose a workflow.

## Set up

| Guide | What you will learn |
| --- | --- |
| [Installation](installation.md) | Install, choose a version, configure PATH, and download manually. |
| [Providers and models](providers.md) | Connect API, local, custom, and subscription providers. |
| [Platform support](platforms.md) | Supported releases, shells, isolation, and OS requirements. |
| [Configuration](configuration.md) | Overview of settings, credentials and environment variables. |
| [config.json reference](config-file.md) | Complete defaults, fields, nested schemas, validation, lookup order and examples. |
| [Data layout and source structure](data-layout.md) | Filesystem trees, session/artifact identities, backups and source modules. |
| [Updates](updates.md) | Check for releases and update an installation. |

## Work in a project

| Guide | What you will learn |
| --- | --- |
| [First session](getting-started.md) | Open a project, choose a mode, and complete a small task. |
| [Terminal interface](terminal-interface.md) | Compose prompts, use menus, inspect output, and stop work. |
| [Commands](commands.md) | Every built-in slash command and every public launch option. |
| [Modes and permissions](harness.md) | Decide when changes need approval and understand host access. |
| [Project instructions](project-instructions.md) | Give Eirene recurring project rules and verification steps. |
| [Files and code navigation](code-navigation.md) | Find code, inspect references, edit files, and check syntax. |
| [Plans](plans.md) | Keep an objective and progress across a session. |
| [Code review](review.md) | Review a working tree or compare against a Git base. |
| [Running commands](processes.md) | Manage tests, builds, servers, timeouts, and saved output. |
| [Web research](web-search.md) | Search, read sources, and configure the optional search API. |
| [Browser and image work](browser.md) | Inspect pages, interact with them, and review screenshots. |
| [HTTP requests](http-requests.md) | Ask for an explicit endpoint request and inspect its response. |
| [Sessions](sessions.md) | Resume, find, export, import, and clear conversations. |
| [Context and usage](context-and-usage.md) | Compact long conversations and read token estimates. |
| [Side questions](side-questions.md) | Ask a question without adding it to the main conversation. |

## Customize and automate

| Guide | What you will learn |
| --- | --- |
| [Skills](skills.md) | Add reusable Markdown guidance and control enabled skills. |
| [Plugins](plugins.md) | Install bundles, inspect them, and manage their capabilities. |
| [Plugin catalog](plugin-catalog.md) | Compare all 14 named installation shortcuts. |
| [MCP servers](mcp.md) | Declare and enable stdio servers, understand protocol/grants and diagnose startup. |
| [Specialist agents](specialists.md) | Use plugin profiles and request independent review passes. |
| [Headless runs](headless.md) | Run one task from a shell or script. |
| [Scheduled tasks](scheduling.md) | Create recurring work with your OS scheduler. |
| [Themes and accessibility](appearance.md) | Choose colors, reduce motion, and adjust terminal output. |
| [Notifications](notifications.md) | Enable and test desktop notifications. |
| [Prompt suggestions](prompt-suggestions.md) | Enable optional model-generated follow-up drafts. |
| [Local model thinking](thinking.md) | Control the local Ollama thinking option. |
| [Troubleshooting](troubleshooting.md) | Diagnose installation, provider, execution, and plugin issues. |

## Plugin guides

[OmniRoute](omniroute.md) · [Ponytail](plugins/ponytail.md) ·
[Superpowers](plugins/superpowers.md) · [Anthropic Skills](plugins/anthropic-skills.md) ·
[Frontend Design](plugins/frontend-design.md) · [Code Review](plugins/code-review.md) ·
[Commit Commands](plugins/commit-commands.md) · [PR Review Toolkit](plugins/pr-review-toolkit.md) ·
[Feature Dev](plugins/feature-dev.md) · [Playwright](plugins/playwright.md) ·
[Serena](plugins/serena.md) · [React Best Practices](plugins/react-best-practices.md) ·
[React Native Skills](plugins/react-native-skills.md) ·
[Web Design Guidelines](plugins/web-design-guidelines.md)

Examples inside a `text` block are prompts or slash commands to enter in Eirene.
Examples marked `sh` or `powershell` run in your terminal. Names such as
`SESSION_ID`, `TASK_ID`, and `MODEL_NAME` are placeholders to replace.

## Reading the technical references

Start with [config.json](config-file.md) when editing settings by hand, and
[data layout](data-layout.md) when inspecting saved state. Feature guides describe
the corresponding command, stored schema, runtime dependencies, and limits.
Examples with placeholder paths/model IDs require substitution; JSON fragments
should be merged into the existing object rather than replacing unrelated fields.
The implementation references in these guides identify the code responsible for
the behavior. Remote plugin guides describe imported guidance; exact content can
change with the upstream version you install.
