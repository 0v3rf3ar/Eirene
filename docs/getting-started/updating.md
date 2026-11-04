# Updating

[Documentation](../README.md) / Getting started / Updating

Eirene updates from its [GitHub releases](https://github.com/0v3rf3ar/Eirene/releases).
There are two channels:

| Channel | Contains | Commands |
| --- | --- | --- |
| Stable | Full releases only. | `/update check`, `/update` |
| Edge | The newest published version, including alpha, beta and release candidates. | `/update edge check`, `/update edge` |

The commands ending in `check` report whether a newer version exists without installing
it. Edge applies only to the command you run: startup checks stay on the stable channel.
Eirene never installs a draft and never downgrades.

## Update on Linux and macOS

```text
/update
```

A card follows each step: the versions involved, the download, checksum verification
and installation. When it finishes, run `/restart`. Eirene starts the new version and
reopens your current session.

Until you restart, the running process keeps using the old program. If any step fails,
the card shows the error and your installed copy stays as it was. To confirm the result,
run `eirene --version`.

## Update on Windows

Windows locks a running `eirene.exe`, so Eirene cannot replace itself. On Windows,
`/update` shows a PowerShell command and copies it to your clipboard when it can. It
looks like this:

```powershell
& ([scriptblock]::Create((irm 'https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.ps1'))) -Version 'v0.2.1' -InstallDir 'C:\Users\you\AppData\Local\Programs\eirene' -NoPathUpdate
```

Run it in any PowerShell window, before or after you exit Eirene. It installs exactly
the release that `/update` found into the folder Eirene runs from, verifies the
checksum, and waits up to 30 minutes for every running copy to close before replacing
the file. Your `PATH`, sessions and settings do not change.

## Update with the installer

The [installer commands](installation.md) also replace an existing copy. To stay in a
custom location or install a specific version, set `EIRENE_INSTALL_DIR` and
`EIRENE_VERSION` as you did the first time.

## Turn off update checks

Eirene checks for a new stable release at startup and only tells you about it. To turn
this off, set `check_updates` to `false` in
[`config.json`](../reference/configuration.md), or set `EIRENE_NO_UPDATE_CHECK` before
launching. `/update check` keeps working.

## What an update changes

An update replaces the executable and nothing else. Your projects, settings and
sessions are stored separately; see [Data directory](../reference/data-directory.md).

Plugins update separately, with `/plugins update`. See
[Plugins](../extending/plugins.md#update-a-plugin).

If a new version misbehaves, please
[report it](../help/reporting-issues.md). To go back in the meantime, reinstall the
previous version by setting `EIRENE_VERSION` to its release tag.
