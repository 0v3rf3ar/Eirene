# Updates

[Documentation](README.md) / Updates

Eirene can check GitHub releases and update a standalone installation. Update
checks are separate from the model's tools and execution permissions.

## Check without installing

```text
/update check
```

The result reports whether a newer release is available. Startup checks are
enabled by default. Set `check_updates` to `false` in configuration, or set
`EIRENE_NO_UPDATE_CHECK` before launch, to disable automatic startup checks.

## Install an update

```text
/update
```

Eirene checks the release, downloads the matching asset, and attempts installation.
Follow the result's restart instructions. If an update is already installed or
scheduled, exit and restart before asking for another update.

An active standalone process continues running its existing program until restart.
On Windows, replacing an in-use executable can require exit. Download, verification,
or write failures are reported; do not assume the version changed until a new
process confirms it.

```sh
eirene --version
```

## Use the installer again

The original [installer commands](installation.md) can also replace an existing
installation. Close Eirene first on Windows. Use the same installation directory
and a real `EIRENE_VERSION` release tag when you want a specific version rather
than the latest one.

An update replaces the executable, not your project. Application data is stored
separately; back it up before a version change when you need a recoverable copy.
A custom or source installation may receive manual replacement instructions
instead of an in-place update.

## Plugin updates are separate

`/plugins refresh NAME` reindexes files already installed; it does not download
upstream changes. Eirene has no automatic plugin upgrade or removal slash command.
See [plugin management](plugins.md) for safely replacing a bundle and reactivating
its executable capabilities.
