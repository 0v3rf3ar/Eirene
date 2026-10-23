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
| Android / Termux (experimental) | ARM64 | `$PREFIX/bin` |

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

## Android / Termux

See the [Android / Termux guide](android-termux.md) for supported workflows,
command sandbox limitations, and graphical companion requirements.

In the standard F-Droid/GitHub `com.termux` app on ARM64, run:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.sh)
```

The installer selects the newest published release containing an uploaded Termux
package, including betas. It verifies the release checksum and package metadata,
then uses Termux APT to install or upgrade Eirene and its dependencies. Rerun the
same command to update; an installed newer version will not be downgraded.
`EIRENE_VERSION` can select a specific tag with a Termux package; `edge` restricts
selection to prereleases.

Termux manages the command path, so no shell profiles are changed. The package
requires the standard `/data/data/com.termux/files/usr` prefix; custom installation
directories and other Android architectures are unsupported. See
[platform support](platforms.md#experimental-android--termux-beta) for limitations.

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

The desktop installers accept the following environment variables. On Termux,
the installation directory is fixed and shell profile configuration is unnecessary.

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

For desktop archives, the Bash installer checks the downloaded executable but
does not verify release checksums. Its Termux branch and the PowerShell installer
verify release checksums. When doing
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

## Running the Python source tree

The package requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From a checkout, sync the locked dependencies and launch the application:

```sh
uv sync --locked
uv run --locked eirene -C /absolute/path/to/project
```

These commands also work on Windows. uv manages the local `.venv` automatically.
Dependencies are declared in `pyproject.toml` and resolved versions are saved in
`uv.lock`. The default sync includes development and build tools. Use
`uv sync --locked --no-dev` for runtime dependencies only.

For development and standalone builds:

```sh
uv run --locked pytest
uv run --locked ruff check .
uv run --locked mypy
uv run --locked python build.py --no-install
```

`python build.py` also syncs the uv environment before running tests and building.
CI installs Bubblewrap for Linux sandbox tests, then runs lint, type checks,
and the full test suite on Python 3.14 before
building native binaries for Linux AMD64/ARM64, macOS Apple Silicon, and Windows
AMD64. Packaging uses Python 3.14 with an explicit interpreter check and
`uv sync --locked --no-dev --group build`; each executable and extracted release
archive is smoke-tested before upload.
After changing dependencies with `uv add` or `uv add --dev`, commit both
`pyproject.toml` and `uv.lock`.

A standalone release bundles its Python runtime; a source installation uses the
interpreter/environment you chose. Neither supplies project compilers or MCP
server dependencies. `/update` does not update an editable Python checkout.

The command wrapper, source checkout, and data directory are separate. See
[data layout](data-layout.md) for their structure and [config.json](config-file.md)
for persistence and an alternate `EIRENE_HOME`.
