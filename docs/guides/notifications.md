# Notifications

[Documentation](../README.md) / Guides / Notifications

Eirene can send a desktop notification when work finishes or fails, so you can do something else in the meantime. This is off by default.

```text
/notification on
/notification test
/notification off
```

`/notification` alone toggles the setting. Turning it on sends a confirmation, and `test` sends a sample without changing the setting.

Notifications can include a short excerpt of the answer, so consider who can see your screen when working with private material.

## Requirements

| System | Utility used |
| --- | --- |
| Linux | `notify-send`; otherwise `kdialog`, `zenity`, `gdbus`, `dbus-send` or `notify-send.py`. |
| macOS | `terminal-notifier`; otherwise `osascript`. |
| Windows | `pwsh` or Windows PowerShell. |

A utility being present does not guarantee a visible notification. System settings, a remote shell, or having no desktop session can all
prevent one. Run the test before relying on it.

## Routines

Failed [routines](../automation/routines.md) can also notify you when this setting is on, but a routine run by your system scheduler may
not have access to your desktop session. Check `/routines` for the reliable record of what happened.
