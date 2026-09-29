#!/usr/bin/env bash
# Install the matching GitHub release without requiring Python or sudo.
set -Eeuo pipefail

printf '\n%s\n%s\n%s\n\n' \
    '┏━╸╻┏━┓┏━╸┏┓╻┏━╸' \
    '┣╸ ┃┣┳┛┣╸ ┃┗┫┣╸' \
    '┗━╸╹╹┗╸┗━╸╹ ╹┗━╸'

fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
warn() { printf 'warning: %s\n' "$*" >&2; }
step='checking this computer'
installed=0
trap 'status=$?; printf "error: failed while %s (exit %s).\n" "$step" "$status" >&2; if [[ "$installed" == 0 ]]; then printf "The existing executable has not been replaced. Fix the error above and rerun the installer.\n" >&2; fi; exit "$status"' ERR
repo='0v3rf3ar/Eirene'
version=${EIRENE_VERSION:-latest}
install_dir=${EIRENE_INSTALL_DIR:-"$HOME/.local/bin"}
case "$install_dir" in /*) ;; *) install_dir="$PWD/$install_dir" ;; esac
for tool in curl tar uname mktemp awk grep cp chmod mv mkdir; do
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
if [[ "$version" == latest ]]; then
    step='finding the latest release; check your connection to github.com'
    # Resolve once so a concurrent release cannot mix an archive and its checksum.
    resolved=$(fetch --head --output /dev/null --write-out '%{url_effective}' "https://github.com/$repo/releases/latest")
    version=${resolved##*/}
fi
[[ "$version" =~ ^v[0-9][A-Za-z0-9._+-]*$ ]] || fail "invalid release tag: $version (expected v followed by a version)"
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
printf 'Downloading Eirene %s for %s…\n' "$version" "$target"
step="downloading $asset; check your connection and that release $version has an asset for $target"
fetch --output "$temporary/$asset" "$base/$asset"
step='downloading release checksums'
fetch --output "$temporary/SHA256SUMS" "$base/SHA256SUMS"
printf 'Verifying download…\n'
step='verifying the downloaded archive'
expected=$(awk -v name="$asset" '$2 == name { print $1 }' "$temporary/SHA256SUMS")
[[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || fail "missing or invalid checksum for $asset"
if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$temporary/$asset" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
    actual=$(shasum -a 256 "$temporary/$asset" | awk '{print $1}')
else
    fail 'sha256sum or shasum is required to verify the download'
fi
[[ "$actual" == "$expected" ]] || fail 'checksum mismatch; existing installation was not changed'
step='extracting the release archive'
tar -xzf "$temporary/$asset" -C "$temporary" eirene
[[ -f "$temporary/eirene" && ! -L "$temporary/eirene" ]] || fail 'archive does not contain a regular eirene executable'
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
step="replacing $install_dir/eirene"
mv -f -- "$staged" "$install_dir/eirene"
staged=''
installed=1

# POSIX quoting also works in Bash and Zsh; never evaluate a user-supplied path.
quote() { local value=${1//\'/\'\\\'\'}; printf "'%s'" "$value"; }
path_line="case \":\$PATH:\" in *$(quote ":$install_dir:")*) ;; *) export PATH=$(quote "$install_dir"):\"\$PATH\" ;; esac"
launch_line=$(quote "$install_dir/eirene")
profiles=()
shell_name=${SHELL:-}
case "${shell_name##*/}" in
    bash)
        profiles+=("$HOME/.bashrc")
        if [[ -f "$HOME/.bash_profile" ]]; then profiles+=("$HOME/.bash_profile")
        elif [[ -f "$HOME/.bash_login" ]]; then profiles+=("$HOME/.bash_login")
        elif [[ -f "$HOME/.profile" || "$os_name" != Darwin ]]; then profiles+=("$HOME/.profile")
        else profiles+=("$HOME/.bash_profile"); fi ;;
    zsh) profiles+=("${ZDOTDIR:-$HOME}/.zshrc" "${ZDOTDIR:-$HOME}/.zprofile") ;;
    fish)
        profiles+=("${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/eirene.fish")
        fish_path=${install_dir//\\/\\\\}
        fish_path=${fish_path//\'/\\\'}
        path_line="contains -- '$fish_path' \$PATH; or set -gx PATH '$fish_path' \$PATH"
        launch_line="'$fish_path/eirene'" ;;
    sh|dash|ksh|'') profiles+=("$HOME/.profile") ;;
    *) warn "unrecognized shell ${SHELL:-unknown}; PATH must be configured manually" ;;
esac

add_path() {
    local profile=$1 backup
    if [[ -e "$profile" && ! -f "$profile" ]]; then
        warn "not a regular profile: $profile"; return 1
    fi
    if grep -Fqx -- "$path_line" "$profile" 2>/dev/null; then
        printf '  PATH already configured in %s\n' "$profile"; return 0
    fi
    mkdir -p -- "${profile%/*}" || return 1
    if [[ -e "$profile" ]]; then
        backup=$(mktemp "$profile.eirene-backup.XXXXXX") || return 1
        cp -p -- "$profile" "$backup" || return 1
        printf '  Profile backup: %s\n' "$backup"
    fi
    printf '\n# Eirene\n%s\n' "$path_line" >> "$profile" || return 1
    printf '  PATH added to %s\n' "$profile"
}

path_ready=1
if [[ "${EIRENE_NO_PATH:-0}" != 1 ]]; then
    printf 'Configuring your shell…\n'
    for profile in "${profiles[@]}"; do
        if ! add_path "$profile"; then
            path_ready=0
            warn "Eirene is installed, but PATH could not be saved to $profile. Check permissions, then rerun the installer."
        fi
    done
else
    printf 'PATH setup skipped (EIRENE_NO_PATH=1).\n'
fi
printf '\nEirene %s installed\n  %s/eirene\n\n' "$version" "$install_dir"
printf 'Start now:\n  %s\n\n' "$launch_line"
if [[ "${EIRENE_NO_PATH:-0}" != 1 && ${#profiles[@]} -gt 0 ]]; then
    if [[ "$path_ready" == 1 ]]; then
        printf 'Open a new terminal and run: eirene\n'
    fi
    printf 'To use this terminal immediately, run:\n  %s\n  eirene\n' "$path_line"
fi
printf '\nInside Eirene, use /connect to choose a provider and /help for commands.\n'
