# Android / Termux

[Documentation](README.md) / Android / Termux

Eirene has an experimental ARM64 package for the standard F-Droid/GitHub
`com.termux` app. Most core workflows work in the terminal: provider connections,
chat, project inspection and editing, approved shell commands, tests and builds
using available tools, sessions, plans, user-installed skills, and compatible
plugins. External tools, provider CLIs, and MCP servers still need Android-compatible
installations; not every desktop dependency is available in Termux.

## Install and update

Run in Termux:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.sh)
```

The installer selects the newest published release containing a compatible
Termux package, including betas. It verifies the checksum and package metadata,
then uses Termux APT to install or upgrade Eirene and its dependencies, including
the required Python runtime. It uses `$PREFIX/bin` without editing shell profiles.
Only ARM64 and the standard `/data/data/com.termux/files/usr` prefix are supported.

Rerun the same installer command to update. It refuses to downgrade an installed
newer version. `/update` inside Eirene points to the installer on Termux.
To select a specific compatible release, set `EIRENE_VERSION` before running it;
see [installation options](installation.md#choose-a-directory-or-version).

Then open your project:

```sh
eirene --version
cd ~/my-project
eirene
```

Use `/connect` to configure a provider. Files and commands are limited by what
your Termux app can access. Eirene uses the tools installed in that environment;
it does not include project compilers or optional external servers.

## No Eirene command sandbox

Eirene does **not** provide a command sandbox on Termux. Its Linux Bubblewrap
backend is unavailable there. Command approval is a permission decision, not
filesystem or network isolation: an approved command runs with your Termux
account's access and can affect files outside the current project.

With the default automatic isolation setting, arbitrary shell commands, background
processes, and language diagnostics require individual approval, including in
auto mode. Plan mode blocks arbitrary commands and supports the fixed file/search
tools instead. Android's app-level restrictions still apply, but they do not
isolate an approved command from the rest of your Termux environment. Explicit
full-access settings can relax Eirene's approval behavior; see
[modes and permissions](harness.md).

Plugins work the same way. Installing a plugin never runs its code. A plugin's
hooks run only after `/plugins trust NAME`, and its MCP servers only after you
enable each one in `/mcp`. On Android those explicit choices take the place of a
sandbox: trusted hooks and enabled MCP servers run with your Termux account's
access, and the trust prompt, `/plugins doctor`, and `/mcp` say so. Plugins need
their own tools from Termux packages, such as `git` to install, `node` for
Ponytail and Playwright, and `uv` for Serena. Browser automation additionally
needs a browser that runs in your Android environment.

Desktop scheduling is unsupported. Browser automation, notifications, clipboard
integration, and other desktop features depend on software and integrations
available in your Android environment.

## Companion and graphical terminals

The graphical companion does **not** work in the standard Termux terminal.
Ordinary text interaction works without it.

To use the companion on Android, you need a GUI environment, such as
[Termux:X11](https://github.com/termux/termux-x11), and an image-capable graphical
terminal, such as a compatible installation of Kitty. Launch Eirene inside that
terminal in the GUI session. Kitty implements the
[Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/);
Eirene can also use a compatible Sixel renderer. Installing a GUI alone does not
add image support to the standard Termux terminal.

Termux:X11 requires its Android app and Termux-side package; follow its upstream
setup instructions for your device. Availability of a compatible graphical
terminal depends on the environment you install. This GUI/companion setup has
not been validated on a physical Android device.

In a supported terminal, enable the companion with:

```text
/companion on
```

The command is shown only when Eirene detects a supported image renderer. The
companion is disabled by default and is also hidden by `NO_COLOR`,
`--no-color`, or accessible icons. See [appearance settings](appearance.md).

## Validation

The package is built and smoke-tested in the official Termux Docker container,
covering native imports, CLI startup, diagnostics, shell execution, file reads,
and the terminal UI. These checks exercise Android/Bionic userspace; they do not
replace physical Android device testing. See [platform support](platforms.md)
for the current release-build scope.
