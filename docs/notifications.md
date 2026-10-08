# Desktop notifications

[Documentation](README.md) / Desktop notifications

Notifications let Eirene report relevant completion or failure events through
your desktop while you are working elsewhere. They are off by default and require
a usable notification utility in your session.

```text
/notification on
/notification test
/notification off
```

With no argument, `/notification` toggles the saved preference. The `test` action
sends a sample notification without changing that preference. Enabling also sends
a confirmation notification.

Completion notifications can include a short excerpt of the answer. Consider
your desktop's notification visibility when working with private project data.

## Platform requirements

| System | Notification utility |
| --- | --- |
| Linux | `notify-send` preferred; also `kdialog`, `zenity`, `gdbus`, `dbus-send`, `termux-notification`, or `notify-send.py`. |
| macOS | `terminal-notifier` when available, otherwise `osascript`. |
| Windows | `pwsh` or Windows PowerShell. |

The OS notification settings, a remote shell, or the absence of a desktop session
can prevent a visible notification even if the utility exists. Use the test before
relying on it. Notifications are not a substitute for recorded command output or
scheduled-task history.

Scheduled run failures can use notifications when the preference is enabled and
the scheduled environment has a usable desktop notification path. See
[scheduling](scheduling.md) for inspecting outcomes directly.

## Persistence and delivery

The saved field is `notifications`, a JSON boolean in
[config.json](config-file.md#modes-access-and-interface). The notification helper
selects an available host utility and invokes it in the current user environment.
Eirene does not run a separate notification daemon or maintain a delivery queue.
A scheduler can have a different desktop/session environment from the UI even
when it reads the same saved preference.

The conversation event log and scheduled run history remain the records of work;
a desktop notification is only a delivery surface. Their locations are listed in
[data layout](data-layout.md).
