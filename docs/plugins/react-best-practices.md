# React Best Practices

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / React Best Practices

React Best Practices supplies Vercel's performance guidance for React and Next.js.
Use it while writing, reviewing, or refactoring components, routes, data fetching,
and client/server boundaries.

## Install and invoke

```text
/plugins install react-best-practices
/react-best-practices Review the invoice page for request waterfalls and unnecessary client JavaScript. Report findings without editing.
```

The canonical command is `/react-best-practices:react-best-practices`. The bundle
contains a skill and supporting rule files. It does not require hooks or an MCP
server; it uses the project tools available to the selected model.

## Review areas

| Area | What the guidance examines |
| --- | --- |
| Async work | Request waterfalls and delayed independent operations. |
| Bundle size | Imports, loading strategy, and unnecessary client dependencies. |
| Server performance | Server-side work, caching, and data transfer. |
| Client data fetching | Request patterns and duplicated work. |
| Re-renders | State dependencies, repeated computation, and component updates. |
| Rendering | Expensive UI and rendering behavior. |
| JavaScript | Costly operations in relevant paths. |
| Advanced patterns | Specialized improvements that need project context. |

The skill loads relevant supporting rules rather than applying every rule blindly.
Ask for evidence of an actual bottleneck and specify behavior that must remain.

## Apply and verify

```text
/react-best-practices:react-best-practices Fix the confirmed data-fetching waterfall. Preserve the loading behavior and verify the change with the project's tests and a page check.
```

Guidance is not a profiler, benchmark, or guarantee of faster rendering. Measure
important paths before and after a performance change. The project still needs its
normal React/Next.js toolchain and dependencies.

For visual design use [Frontend Design](frontend-design.md); for accessibility
and interface compliance use [Web Design Guidelines](web-design-guidelines.md).

Source: [Vercel agent skills](https://github.com/vercel-labs/agent-skills/tree/main/skills/react-best-practices).
