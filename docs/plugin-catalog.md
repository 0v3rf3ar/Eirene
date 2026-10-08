# Plugin catalog

[Documentation](README.md) / Plugin catalog

Eirene offers 14 named installation shortcuts. These are imported bundles and
adapters, not 14 extra model providers. Install one with `/plugins install NAME`;
GitHub sources need Git and network access. Written workflows become available
when enabled, while hooks and MCP require separate activation.

## Available bundles

| Install name | Purpose | Commands or capabilities added | Requirements and guide |
| --- | --- | --- | --- |
| `omniroute` | Chat routing and optional gateway management. | OmniRoute in `/connect`; `/omniroute` management entry; gateway MCP tools. | Separate gateway and CLI; [OmniRoute](omniroute.md). |
| `ponytail` | Limit over-engineering and inspect shortcuts. | Mode controls, review, audit, debt, and impact workflows. | Node.js and trusted hooks for controls; [Ponytail](plugins/ponytail.md). |
| `superpowers` | Structured design, plans, debugging, tests, and completion. | 15 skill workflows and optional startup guidance. | Git/Bash for relevant workflows and hook; [Superpowers](plugins/superpowers.md). |
| `anthropic-skills` | Documents, design, communication, and skill authoring. | 19 skills in the upstream snapshot, under `/skills:...`. | Per-skill runtime/rendering tools; [Anthropic Skills](plugins/anthropic-skills.md). |
| `frontend-design` | Design and implement a distinctive frontend. | `/frontend-design` skill workflow. | Project's frontend toolchain; [Frontend Design](plugins/frontend-design.md). |
| `code-review` | Multi-pass GitHub PR review. | `/code-review` and upstream PR-commenting workflow. | Git and authenticated `gh`; [Code Review](plugins/code-review.md). |
| `commit-commands` | Commit, push, PR, and stale-branch workflows. | `commit`, `commit-push-pr`, and `clean_gone` commands. | Git; `gh` for PR creation; [Commit Commands](plugins/commit-commands.md). |
| `pr-review-toolkit` | Focused review by concern. | `review-pr`, six specialist profiles, and profile commands. | Git; `gh` for PR context; [PR Review Toolkit](plugins/pr-review-toolkit.md). |
| `feature-dev` | Explore, design, implement, and review a feature. | `/feature-dev` and three specialist profiles. | Project tools and Git; [Feature Dev](plugins/feature-dev.md). |
| `playwright` | Browser automation and page testing. | `/playwright` plus enabled Playwright MCP tools. | Node.js/npx, browser dependencies, `/mcp`; [Playwright](plugins/playwright.md). |
| `serena` | Semantic code navigation and supported edits. | `/serena` plus enabled language-server MCP tools. | uv/uvx, Git, language prerequisites, `/mcp`; [Serena](plugins/serena.md). |
| `react-best-practices` | React and Next.js performance guidance. | Review/implementation skill and supporting rule files. | React project's tools; [React Best Practices](plugins/react-best-practices.md). |
| `react-native-skills` | React Native and Expo guidance. | Mobile performance/UI skill and rule files. | Project and native tooling; [React Native Skills](plugins/react-native-skills.md). |
| `web-design-guidelines` | Review interface usability and accessibility. | Guideline-based audit skill using current upstream rules. | Network for guideline retrieval; [Web Design Guidelines](plugins/web-design-guidelines.md). |

Counts and command inventories for remote bundles describe the upstream content
used for these guides. Installation follows the source's current default branch,
so later upstream changes may differ. `/plugins inspect NAME`, `/skills`, and
`/help` show what your installed copy actually provides. Use a supported GitHub
tag/tree source when you need a particular upstream version.

## Choose a workflow

For ordinary workspace review, the built-in `/review` is enough. Add Code Review
for a GitHub PR workflow or PR Review Toolkit for specialized analysis. Choose
Feature Dev for a guided feature process, or Superpowers when you want explicit
design, planning, and test-first stages.

Frontend Design and the Anthropic Skills bundle overlap: the larger bundle also
contains document and other artifact workflows. Enable the relevant skill and
use its namespaced command when aliases collide. React, React Native, and Web
Design Guidelines focus on different kinds of review.

Playwright and Serena add external tools; their Markdown entry commands alone
are not the integration. Enable their servers with `/mcp` after checking
prerequisites. OmniRoute chat routing and gateway management are also separate.

See [plugin management](plugins.md) for installation, updates, and activation,
[MCP](mcp.md) for external tool servers, and [specialists](specialists.md) for
independent task passes. Tool-less providers cannot execute these workflows;
provider-neutral guidance does not remove a provider's actual capability limits.
