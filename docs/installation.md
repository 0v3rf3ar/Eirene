# Installation

[Documentation](README.md) / Installation

Install a standalone release to use Eirene without setting up Python. The
installer selects an archive for your operating system and processor, checks the
executable, and installs it in your user account.

## Supported release downloads

| System | Processor | Default installation directory |
| --- | --- | --- |
| Linux | AMD64 or ARM64 | `~/.local/bin` |
| macOS | Apple Silicon / ARM64 | `~/.local/bin` |
| Windows | AMD64 | `%LOCALAPPDATA%\Programs\eirene` |

A release for one system cannot run on another. Intel macOS does not have a
matching standalone archive in this release set. See [platform support](platforms.md)
for command execution requirements after installation.

## Linux and macOS

Run this in Bash, or a shell that can launch Bash:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.sh)
```

The installer configures PATH in detected supported shell profiles and backs up
existing profiles before changing them. It prints a command to refresh the shell;
run that command or open a new terminal. Its verification shell cannot change the
environment of your current terminal.

## Windows

Run this in PowerShell:

```powershell
irm https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.ps1 | iex
```

Administrator access is not required for the default user installation. The
installer updates your user PATH and refreshes the current PowerShell process.
Other open terminal windows may need to be restarted. Close Eirene before
replacing an existing Windows executable.

## Verify and start

```sh
eirene --version
eirene --help
eirene -C /path/to/project
```

On Windows, quote a directory containing spaces:

```powershell
eirene -C "C:\Users\you\Projects\My App"
```

Inside Eirene, enter `/connect`. The [first-session guide](getting-started.md)
walks through connection, modes, and a small task.

## Choose a directory or version

Both installers accept the following environment variables.

| Variable | Purpose |
| --- | --- |
| `EIRENE_INSTALL_DIR` | Choose the executable directory. |
| `EIRENE_VERSION` | Choose a release tag instead of the latest release. |
| `EIRENE_NO_PATH=1` | Install without changing shell profiles or PATH. |
| `NO_COLOR=1` | Disable installer colors. |

For example, install to a directory you manage yourself:

```sh
export EIRENE_INSTALL_DIR="$HOME/bin"
export EIRENE_NO_PATH=1
bash <(curl -fsSL https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.sh)
```

In PowerShell:

```powershell
$env:EIRENE_INSTALL_DIR = "$env:LOCALAPPDATA\Programs\eirene"
$env:EIRENE_NO_PATH = "1"
irm https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.ps1 | iex
```

For a specific release, set `EIRENE_VERSION` to an actual tag listed on the
[releases page](https://github.com/0v3rf3ar/Eirene/releases) before running the
installer. These variables affect installation; `EIRENE_HOME` controls application
data separately, as described in [configuration](configuration.md).

## Manual download

Download the archive for your system from the releases page, extract it, and put
`eirene` or `eirene.exe` in a directory on PATH. On Linux and macOS, ensure the
file is executable with `chmod +x /path/to/eirene`. Run `--version` before use.

The Bash installer checks the downloaded executable but does not verify release
checksums. The PowerShell installer also verifies release checksums. When doing
manual verification, use the checksums supplied with the same release.

## If the command is missing

Try the executable by its full path:

```sh
~/.local/bin/eirene --version
```

```powershell
& "$env:LOCALAPPDATA\Programs\eirene\eirene.exe" --version
```

If this works, installation succeeded and PATH needs refreshing. Open a new
terminal or follow the installer's printed recovery instructions. See
[troubleshooting](troubleshooting.md) for platform and permission errors, and
[updates](updates.md) for replacing an existing release.
