# Ponytail

[Documentation](../../README.md) / [Plugin catalog](../plugin-catalog.md) / Ponytail

Ponytail supplies guidance for keeping implementations small, along with review and audit workflows that look for unnecessary complexity, shortcuts and maintenance debt.

## Install

```text
/plugins install ponytail
/plugins inspect ponytail
/plugins doctor ponytail
/plugins trust ponytail
```

Install Node.js separately and make sure `node` is on `PATH`, because Ponytail's controls are driven by hooks. Plan mode does not run them.

## Commands

| Command | Purpose |
| --- | --- |
| `/ponytail` | Show the mode in effect for this session. |
| `/ponytail lite` | Use the lighter level of guidance for this session. |
| `/ponytail full` | Use the full level. |
| `/ponytail ultra` | Use the strongest level. |
| `/ponytail off` | Turn off Ponytail's guidance for this session. |
| `/ponytail default LEVEL` | Set `lite`, `full`, `ultra` or `off` for new sessions. |
| `/ponytail-help` | Show controls and workflows. `/ponytail help` does the same. |
| `/ponytail-review [task]` | Review code for over-engineering. |
| `/ponytail-audit [task]` | Audit the repository. |
| `/ponytail-debt [task]` | Collect comments that mark shortcuts or debt. |
| `/ponytail-gain [task]` | Report measured impact, where there is evidence for it. |

If a short name is taken, use the long form, such as `/ponytail:ponytail-review`.

## Use it

Mode and help commands are applied directly, without asking the model. A session choice leaves your saved default unchanged. Review, audit, debt and gain commands start ordinary model turns and follow your current permissions.

```text
/ponytail lite
/ponytail-review Inspect src/imports for unnecessary abstractions. Report findings first and do not edit.
```

`/ponytail off` removes the active guidance. It does not undo earlier edits, and the written workflows remain available. To turn off the whole plugin, use `/plugins untrust ponytail`.

## Compatibility

Hook errors or missing state are reported rather than claiming that a switch worked. Ponytail's own status line and `SubagentStart` behavior are not available in Eirene.

Its state is kept in `plugin-data/ponytail` in the [data directory](../../reference/data-directory.md). The default mode is stored at `plugin-data/ponytail/config/ponytail/config.json`, as `defaultMode`.

## Origin

Made by DietrichGebert, with thanks. Source: [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail).
