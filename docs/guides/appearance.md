# Appearance and accessibility

[Documentation](../README.md) / Guides / Appearance and accessibility

These settings change only how Eirene looks. They have no effect on your project, model requests or permissions.

## Themes

```text
/theme
/theme gruvbox
```

`/theme`, or Ctrl+T, opens a picker. Highlighting a theme previews it, accepting saves it, and cancelling returns to your previous theme.

| Style | Themes |
| --- | --- |
| Terminal colors | `default`, which uses your terminal's own palette and works with transparent backgrounds |
| High intensity | `matrix`, `hacker-red` |
| Dark | `gruvbox`, `catppuccin`, `dracula`, `nord`, `tokyo-night`, `solarized-dark`, `monokai`, `one-dark`, `rose-pine`, `ayu-dark`, `everforest`, `kanagawa`, `night-owl` |
| Light | `solarized-light`, `gruvbox-light`, `latte` |

Your terminal controls the font and background; Eirene cannot set them.

## Reduce motion

Use any of these:

- The launch flag: `eirene --reduce-motion`.
- The setting: `"reduce_motion": true` in [`config.json`](../reference/configuration.md#interface).
- The environment variable `EIRENE_REDUCE_MOTION`, set to any non-empty value before launching. Even `0` turns it on.

The animated status is replaced by a static marker, and snowfall and the companion's movement stop. Status text keeps working.

## Turn off colors

```sh
eirene --no-color
```

Setting `NO_COLOR=1` does the same, and the installers respect it too.

## Accessible icons

Set `"accessible_icons": true` in [`config.json`](../reference/configuration.md#interface) to use a simpler set of icons. This also hides the
companion, as does `--no-color`.

## Keyboard access

Every feature has a keyboard route. Slash commands reach the same controls as clickable elements, and `/keybindings` or Ctrl+K lists the
shortcuts. See [Terminal interface](terminal-interface.md#keyboard-shortcuts).

## Companion

The companion is an optional animated character who sits above the input. She is off by default:

```text
/companion
/companion on
/companion off
```

She works in terminals that support Kitty graphics or Sixel, and the command is listed only there. She is hidden in windows smaller than 48
columns by 20 rows.

Her pose follows what Eirene is doing: she uses her laptop while it works, shows a question pose when it needs an answer from you, and falls
asleep after a minute without attention. Typing or clicking wakes her. Left alone, she also blinks, hums along to her earphones, and has a few
other small idle moments. Clicking her gets an annoyed reaction, and three quick clicks make her furious. With reduced motion, she stays still
but her expression still changes.

## December snowfall

Light snow falls in the empty chat during December, based on your system date. It stops once the conversation has content and returns after
`/clear`. Set `"seasonal_effects": false` to turn it off. Reduced motion also turns it off.
