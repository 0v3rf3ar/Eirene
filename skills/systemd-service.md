---
name: systemd-service
description: Run something as a systemd user service or timer on Linux, without root.
---

Use this whenever the user wants something to run in the background, on boot, or on
a schedule, on a Linux machine.

## Where the files go

User units live in `~/.config/systemd/user/`. Never write to `/etc/systemd/system`
unless the user explicitly asks for a system unit and accepts using sudo.

## A service

```ini
[Unit]
Description=<one line, what it does>
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/<project>
ExecStart=%h/<project>/.venv/bin/python -m <module>
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

`ExecStart` must be an absolute path. `%h` expands to the home directory. A bare
command name will not be found.

## A timer

Pair `thing.service` (with `Type=oneshot`) and `thing.timer`:

```ini
[Unit]
Description=<what it does> schedule

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`Persistent=true` runs a missed job after the machine wakes up. Check an expression
with `systemd-analyze calendar "<expr>"` before installing it.

## Installing

```sh
systemctl --user daemon-reload
systemctl --user enable --now thing.service   # or thing.timer
```

## Checking

```sh
systemctl --user status thing.service
journalctl --user -u thing.service -n 50 --no-pager
systemctl --user list-timers --no-pager
```

Never use `journalctl -f`; it never returns. Always pass `-n <count>` and
`--no-pager`.

## The lingering trap

User units stop when the last session of that user ends. If the job must survive
logout or run on boot with nobody logged in, tell the user to run:

```sh
loginctl enable-linger $USER
```

Say this out loud rather than silently enabling it, because it changes how their
account behaves.
