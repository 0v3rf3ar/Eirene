#!/usr/bin/env bash
# Install the matching GitHub release without requiring Python or sudo.
set -Eeuo pipefail

path_only=0
if [[ "${1:-}" == --configure-shells ]]; then path_only=1; fi
# Keep logs readable when redirected; respect NO_COLOR and small terminals.
accent='' green='' dim='' reset=''
if [[ -t 1 && "${TERM:-dumb}" != dumb && -z "${NO_COLOR+x}" ]]; then
    accent=$'\033[36m' green=$'\033[32m' dim=$'\033[2m' reset=$'\033[0m'
fi
heading() { [[ "$path_only" == 1 ]] && return 0; printf '\n%s[%s/7]%s %s\n' "$accent" "$1" "$reset" "$2"; }
ok() { printf '%s[ok]%s %s\n' "$green" "$reset" "$*"; }
show_art() {
    if [[ -t 1 && ${COLUMNS:-80} -ge 56 ]]; then
        printf '%s' "$accent"
        cat <<'EIRENE_ART'
                    ⠠⠤⣤⣀⡀
                       ⠙⠻⣷⣄
         ⡀              ⣤⠈⠻⣷⡄  ⢰⣿
       ⠠⠊    ⡀⢀⡀⣤⣄⣀⣠⣶⣼⠿⠦⠈ ⠈⠙⠙⠂⠈⠙⠂
       ⡐⠤⠰⠖⠇⠐⠛⠉⠁⡈⠁⠉⠁⠁
      ⡰         ⣷⡀
     ⢰⡇    ⢰⡀ ⡀⢸⠘⣻⣤⣤⣀⣀⣀⢀     ⣀⣤⣄
     ⠘⡇⡆   ⣈⣳⣦⣵⡼⠋⠁⠈⠉⢉⣽⣿⣿⣿⣧⡀⢀⣼⣇⣻⣾⠆
       ⠹⢦⡀   ⠈⣿⣇    ⣼⣿⣿⣿⣿⣿⣿⣿⡋⣀⣼⠏      ⠠
         ⠈   ⣴⣿⣿⣷⣦⣴⣾⣿⣿⣿⣿⣿⣿⣿⠟⠁⠋⠁   ⠢    ⢆
            ⠘⣿⠿⠿⠿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣆⡟          ⠘⡄
          ⣼  ⠈⢷⣼⣿⣿⣿⣿⣿⣿⡿⣿⣿⣿⣿⣾⡇⡀  ⣰⡜⠃    ⠠⣹⡄
          ⠉    ⠹⣿⡿⠿⠛⠉⢁⣾⣿⣿⣿⣿⣿⣷⣇          ⢹⣿⡄
        ⣸  ⠰         ⣿⣿⣿⡿⣿⣿⣿⣟⢿⠄⠄         ⠻⣷
        ⢿⡀⡄          ⠸⣿⣟⣼⣿⣿⣿⣿⠂        ⢀ ⡀⢠⠘
        ⠈⡽⠁           ⢹⣿⣿⢿⠿⠟⠉    ⢀⣄   ⠈ ⠁ ⣇ ⣧
        ⠈⠁⣠⡆  ⠠⠃       ⣿⣿⣶⡆⠉             ⠠⠃⠘⠃
                   ⢀⣤⠖⣷⣿⠿⠋  ⣠⠔⠉          ⡀
          ⠤⠄⡠⠂     ⢾⠇⣼⠟⠁⠂ ⠊⠈⠁
           ⠈⠁      ⠈ ⠁
EIRENE_ART
        printf '%s\n' "$reset"
    fi
    printf '%sE I R E N E%s  /  terminal coding agent\n' "$accent" "$reset"
}
if [[ "$path_only" == 0 ]]; then printf 'E I R E N E  /  installer\n'; fi
initial_path=$PATH
heading 1 'Check this computer'

fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
warn() { printf 'warning: %s\n' "$*" >&2; }
step='checking this computer'
installed=0
trap 'status=$?; printf "error: failed while %s (exit %s).\n" "$step" "$status" >&2; if [[ "$installed" == 0 ]]; then printf "The existing executable has not been replaced. Fix the error above and rerun the installer.\n" >&2; fi; exit "$status"' ERR
repo='0v3rf3ar/Eirene'
version=${EIRENE_VERSION:-latest}
install_dir=${EIRENE_INSTALL_DIR:-"$HOME/.local/bin"}
case "$install_dir" in /*) ;; *) install_dir="$PWD/$install_dir" ;; esac
for tool in curl tar uname mktemp grep cp chmod mv mkdir cat sleep; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required"
done
case "$install_dir" in *$'\n'*|*$'\r'*|*:*) fail 'install directory must not contain newlines or a colon (PATH separator)' ;; esac
os_name=$(uname -s)
cpu=$(uname -m)
case "$os_name" in
    Linux)
        case "$cpu" in
            x86_64|amd64) target=Linux-amd64 ;;
            aarch64|arm64) target=Linux-arm64 ;;
            *) fail "unsupported Linux architecture: $cpu" ;;
        esac ;;
    Darwin)
        # uname may report x86_64 when Bash is running under Rosetta.
        if [[ "$cpu" != arm64 && "$cpu" != aarch64 ]] && [[ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" != 1 ]]; then
            fail 'the macOS release requires Apple Silicon'
        fi
        target=MacOS-silicon ;;
    MINGW*|MSYS*|CYGWIN*) fail 'on Windows, use install.ps1 from PowerShell' ;;
    *) fail "unsupported operating system: $os_name" ;;
esac
fetch() {
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 300 "$@"
}
if [[ "$path_only" == 0 ]]; then ok "$target · $install_dir"; fi
if [[ "$path_only" == 0 ]]; then
heading 2 'Find the release'
if [[ "$version" == latest ]]; then
    step='finding the latest release; check your connection to github.com'
    # Resolve the latest tag once before choosing the platform archive.
    resolved=$(fetch --head --output /dev/null --write-out '%{url_effective}' "https://github.com/$repo/releases/latest")
    version=${resolved##*/}
fi
[[ "$version" =~ ^v[0-9][A-Za-z0-9._+-]*$ ]] || fail "invalid release tag: $version (expected v followed by a version)"
ok "Release $version"
asset="eirene-$target-${version#v}.tar.gz"
base="https://github.com/$repo/releases/download/$version"
step='creating temporary files; check free disk space and temporary-directory permissions'
temporary=$(mktemp -d)
staged=''
cleanup() {
    rm -rf -- "$temporary" || warn "could not remove temporary files: $temporary"
    if [[ -n "$staged" ]]; then rm -f -- "$staged" || warn "could not remove staging file: $staged"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
heading 3 'Download'
show_art
printf 'Eirene %s for %s\n' "$version" "$target"
step="downloading $asset; check your connection and that release $version has an asset for $target"
# Curl owns a single live progress line below the portrait, including retries.
if [[ -t 2 && "${TERM:-dumb}" != dumb ]]; then
    curl --fail --show-error --location --proto '=https' --proto-redir '=https' \
        --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 300 \
        --progress-bar --output "$temporary/$asset" "$base/$asset"
else
    fetch --output "$temporary/$asset" "$base/$asset"
fi
[[ -s "$temporary/$asset" ]] || fail 'downloaded archive is empty'
ok 'Archive downloaded'
heading 4 'Unpack'
step='extracting the release archive'
tar -xzf "$temporary/$asset" -C "$temporary" eirene
[[ -f "$temporary/eirene" && ! -L "$temporary/eirene" ]] || fail 'archive does not contain a regular eirene executable'
ok 'Executable extracted'
heading 5 'Install the executable'
step="preparing $install_dir; check directory permissions and free disk space"
mkdir -p -- "$install_dir"
[[ ! -d "$install_dir/eirene" ]] || fail "$install_dir/eirene is a directory"
staged=$(mktemp "$install_dir/.eirene.XXXXXX")
cp -- "$temporary/eirene" "$staged"
chmod 755 "$staged"
step='checking the executable; check OS compatibility and whether the install directory allows execution'
"$staged" --version > "$temporary/version.txt" 2>&1 || {
    cat "$temporary/version.txt" >&2
    fail 'downloaded executable could not run; existing installation was not changed'
}
"$staged" --help > "$temporary/help.txt" 2>&1 || fail 'downloaded executable failed --help'
[[ -s "$temporary/version.txt" && -s "$temporary/help.txt" ]] || fail 'executable returned empty version or help output'
ok 'Staged executable responds to --version and --help'
step="replacing $install_dir/eirene"
mv -f -- "$staged" "$install_dir/eirene"
staged=''
installed=1
ok "Installed $install_dir/eirene"
else
    [[ -x "$install_dir/eirene" ]] || fail 'shell setup needs an installed executable'
    temporary=$(mktemp -d)
    trap 'rm -rf -- "$temporary"' EXIT
fi

# POSIX quoting also works in Bash and Zsh; never evaluate a user-supplied path.
quote() { local value=${1//\'/\'\\\'\'}; printf "'%s'" "$value"; }
path_line="case \":\$PATH:\" in *$(quote ":$install_dir:")*) ;; *) export PATH=$(quote "$install_dir"):\"\$PATH\" ;; esac"
launch_line=$(quote "$install_dir/eirene")
shell_name=${SHELL:-}
posix_line=$path_line
profiles=()
lines=()
detected=()
add_profile() { profiles+=("$1"); lines+=("$2"); }
has_shell() {
    local name=$1 candidate
    [[ "${shell_name##*/}" == "$name" ]] && return 0
    command -v "$name" >/dev/null 2>&1 && return 0
    if [[ -r /etc/shells ]]; then
        while IFS= read -r candidate; do
            [[ "$candidate" == /* && "${candidate##*/}" == "$name" && -x "$candidate" ]] && return 0
        done < /etc/shells
    fi
    return 1
}
# POSIX login configuration also covers sh, dash and ksh.
add_profile "$HOME/.profile" "$posix_line"
if has_shell bash; then
    detected+=(bash)
    add_profile "$HOME/.bashrc" "$posix_line"
    if [[ -f "$HOME/.bash_profile" ]]; then add_profile "$HOME/.bash_profile" "$posix_line"
    elif [[ -f "$HOME/.bash_login" ]]; then add_profile "$HOME/.bash_login" "$posix_line"
    elif [[ "$os_name" == Darwin ]]; then add_profile "$HOME/.bash_profile" "$posix_line"; fi
fi
if has_shell zsh; then
    detected+=(zsh)
    add_profile "${ZDOTDIR:-$HOME}/.zshrc" "$posix_line"
    add_profile "${ZDOTDIR:-$HOME}/.zprofile" "$posix_line"
fi
if has_shell fish; then
    detected+=(fish)
    fish_path=${install_dir//\\/\\\\}
    fish_path=${fish_path//\'/\\\'}
    add_profile "${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/eirene.fish" "contains -- '$fish_path' \$PATH; or set -gx PATH '$fish_path' \$PATH"
fi
for name in sh dash ksh; do
    if has_shell "$name"; then detected+=("$name"); fi
done
if has_shell ksh; then add_profile "$HOME/.kshrc" "$posix_line"; fi
for name in csh tcsh; do
    if has_shell "$name"; then
        detected+=("$name")
        csh_line="if ( \":\$PATH:\" !~ *$(quote ":$install_dir:")* ) set path = ( $(quote "$install_dir") \$path )"
        add_profile "$HOME/.${name}rc" "$csh_line"
    fi
done
if has_shell pwsh; then
    detected+=(pwsh)
    ps_path=${install_dir//\'/\'\'}
    add_profile "${XDG_CONFIG_HOME:-$HOME/.config}/powershell/profile.ps1" "if ((\$env:PATH -split [IO.Path]::PathSeparator) -cnotcontains '$ps_path') { \$env:PATH = '$ps_path' + [IO.Path]::PathSeparator + \$env:PATH }"
fi
if has_shell nu; then
    detected+=(nu)
    # Nushell double-quoted strings do not interpolate without a $ prefix.
    nu_path=${install_dir//\\/\\\\}
    nu_path=${nu_path//\"/\\\"}
    add_profile "${XDG_CONFIG_HOME:-$HOME/.config}/nushell/env.nu" "\$env.PATH = (\$env.PATH | prepend \"$nu_path\" | uniq)"
fi
heading 6 'Configure installed shells'
printf 'Detected: %s\n' "${detected[*]:-POSIX shell}"

add_path() {
    local profile=$1 path_line=$2 backup
    if [[ -e "$profile" && ! -f "$profile" ]]; then
        warn "not a regular profile: $profile"; return 1
    fi
    if grep -Fqx -- "$path_line" "$profile" 2>/dev/null; then
        printf 'PATH already configured in %s\n' "$profile"; return 0
    fi
    mkdir -p -- "${profile%/*}" || return 1
    if [[ -e "$profile" ]]; then
        backup=$(mktemp "$profile.eirene-backup.XXXXXX") || return 1
        cp -p -- "$profile" "$backup" || return 1
        printf 'Profile backup: %s\n' "$backup"
    fi
    printf '\n# Eirene\n%s\n' "$path_line" >> "$profile" || return 1
    grep -Fqx -- "$path_line" "$profile" || return 1
    ok "PATH saved to $profile"
}

path_ready=1
if [[ "${EIRENE_NO_PATH:-0}" != 1 ]]; then
    printf 'Configuring your shell…\n'
    for index in "${!profiles[@]}"; do
        profile=${profiles[$index]}
        if ! add_path "$profile" "${lines[$index]}"; then
            path_ready=0
            warn "Eirene is installed, but PATH could not be saved to $profile. Check permissions, then rerun the installer."
        fi
    done
else
    printf 'PATH setup skipped (EIRENE_NO_PATH=1).\n'
fi
heading 7 'Check the installed command'
step='verifying the installed command'
if [[ "${EIRENE_NO_PATH:-0}" != 1 ]]; then
    export PATH="$install_dir:$PATH"
    hash -r
    [[ "$(command -v eirene)" == "$install_dir/eirene" ]] || fail 'PATH resolves to a different eirene'
    if [[ "$path_only" == 0 ]]; then
        eirene --version
        ok 'eirene resolves on PATH and runs'
    fi
    if [[ -f "$HOME/.bashrc" ]] && command -v bash >/dev/null 2>&1; then
        printf 'Checking .bashrc (up to 2 seconds)…\n'
        # Job control gives the check its own process group. The watchdog can
        # stop the shell AND profile children on Linux/macOS without timeout(1).
        # Only resolve PATH here: another frozen-binary startup is unnecessary.
        verify_bash_profile() (
            set +e
            set -m
            PATH="$initial_path" bash --noprofile --norc +m -ic \
                'source "$1"; hash -r; [[ "$(type -P eirene)" == "$2/eirene" ]] && printf verified > "$3"' \
                bash "$HOME/.bashrc" "$install_dir" "$temporary/profile-verified" < /dev/null \
                > "$temporary/shell-check.txt" 2>&1 &
            shell_pid=$!
            (
                sleep 2
                printf 'timeout\n' > "$temporary/shell-timeout"
                kill -TERM -- "-$shell_pid" 2>/dev/null
                sleep 0.1
                kill -KILL -- "-$shell_pid" 2>/dev/null
            ) &
            watchdog_pid=$!
            wait "$shell_pid"
            result=$?
            # macOS can reap the shell on TERM while a profile child ignores
            # that signal. Let the timed-out watchdog finish its KILL phase
            # before returning; cancelling it here leaves those children alive.
            if [[ ! -f "$temporary/shell-timeout" ]]; then
                kill -TERM -- "-$watchdog_pid" 2>/dev/null
            fi
            wait "$watchdog_pid" 2>/dev/null
            exit "$result"
        )
        if verify_bash_profile > "$temporary/shell-watchdog.txt" 2>&1 &&
            [[ -f "$temporary/profile-verified" && ! -f "$temporary/shell-timeout" ]]; then
            ok 'Sourced .bashrc and verified eirene on PATH'
        else
            path_ready=0
            if [[ -f "$temporary/shell-timeout" ]]; then
                warn 'Bash startup exceeded 2 seconds; verification stopped. PATH is saved. Use the full launch command below.'
            else
                warn 'Bash startup verification failed; inspect .bashrc and use the full launch command below.'
            fi
        fi
    fi
elif [[ "$path_only" == 0 ]]; then
    "$install_dir/eirene" --version
    ok 'Installed command runs'
fi
if [[ "$path_only" == 1 ]]; then
    [[ "$path_ready" == 1 ]] || fail 'some shell profiles could not be configured or verified'
    ok 'Shell setup complete'
    exit 0
fi
printf '\nEirene %s installed\n%s/eirene\n\n' "$version" "$install_dir"
printf 'Start now:\n%s\n\n' "$launch_line"
if [[ "${EIRENE_NO_PATH:-0}" != 1 && ${#profiles[@]} -gt 0 ]]; then
    if [[ "$path_ready" == 1 ]]; then
        printf 'Open a new terminal and run: eirene\n'
    fi
    printf 'The installer cannot change its parent terminal. To use this terminal immediately, run:\n'
    if [[ "${shell_name##*/}" == bash && -f "$HOME/.bashrc" ]]; then
        printf 'source %s\n' "$(quote "$HOME/.bashrc")"
    elif [[ "${shell_name##*/}" == fish ]]; then
        printf 'source %s\n' "$(quote "${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/eirene.fish")"
    elif [[ "${shell_name##*/}" == zsh ]]; then
        printf 'source %s\n' "$(quote "${ZDOTDIR:-$HOME}/.zshrc")"
    else
        printf '%s\n' "$posix_line"
    fi
    printf 'eirene\n'
fi
printf '\nInside Eirene, use /connect to choose a provider and /help for commands.\n'
