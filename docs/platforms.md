# Platform support

Eirene gives local/API models host-specific command guidance and passes native host guidance to Codex and Claude Code. File/search/edit tools keep the same schema on each host.

| Host | Commands | Isolation |
| --- | --- | --- |
| Linux | Bash with pipefail, sh fallback | Bubblewrap |
| macOS | System Bash/sh, BSD utility guidance, BSD PTY launcher | sandbox-exec (required; no silent fallback) |
| Windows | CMD by default; powershell=true on run_command/start_process | Each native command needs explicit approval; no kernel isolation backend |

PowerShell is launched without profiles, noninteractively, with UTF-8 output and error/exit-code propagation. Install pwsh or Windows PowerShell to use it. Windows plan mode uses portable file/search tools; native command execution cannot guarantee read-only behavior. Headless Windows commands requiring approval fail closed. Codex and Claude Code continue to own their native tools and permission policies. Native Windows Claude Code requires approval for each turn without kernel isolation; plan mode disables command and edit tools. Use WSL2 for Claude sandboxing.

## Installer behavior

The Bash installer uses `~/.local/bin` on Linux and macOS. It detects the login
shell from `SHELL` and configures:

- Bash: `.bashrc` and the first existing `.bash_profile`, `.bash_login`, or
  `.profile`. With no existing login profile, it creates `.bash_profile` on
  macOS or `.profile` on Linux.
- Zsh: `.zshrc` and `.zprofile`, respecting `ZDOTDIR`.
- Fish: `fish/conf.d/eirene.fish`, respecting `XDG_CONFIG_HOME`.
- Sh, Dash, and Ksh: `.profile`.

Unrecognized shells receive manual setup guidance. Startup files are backed up
before modification; repeating installation does not add duplicate entries.
The printed full-path command works immediately, without restarting a shell.

Windows uses `%LOCALAPPDATA%\Programs\eirene` and persistent user PATH,
without administrator access. PowerShell also updates the current process PATH.
When run on Linux or macOS, the PowerShell installer updates PowerShell's
`CurrentUserAllHosts` profile; use `install.sh` for Bash, Zsh, or Fish setup.

Both installers support `EIRENE_INSTALL_DIR`, `EIRENE_VERSION`, and
`EIRENE_NO_PATH=1`. They verify the release checksum and run the staged binary
before replacing the installed executable. Errors identify the failed phase;
PATH failures leave a working executable and print recovery instructions.
Close running Eirene processes before updating on Windows.

## Build on the target machine

Use Python 3.10+ and Git for tests. From the repository root:

- Linux/macOS: `python3 build.py`
- Windows CMD or PowerShell: `py -3 build.py` (or `python build.py`)
- `python bulid.py` is also accepted for compatibility with that spelling.

The script creates a separate build environment per OS/architecture, installs dependencies, runs tests, packages with PyInstaller, then checks --version and --help. Output is dist/eirene or dist/eirene.exe. Build on each target OS/architecture; PyInstaller does not cross-compile. Internet is needed to install build dependencies. Existing unrelated dist files are preserved. With dependencies already installed, --no-install uses the current Python environment without contacting package servers. --dist-dir PATH selects a writable output directory; --work-dir PATH selects the temporary packaging directory. Use --test-only to validate without packaging and --skip-tests only when tests have already passed.

## Connections and animation

Slow streams show a waiting status after 15 seconds without model events. Codex willRetry and Claude Code api_retry events keep the existing turn alive and show reconnect details. Retryable API failures before content/tool activity use up to 12 attempts by default (config: retry_attempts, 1–100), with exponential delays capped at 60 seconds; Retry-After may require a longer wait. Escape cancels waits. Authentication, quota, and other permanent errors stop immediately. Exhausting attempts means recovery was unsuccessful, not proof of a permanent outage. A stalled native CLI turn or partially delivered answer is not automatically replayed, because it may have executed tools.

Each turn randomly selects braille, orbit, or wave animation. Accessible icons and reduced motion use a static marker.

Protocol references: [Codex app server](https://learn.chatgpt.com/docs/app-server), [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes), [Claude sandbox platforms](https://code.claude.com/docs/en/sandboxing).
