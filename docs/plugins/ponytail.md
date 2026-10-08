# Ponytail

[Documentation](../README.md) / [Plugin catalog](../plugin-catalog.md) / Ponytail

Ponytail supplies guidance for keeping implementations small and examining
unnecessary complexity. Its review and audit workflows help identify shortcuts,
maintenance debt, and the impact of applying that guidance.

## Install and activate

```text
/plugins install ponytail
/plugins inspect ponytail
/plugins doctor ponytail
/plugins trust ponytail
```

Install Node.js separately and make `node` available on PATH. Trust is required
for Ponytail's hook-driven controls. Installation alone does not activate those
hooks. Choose Manual or Auto mode; Plan mode does not execute Ponytail hooks or
mode switches.

## Commands

| Command | Purpose |
| --- | --- |
| `/ponytail` | Show the effective mode for this session. |
| `/ponytail lite` | Select the lighter instruction level for this session. |
| `/ponytail full` | Select the full instruction level. |
| `/ponytail ultra` | Select the strongest instruction level. |
| `/ponytail off` | Turn off Ponytail's active instruction guidance for this session. |
| `/ponytail default LEVEL` | Set `lite`, `full`, `ultra`, or `off` for new sessions. |
| `/ponytail-help` | Show controls and available workflows. |
| `/ponytail-review [task]` | Review code for over-engineering. |
| `/ponytail-audit [task]` | Audit the repository using Ponytail guidance. |
| `/ponytail-debt [task]` | Collect shortcut/debt comments. |
| `/ponytail-gain [task]` | Report measured impact where evidence is available. |

Namespaced forms such as `/ponytail:ponytail-review` remain available when a short
alias collides. `/ponytail help` also shows help.

## Session controls and task flows

Mode and help controls are applied locally, without asking the model to interpret
them. A session choice does not change the saved default unless you use
`default`. Review, audit, debt, and gain commands start ordinary model turns and
follow the current permissions.

```text
/ponytail lite
/ponytail-review Inspect src/imports for unnecessary abstractions. Report findings first and do not edit.
```

Turning Ponytail off removes its active hook guidance; it does not remove the
plugin or undo previous edits. Disable the bundle through `/plugins` if you also
want its written workflows unavailable.

## State and compatibility

Eirene keeps Ponytail state in its managed `plugin-data/ponytail` area beneath the
application data directory. Hook errors or missing state are reported instead of
claiming that a switch succeeded.

The native Ponytail status line and `SubagentStart` behavior are not emulated.
Eirene supplies portable hook guidance and controls, not a duplicate of every
upstream host feature. `/ponytail-gain` needs actual evidence of impact; it is not
a guarantee of smaller code or better performance.

Use `/plugins untrust ponytail` to revoke hook execution. If installed hook files
changed, refresh, inspect, and trust again. See [plugin management](../plugins.md).

Source: [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail).

## Concrete state locations

The imported hooks receive `PLUGIN_DATA` pointing to
`plugin-data/ponytail/SESSION_UUID`, and persistent `XDG_CONFIG_HOME` pointing to
`plugin-data/ponytail/config`. The session mode is read from `.ponytail-active`;
the default control checks `config/ponytail/config.json` for `defaultMode` beneath
that persistent settings directory.

A control operation invokes the trusted hook path and validates the resulting
state. When changing levels, Eirene loads the upstream rule generator so an old
startup ruleset is not retained after `off` or another level. Plan mode suppresses
this execution. Trust is stored under `plugin_trust.ponytail`, while bundle
activation uses `plugins.ponytail` in [config.json](../config-file.md#skill-and-plugin-maps).
See [hook protocol](../plugins.md#imported-lifecycle-hooks) for stdin/environment.
