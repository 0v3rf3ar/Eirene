#!/usr/bin/env bash
# Install a matching desktop release or a package-managed Android/Termux release.
set -Eeuo pipefail

path_only=0
edge=0
for argument in "$@"; do
    case "$argument" in
        --configure-shells) path_only=1 ;;
        edge|--edge) edge=1 ;;
        *) printf 'error: unknown argument: %s\n' "$argument" >&2; exit 1 ;;
    esac
done
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
if [[ "$edge" == 1 ]]; then version=edge; fi
install_dir=${EIRENE_INSTALL_DIR:-"$HOME/.local/bin"}
case "$install_dir" in /*) ;; *) install_dir="$PWD/$install_dir" ;; esac
for tool in curl uname mktemp awk cat rm; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required"
done
case "$install_dir" in *$'\n'*|*$'\r'*|*:*) fail 'install directory must not contain newlines or a colon (PATH separator)' ;; esac
os_name=$(uname -s)
cpu=$(uname -m)
termux=0
if [[ "$os_name" == Android || -n "${TERMUX_VERSION:-}" || "${PREFIX:-}" == /data/data/com.termux/* ]]; then
    termux=1
    [[ "${PREFIX:-}" == /data/data/com.termux/files/usr ]] || fail 'Android installation requires the standard com.termux prefix'
    case "$cpu" in aarch64|arm64) target=Termux-aarch64 ;; *) fail "unsupported Termux architecture: $cpu (ARM64 is required)" ;; esac
    [[ -z "${EIRENE_INSTALL_DIR:-}" || "$EIRENE_INSTALL_DIR" == "$PREFIX/bin" ]] || fail 'Termux packages install in $PREFIX/bin; custom EIRENE_INSTALL_DIR is unsupported'
    install_dir="$PREFIX/bin"
    for tool in apt-get dpkg-deb dpkg dpkg-query sha256sum; do
        command -v "$tool" >/dev/null 2>&1 || fail "$tool is required in Termux"
    done
    if [[ "$path_only" == 1 ]]; then
        command -v eirene >/dev/null 2>&1 || fail 'shell setup needs an installed executable'
        ok 'Termux manages PATH; no shell profile changes are needed'
        exit 0
    fi
else
for tool in tar grep cp chmod mv mkdir sleep ps; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required"
done
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
fi
fetch() {
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --retry 3 --retry-delay 2 --connect-timeout 30 --max-time 600 "$@"
}
# Read top-level release fields and uploaded asset names without confusing
# nested uploader metadata or braces inside JSON strings with release fields.
# This keeps installation independent of Python and jq.
release_metadata() {
    awk -v target="$metadata_target" -v prerelease_only="$prerelease_only" '
    function field(name, source, value) {
        value = source
        if (!match(value, "\"" name "\"[[:space:]]*:[[:space:]]*\"[^\"]*\"")) return ""
        value = substr(value, RSTART, RLENGTH)
        sub(/^[^:]*:[[:space:]]*"/, "", value)
        sub(/"$/, "", value)
        return value
    }
    {
        for (i = 1; i <= length($0); i++) {
            c = substr($0, i, 1)
            if (depth == 1) object = object c
            if (in_assets && depth == 2) asset = asset c
            if (quoted) {
                if (escaped) escaped = 0
                else if (c == "\\") escaped = 1
                else if (c == "\"") quoted = 0
                continue
            }
            if (c == "\"") { quoted = 1; continue }
            if (c == "[" && depth == 1 && object ~ /"assets"[[:space:]]*:[[:space:]]*\[$/) in_assets = 1
            if (c == "]" && depth == 1) in_assets = 0
            if (c == "{") {
                depth++
                if (depth == 1) { object = ""; names = "\n"; in_assets = 0 }
                if (in_assets && depth == 2) asset = ""
            }
            if (c == "}") {
                if (in_assets && depth == 2 && field("state", asset) == "uploaded") names = names field("name", asset) "\n"
                depth--
                if (depth == 0) {
                    count++
                    release_tag = field("tag_name", object)
                    expected = "eirene-" target "-" substr(release_tag, 2) ".deb"
                    if (object ~ /"draft"[[:space:]]*:[[:space:]]*false/ &&
                        (!prerelease_only || object ~ /"prerelease"[[:space:]]*:[[:space:]]*true/) &&
                        (target == "" || index(names, "\n" expected "\n"))) {
                        date = field("published_at", object)
                        if (date > newest) { newest = date; tag = release_tag }
                    }
                }
            }
        }
    }
    END { print count+0, newest, tag }'
}
if [[ "$path_only" == 0 ]]; then ok "$target · $install_dir"; fi
if [[ "$path_only" == 0 ]]; then
heading 2 'Find the release'
if [[ "$version" == edge || ("$termux" == 1 && "$version" == latest) ]]; then
    step='finding the latest compatible release'
    metadata_target='' prerelease_only=1
    if [[ "$termux" == 1 ]]; then
        metadata_target=$target
        if [[ "$version" == latest ]]; then prerelease_only=0; fi
    fi
    page=1 newest='' candidate=''
    while :; do
        metadata=$(fetch "https://api.github.com/repos/$repo/releases?per_page=100&page=$page")
        read -r count published tag <<< "$(printf '%s\n' "$metadata" | release_metadata)"
        if [[ -n "$tag" && "$published" > "$newest" ]]; then newest=$published; candidate=$tag; fi
        [[ "$count" == 100 ]] || break
        page=$((page + 1))
    done
    if [[ -z "$candidate" ]]; then
        if [[ "$termux" == 1 ]]; then fail 'no compatible published Termux package is available'; fi
        fail 'no published unstable release is available'
    fi
    version=$candidate
elif [[ "$version" == latest ]]; then
    step='finding the latest release; check your connection to github.com'
    # Resolve the latest tag once before choosing the platform archive.
    resolved=$(fetch --head --output /dev/null --write-out '%{url_effective}' "https://github.com/$repo/releases/latest")
    version=${resolved##*/}
fi
[[ "$version" =~ ^v[0-9][A-Za-z0-9._+-]*$ ]] || fail "invalid release tag: $version (expected v followed by a version)"
ok "Release $version"
asset="eirene-$target-${version#v}.tar.gz"
if [[ "$termux" == 1 ]]; then
    asset="eirene-$target-${version#v}.deb"
    printf 'Android/Termux package channel: newest compatible release (may be a beta).\n'
fi
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
        --retry 3 --retry-delay 2 --connect-timeout 30 --max-time 600 \
        --progress-bar --output "$temporary/$asset" "$base/$asset"
else
    fetch --output "$temporary/$asset" "$base/$asset"
fi
[[ -s "$temporary/$asset" ]] || fail 'downloaded archive is empty'
ok 'Archive downloaded'

if [[ "$termux" == 1 ]]; then
    heading 4 'Verify the Android package'
    step='verifying the Termux package checksum'
    fetch --output "$temporary/SHA256SUMS" "$base/SHA256SUMS"
    expected=$(awk -v wanted="$asset" '
        ($2 == wanted || $2 == "*" wanted) && length($1) == 64 && $1 ~ /^[[:xdigit:]]+$/ {
            count++; checksum = tolower($1)
        }
        END { if (count != 1) exit 1; print checksum }
    ' "$temporary/SHA256SUMS") || fail 'release must contain one valid checksum for the Termux package'
    actual=$(sha256sum "$temporary/$asset")
    [[ "${actual%% *}" == "$expected" ]] || fail 'Termux package checksum mismatch; existing installation was not changed'
    package_version=$(dpkg-deb --field "$temporary/$asset" Version)
    expected_version=${version#v}
    if [[ "$expected_version" =~ ^([0-9]+\.[0-9]+\.[0-9]+)(a|b|rc)([0-9]+)$ ]]; then
        expected_version="${BASH_REMATCH[1]}~${BASH_REMATCH[2]}${BASH_REMATCH[3]}"
    fi
    [[ "$(dpkg-deb --field "$temporary/$asset" Package)" == eirene &&
       "$(dpkg-deb --field "$temporary/$asset" Architecture)" == aarch64 &&
       "$package_version" == "$expected_version" ]] || fail 'Termux package metadata does not match this release and architecture'
    current=$(dpkg-query -W '-f=${Status}\n${Version}\n' eirene 2>/dev/null || true)
    if [[ "${current%%$'\n'*}" == 'install ok installed' ]] &&
        dpkg --compare-versions "${current##*$'\n'}" gt "$package_version"; then
        fail "a newer Eirene package is already installed (${current##*$'\n'}); refusing to downgrade"
    fi
    ok 'Checksum, package identity, architecture and version verified'
    heading 5 'Install or update Eirene with Termux APT'
    step='refreshing Termux package indexes'
    apt-get update
    step='installing or upgrading the Eirene package and its dependencies'
    # APT may already have changed package state if installation fails.
    installed=1
    DEBIAN_FRONTEND=noninteractive apt-get install -y -- "$temporary/$asset"
    heading 6 'Use the Termux-managed command path'
    export PATH="$PREFIX/bin:$PATH"
    hash -r
    command -v eirene >/dev/null 2>&1 || fail 'eirene was not found after package installation'
    heading 7 'Check the installed command'
    step='verifying the installed Termux command'
    output=$(eirene --version)
    [[ "$output" == "eirene ${version#v}" ]] || fail "unexpected installed version: $output"
    eirene --help > /dev/null
    ok "Eirene ${version#v} installed or updated"
    printf '\nStart now: eirene\nRerun this installer to update the Android package.\n'
    exit 0
fi
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
        printf 'Checking .bashrc (up to 4 seconds)…\n'
        # Job control gives the check its own process group. Interactive startup
        # and profiles can create additional groups, so snapshot descendants
        # before signalling the shell; their parent links disappear on exit.
        # Only resolve PATH here: another frozen-binary startup is unnecessary.
        verify_bash_profile() (
            set +e
            set -m
            PATH="$initial_path" bash --noprofile --norc +m -ic \
                'set +m; source "$1"; hash -r; [[ "$(type -P eirene)" == "$2/eirene" ]] && printf verified > "$3"' \
                bash "$HOME/.bashrc" "$install_dir" "$temporary/profile-verified" < /dev/null \
                > "$temporary/shell-check.txt" 2>&1 &
            shell_pid=$!
            (
                sleep 4
                printf 'timeout\n' > "$temporary/shell-timeout"
                ps -axo pid=,ppid= | awk -v root="$shell_pid" '
                    { parent[$1] = $2 }
                    END {
                        descendant[root] = 1
                        do {
                            changed = 0
                            for (pid in parent) {
                                if (!descendant[pid] && descendant[parent[pid]]) {
                                    descendant[pid] = 1
                                    print pid
                                    changed = 1
                                }
                            }
                        } while (changed)
                    }
                ' > "$temporary/profile-children"
                while read -r child_pid; do
                    kill -TERM "$child_pid" 2>/dev/null
                done < "$temporary/profile-children"
                kill -TERM -- "-$shell_pid" 2>/dev/null
                sleep 0.1
                kill -KILL -- "-$shell_pid" 2>/dev/null
                while read -r child_pid; do
                    kill -KILL "$child_pid" 2>/dev/null
                done < "$temporary/profile-children"
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
                warn 'Bash startup exceeded 4 seconds; verification stopped. PATH is saved. Use the full launch command below.'
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
