# React Native Skills

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / React Native Skills

React Native Skills supplies Vercel guidance for React Native and Expo projects.
It focuses on mobile performance, interaction, platform behavior, and project
configuration rather than general web frontend design.

## Install and invoke

```text
/plugins install react-native-skills
/react-native-skills Review the feed screen for expensive list items and unstable callbacks. Keep the review read-only.
```

The canonical command is `/react-native-skills:react-native-skills`. The imported
skill and its rule files need no hook or MCP activation. Actual builds and checks
require your project's JavaScript and native tooling.

## Guidance areas

| Area | Focus |
| --- | --- |
| Lists | Virtualization, item cost, image handling, and stable references. |
| Animation | Efficient animated properties and gesture patterns. |
| Navigation | Native navigation behavior and performance. |
| UI | Images, presses, safe areas, menus, modals, and scroll behavior. |
| State and rendering | Update patterns and component work. |
| Monorepos | Native dependency structure and package boundaries. |
| Configuration | Fonts, imports, and platform setup. |

Supply the target platform and whether the app uses Expo or a custom native setup.
A rule appropriate to one runtime may need adjustment in another.

## Check the result

```text
/react-native-skills:react-native-skills Improve feed scrolling on Android. Preserve row behavior and verify with the available checks; state anything that still needs a device run.
```

The skill does not install an emulator, Xcode, Android SDK, native modules, or an
Expo environment. Eirene can run only checks supported by the current host and
permissions. Device performance still needs observation or measurement on the
relevant runtime. A passed JavaScript test is not proof that native behavior works.

For browser-based React/Next.js guidance, use
[React Best Practices](react-best-practices.md).

Source: [Vercel agent skills](https://github.com/vercel-labs/agent-skills/tree/main/skills/react-native-skills).

## Host tooling and saved activation

The skill ID is `react-native-skills:react-native-skills` and bundle activation
is `plugins.react-native-skills`. The copied rules are instruction resources;
Xcode, Android SDK, emulators and signing configuration are external host/project
state. They are not stored as Eirene provider credentials or installed by the
bundle importer.

A delegated read-only pass can examine code but cannot acquire an interactive
device environment by using a specialist profile. Specify which host/platform
checks are available. See [platform runtime](../platforms.md),
[resource import](../plugins.md#local-bundle-format), and
[config activation](../config-file.md#skill-and-plugin-maps).
