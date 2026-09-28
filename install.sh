#!/usr/bin/env bash
# Install the matching GitHub release without requiring Python or sudo.
set -euo pipefail

printf '\n%s\n%s\n%s\n\n' \
    '┏━╸╻┏━┓┏━╸┏┓╻┏━╸' \
    '┣╸ ┃┣┳┛┣╸ ┃┗┫┣╸' \
    '┗━╸╹╹┗╸┗━╸╹ ╹┗━╸'

fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
repo='0v3rf3ar/Eirene'
version=${EIRENE_VERSION:-latest}
install_dir=${EIRENE_INSTALL_DIR:-"$HOME/.local/bin"}
case "$install_dir" in /*) ;; *) install_dir="$PWD/$install_dir" ;; esac
for tool in curl tar uname mktemp awk grep; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required"
done
case "$install_dir" in *$'\n'*|*$'\r'*) fail 'install directory must not contain newlines' ;; esac
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
    # Resolve once so a concurrent release cannot mix an archive and its checksum.
    resolved=$(fetch --head --output /dev/null --write-out '%{url_effective}' "https://github.com/$repo/releases/latest")
    version=${resolved##*/}
fi
[[ "$version" =~ ^v[0-9][A-Za-z0-9._+-]*$ ]] || fail "invalid release tag: $version (expected v followed by a version)"
asset="eirene-$target-${version#v}.tar.gz"
base="https://github.com/$repo/releases/download/$version"
temporary=$(mktemp -d)
staged=''
cleanup() {
    rm -rf -- "$temporary"
    if [[ -n "$staged" ]]; then rm -f -- "$staged"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'Downloading Eirene %s for %s…\n' "$version" "$target"
fetch --output "$temporary/$asset" "$base/$asset"
fetch --output "$temporary/SHA256SUMS" "$base/SHA256SUMS"
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
tar -xzf "$temporary/$asset" -C "$temporary" eirene
[[ -f "$temporary/eirene" && ! -L "$temporary/eirene" ]] || fail 'archive does not contain a regular eirene executable'
mkdir -p -- "$install_dir"
[[ ! -d "$install_dir/eirene" ]] || fail "$install_dir/eirene is a directory"
staged=$(mktemp "$install_dir/.eirene.XXXXXX")
cp -- "$temporary/eirene" "$staged"
chmod 755 "$staged"
"$staged" --version
mv -f -- "$staged" "$install_dir/eirene"
staged=''
printf 'Installed to %s/eirene\n' "$install_dir"
if [[ "${EIRENE_NO_PATH:-0}" != 1 ]]; then
    case ":$PATH:" in
        *":$install_dir:"*) ;;
        *)
            case "${SHELL:-/bin/bash}" in
                */zsh) profile="${ZDOTDIR:-$HOME}/.zshrc" ;;
                */bash) profile="$HOME/.bashrc" ;;
                *) profile="$HOME/.profile" ;;
            esac
            path_line=$(printf 'export PATH=%q:"$PATH"' "$install_dir")
            if ! grep -Fqx -- "$path_line" "$profile" 2>/dev/null; then
                printf '\n# Eirene\n%s\n' "$path_line" >> "$profile"
            fi
            printf 'Added PATH to %s. Open a new terminal, or run:\n%s\n' "$profile" "$path_line"
            ;;
    esac
fi
printf 'Run eirene to get started.\n'
