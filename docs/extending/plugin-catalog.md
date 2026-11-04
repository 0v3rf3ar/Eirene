# Plugin catalog

[Documentation](../README.md) / Extending Eirene / Plugin catalog

These 10 plugins can be installed by name. For example:

```text
/plugins install superpowers
/plugins trust superpowers
```

Nothing in a plugin works until you [trust it](plugins.md#trust-a-plugin).

| Plugin | Use it for | Adds | Requires |
| --- | --- | --- | --- |
| [`superpowers`](plugins/superpowers.md) | Structured design, planning, debugging and test-first work. | 14 skills and optional startup guidance. | Git and Bash for some workflows. |
| [`eirene-skills`](plugins/eirene-skills.md) | Documents, design, frontend, testing, writing, MCP servers and writing skills. | 16 skills. | Python, Node.js, LibreOffice or Poppler, depending on the skill. |
| [`feature-dev`](plugins/feature-dev.md) | Exploring, designing, implementing and reviewing a feature. | `/feature-dev` and 3 specialist profiles. | Git and your project's tools. |
| [`pr-review-toolkit`](plugins/pr-review-toolkit.md) | Reviewing a change by concern. | `review-pr` and 6 specialist profiles. | Git, plus `gh` for pull request context. |
| [`ponytail`](plugins/ponytail.md) | Limiting over-engineering and auditing shortcuts. | Mode controls and review, audit, debt and impact workflows. | Node.js. |
| [`arena`](plugins/arena.md) | Making subagents compete when an answer keeps falling short. | `/arena`. | Python and a tool-capable provider. |
| [`playwright`](plugins/playwright.md) | Browser automation and page testing. | `/playwright` and browser MCP tools. | Node.js, `npx` and browser dependencies. |
| [`serena`](plugins/serena.md) | Language-aware code navigation and edits. | `/serena` and MCP tools. | `uv`, Git and language tools. |
| [`obsidian`](plugins/obsidian.md) | Working with Obsidian vault files. | 6 skills. | The relevant CLI, for some skills. |
| [`omniroute`](../providers/omniroute.md) | Routing chat through an OmniRoute gateway, and managing it. | A `/connect` entry, `/omniroute` and MCP tools. | A separate gateway and CLI. |

## Which one should I use?

| Situation | Suggestion |
| --- | --- |
| Reviewing your working changes | The built-in [`/review`](../guides/code-review.md) is enough. |
| Reviewing tests, error handling or types in depth | PR Review Toolkit |
| Building a feature in an unfamiliar codebase | Feature Dev |
| Wanting explicit design, planning and test-first stages | Superpowers |
| Reading and writing Office documents and PDFs | Eirene Skills |
| Designing an interface | The `frontend-design` skill in Eirene Skills |
| An answer that keeps falling short | Arena |
| Testing a web app across many steps | Playwright. The [built-in browser](../guides/web-and-browser.md#use-the-browser) handles simple checks. |
| Tracing symbols in a large codebase | Serena |

## Where they come from

`eirene-skills`, `superpowers`, `arena` and `obsidian` ship inside Eirene, adapted for it, in [`eirene/plugins`](https://github.com/0v3rf3ar/Eirene/tree/master/eirene/plugins). Installing one copies the version packaged with your
Eirene, with no network needed. `/plugins update NAME` fetches the newest copy from the `master` branch.

`omniroute` is generated locally by Eirene and does not install the gateway.

The others are downloaded from GitHub, which needs Git and network access. They follow the source's default branch, so they may have changed since this page was written. `/plugins inspect NAME`, `/skills` and `/help` show what your
installed copy provides. To pin a version, install from a GitHub tree URL with a tag.

Installing a plugin does not install its dependencies. A repository containing an MCP server's source is not necessarily a plugin, so for a server executable use a
[standalone MCP declaration](mcp.md#add-a-server-by-hand).

## Credits

These plugins are the work of their authors. Thank you to:

| Plugin | Made by | Source |
| --- | --- | --- |
| `superpowers` | Jesse Vincent | [obra/superpowers](https://github.com/obra/superpowers) |
| `arena` | Jake Schincariol | [Jakeschincariol/arena-skill](https://github.com/Jakeschincariol/arena-skill) |
| `obsidian` | Steph Ango | [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) |
| `eirene-skills` (`frontend-design`) | Anthropic | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design) |
| `ponytail` | DietrichGebert | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) |
| `pr-review-toolkit` | Anthropic | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/pr-review-toolkit) |
| `feature-dev` | Anthropic | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/feature-dev) |
| `playwright` | Microsoft | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) |
| `serena` | Oraios | [oraios/serena](https://github.com/oraios/serena) |
| `omniroute` | The OmniRoute project | [OmniRoute](https://github.com/diegosouzapw/OmniRoute) |

The first four are adapted for Eirene, and their changes are listed in the [NOTICE](../../NOTICE) file. The rest of `eirene-skills` was written for Eirene.
