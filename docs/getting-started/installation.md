# Installation

[Documentation](../README.md) / Getting started / Installation

Eirene is distributed as a single executable. The installer picks the right build
for your computer, verifies its SHA-256 checksum, checks that it runs, and installs
it for your user account. You do not need Python or administrator rights.

## Supported systems

| System | Processor | Installed to |
| --- | --- | --- |
| Linux | AMD64 or ARM64 | `~/.local/bin` |
| macOS | Apple Silicon | `~/.local/bin` |
| Windows | AMD64 | `%LOCALAPPDATA%\Programs\eirene` |

Intel Macs have no build. Eirene also relies on your system's shell and sandbox;
[Platform support](../platforms/platform-support.md) lists what each system needs.

## Install on Linux or macOS

Run this in a terminal:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.sh)
```

The installer adds `~/.local/bin` to `PATH` in each shell profile it finds, after
backing up the profile. A running shell cannot pick that change up by itself, so the
installer finishes by printing the command that refreshes yours, such as
`source ~/.bashrc`. Opening a new terminal works too.

On Linux, the installer also starts an empty Bubblewrap sandbox, the same kind Eirene
uses to run commands. If that fails, it tells you why and how to fix it: usually a
package to install or a `sysctl` setting to change. It never runs `sudo` for you, and
Eirene is installed either way. You can repeat the check at any time with `/sandbox`.

## Install on Windows

Run this in PowerShell:

```powershell
irm https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.ps1 | iex
```

The installer updates your user `PATH` and the current PowerShell session. Terminals
that were already open keep their old `PATH` until you restart them. If you are
replacing an existing copy, the installer waits for Eirene to close.

## Check the installation

```sh
eirene --version
eirene --doctor
```

`--doctor` prints a short read-only report on your data directory, configuration and
sandbox tools. Continue to [Your first session](first-session.md) when both commands
work.

If your shell reports that `eirene` is not found, run it by its full path:

```sh
~/.local/bin/eirene --version
```

```powershell
& "$env:LOCALAPPDATA\Programs\eirene\eirene.exe" --version
```

If that works, Eirene is installed and only `PATH` needs refreshing, so open a new
terminal.

## Install a prerelease

Prereleases contain the newest changes and may be less stable.

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.sh) edge
```

```powershell
$installer = irm https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.ps1
& ([scriptblock]::Create($installer)) -Edge
```

If Eirene is already installed, run `/update edge` inside it instead. See
[Updating](updating.md).

## Installer options

Set these environment variables before running the installer:

| Variable | Effect |
| --- | --- |
| `EIRENE_INSTALL_DIR` | Install the executable to this directory. |
| `EIRENE_VERSION` | Install this release tag instead of the latest stable release. |
| `EIRENE_NO_PATH=1` | Leave shell profiles and `PATH` unchanged. |
| `NO_COLOR=1` | Turn off colors in the installer's output. |

For example, to install to a directory you manage yourself:

```sh
export EIRENE_INSTALL_DIR="$HOME/bin"
export EIRENE_NO_PATH=1
bash <(curl -fsSL https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.sh)
```

```powershell
$env:EIRENE_INSTALL_DIR = "$env:LOCALAPPDATA\Programs\eirene"
$env:EIRENE_NO_PATH = "1"
irm https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.ps1 | iex
```

Release tags are listed on the
[releases page](https://github.com/0v3rf3ar/Eirene/releases).

These variables only affect where the program goes. Your settings and sessions live
in a separate [data directory](../reference/data-directory.md), which reinstalling
does not touch.

## Install manually

1. Download the archive for your system from the
   [releases page](https://github.com/0v3rf3ar/Eirene/releases), along with the
   `SHA256SUMS` file from the same release.
2. Compare the archive's checksum with the matching line in `SHA256SUMS`.
3. Extract `eirene` or `eirene.exe` to a directory on your `PATH`.
4. On Linux and macOS, make it executable with `chmod +x eirene`.
5. Run `eirene --version`.

## Uninstall

1. Delete any [routines](../automation/routines.md) you created, using `/routines`,
   so that nothing is left in your system scheduler.
2. Delete the executable.
3. If you do not want to keep your settings and conversations, delete the
   [data directory](../reference/data-directory.md).

Linux and macOS shell profiles keep the `PATH` line the installer added. It does no
harm, and you can remove it by hand.

**Next:** [Your first session](first-session.md)
