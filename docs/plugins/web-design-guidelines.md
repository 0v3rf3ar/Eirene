# Web Design Guidelines

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / Web Design Guidelines

Web Design Guidelines audits UI files against Vercel's current Web Interface
Guidelines. It is a review workflow for accessibility, usability, and interface
behavior; it does not automatically redesign the application.

## Install and invoke

```text
/plugins install web-design-guidelines
/web-design-guidelines src/components/settings.tsx
```

The canonical command is `/web-design-guidelines:web-design-guidelines`. Give a
file or pattern to review; with no scope, the workflow asks which files to inspect.
No hook or MCP server is required.

## Review flow

```text
fetch current rules -> inspect selected files -> check each relevant rule -> report file:line findings
```

The skill retrieves the current guideline document before the audit, so network
access is needed under the applicable permission policy. If retrieval fails, the
model should report that gap rather than claim compliance with rules it has not
read. The upstream guideline document controls the detailed rule set and output
format, so it can evolve independently from an installed skill.

```text
/web-design-guidelines:web-design-guidelines Review src/pages/settings.tsx and src/components/form. Keep the report read-only and include the applicable rule for each finding.
```

## Follow up

Review the findings and request specific fixes in a later turn. Static code review
cannot prove every keyboard, screen-reader, responsive-layout, or runtime behavior.
Use [browser inspection](../browser.md), [Playwright](playwright.md), and appropriate
manual accessibility checks for the behaviors that need a running page.

Use [Frontend Design](frontend-design.md) for a design-and-implementation workflow,
or [React Best Practices](react-best-practices.md) for performance-focused review.

Sources: [skill bundle](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines),
[current guideline source](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md).

## Installed guidance versus fetched rules

The config skill ID is `web-design-guidelines:web-design-guidelines`; the bundle
key is `plugins.web-design-guidelines`. The installed instruction file and its
live guideline URL are separate inputs. Refreshing the bundle reindexes local
files; fetching current guideline text happens during the requested audit.

Record the source URL and concrete rules used in findings if you need to assess
an audit later. A session retains the tool observations that were actually
returned, subject to output/context bounds. See [web search limits](../web-search.md#cache-and-request-bounds),
[session formats](../sessions.md#event-log-format), and
[config.json](../config-file.md#skill-and-plugin-maps).
