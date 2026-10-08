# Frontend Design

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / Frontend Design

Frontend Design is written guidance for designing and implementing a frontend
with a deliberate visual direction. It addresses typography, layout, color,
interaction, and implementation choices in the context of your actual project.

## Install and invoke

```text
/plugins install frontend-design
/frontend-design Build a compact invoice dashboard using the project's existing components. Keep its accessibility behavior and responsive layout.
```

The canonical command is `/frontend-design:frontend-design`. The short alias is
available when it does not collide with another enabled skill. This bundle does
not need an executable hook or MCP server for its guidance.

## Give the design context

Explain the audience, main action, required content, existing brand or components,
and output you want. If a design is established, state which parts must be kept.
Provide a reference file or screenshot in the workspace when useful.

```text
/frontend-design:frontend-design Refine the settings page. Keep the current brand colors and navigation, improve field grouping, and check the narrow-screen layout.
```

The skill guides the model through design and implementation; it does not install
a UI framework or change your application's toolchain by itself. File changes
and commands follow normal permissions.

## Verify the result

Ask for the project build and accessibility checks, then inspect the rendered
page. Built-in [browser helpers](../browser.md) or the [Playwright plugin](playwright.md)
can help when their prerequisites are satisfied. Visual review requires an
image-capable model when it involves screenshots.

For an audit against current web interface rules, use
[Web Design Guidelines](web-design-guidelines.md). The
[Anthropic Skills](anthropic-skills.md) bundle also contains a frontend-design
skill; namespaced commands distinguish the two installations.

Source: [Anthropic official plugins](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design).

## Guidance identity and runtime

The standalone skill uses the config ID `frontend-design:frontend-design`; the
Anthropic collection's variant uses `skills:frontend-design`. These are separate
preferences even when their short aliases collide. Bundle enablement is stored
under `plugins`, individual guidance under `skills`.

The imported command supplies instructions to the selected model and tools;
it does not supply a rendering engine or dependency installation step. Workspace
output and screenshots are separate from the plugin's copied resource files.
See [skill parsing/loading](../skills.md#discovery-identifiers-and-parsing-limits)
and [config.json](../config-file.md#skill-and-plugin-maps).
