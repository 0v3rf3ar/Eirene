# Themes and accessibility

[Documentation](README.md) / Themes and accessibility

Choose a theme for the terminal interface without changing your project or model.
The default theme uses terminal-native colors and works with transparent terminal
backgrounds.

## Choose a theme

```text
/theme
/theme gruvbox
```

Ctrl+T opens the same picker. Highlighting a theme previews it; accepting saves
it. Cancelling returns to the previous theme.

| Style | Available names |
| --- | --- |
| Terminal-native | `default` |
| High-intensity | `matrix`, `hacker-red` |
| Dark palettes | `gruvbox`, `catppuccin`, `dracula`, `nord`, `tokyo-night`, `solarized-dark`, `monokai`, `one-dark`, `rose-pine`, `ayu-dark`, `everforest`, `kanagawa`, `night-owl` |
| Light palettes | `solarized-light`, `gruvbox-light`, `latte` |

A theme changes Eirene's interface palette, not your shell's global theme. Use the
picker descriptions to compare contrast against your terminal background.

## Reduce motion

```sh
eirene --reduce-motion
```

For a persistent preference, set `reduce_motion` to `true` in configuration. You
can also set `EIRENE_REDUCE_MOTION` before launching. Reduced motion uses a static
activity marker rather than the animated turn indicator; waiting and work status
are still displayed.

`accessible_icons: true` is another configuration preference for accessible icon
presentation. See [configuration](configuration.md) for editing these settings.

## Disable colors

```sh
eirene --no-color
```

`NO_COLOR=1` also disables colors and is recognized by the installers. Redirected
installer output stays plain. Display changes do not affect provider requests,
permissions, or saved project files.

## Keyboard access

Use `/keybindings` or Ctrl+K for the shortcut list. Slash commands provide access
to the same controls without relying on clickable status elements. See
[terminal interface](terminal-interface.md) for composing multiline prompts,
copying text, and interrupting work.

## Preference precedence

`theme`, `reduce_motion`, and `accessible_icons` are saved in
[config.json](config-file.md#modes-access-and-interface). A nonempty
`EIRENE_REDUCE_MOTION` enables reduced motion; setting it to the string `0` does
not disable the environment override. The launch flag can also enable it.
`NO_COLOR`/`--no-color` affect rendering rather than changing the provider request.

Display preferences do not restore the terminal's own font, background, clipboard
utilities, or keybindings. The data directory is independent of terminal profiles;
see [data layout](data-layout.md).
