#!/usr/bin/env bash
# Install the matching Linux or macOS release.
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

# A terminal gets colour, the portrait and a live download bar; logs get plain lines.
fancy=0
if [[ -t 1 && "${TERM:-dumb}" != dumb && -z "${NO_COLOR+x}" ]]; then fancy=1; fi
if [[ "$fancy" == 1 ]]; then
    reset=$'\033[0m' bold=$'\033[1m' dim=$'\033[2m' green=$'\033[38;2;120;220;150m'
    cyan=$'\033[38;2;90;200;255m' violet=$'\033[38;2;190;130;255m' red=$'\033[38;2;255;120;120m'
    yellow=$'\033[38;2;240;200;110m'
    pad='  ' error_mark="  $red✗$reset " warning_mark="  $yellow!$reset "
else
    reset='' bold='' dim='' green='' cyan='' violet='' red='' yellow=''
    pad='' error_mark='error: ' warning_mark='warning: '
fi
spinner=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
pending=0

# `begin` shows what is happening on one line; `done_step` replaces it with the result.
begin() {
    [[ "$fancy" == 1 ]] || return 0
    printf '  %s%s%s %s%s%s' "$cyan" "${spinner[0]}" "$reset" "$dim" "$1" "$reset"
    pending=1
}
clear_pending() {
    if [[ "$pending" == 1 ]]; then printf '\r\033[2K'; pending=0; fi
}
done_step() {
    clear_pending
    if [[ "$fancy" == 1 ]]; then printf '  %s✓%s %s\n' "$green" "$reset" "$*"
    else printf '[ok] %s\n' "$*"; fi
}
note() {
    clear_pending
    if [[ "$fancy" == 1 ]]; then printf '  %s·%s %s%s%s\n' "$dim" "$reset" "$dim" "$*" "$reset"
    else printf '%s\n' "$*"; fi
}
fail() {
    clear_pending
    printf '%s%s\n' "$error_mark" "$*" >&2
    exit 1
}
warn() {
    clear_pending
    printf '%s%s\n' "$warning_mark" "$*" >&2
}
tilde() { local value=$1; [[ "$value" == "$HOME"/* ]] && value="~${value#"$HOME"}"; printf '%s' "$value"; }
# A path to type: ~/... when that is unambiguous, otherwise fully quoted.
typed_path() {
    local rest=${1#"$HOME"/}
    if [[ "$1" == "$HOME"/* && "$rest" =~ ^[A-Za-z0-9._/-]+$ ]]; then printf '~/%s' "$rest"
    else quote "$1"; fi
}
megabytes() { awk -v bytes="$1" 'BEGIN { printf "%.1f", bytes / 1048576 }'; }

show_portrait() {
    [[ "$fancy" == 1 && ${COLUMNS:-$(tput cols 2>/dev/null || echo 80)} -ge 56 ]] || return 0
    local rows=() row index=0 count red_value green_value
    while IFS= read -r row; do rows+=("$row"); done <<'EIRENE_ART'
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
    count=${#rows[@]}
    printf '\n'
    for row in "${rows[@]}"; do
        red_value=$(( 90 + 100 * index / (count - 1) ))
        green_value=$(( 200 - 70 * index / (count - 1) ))
        printf '\033[38;2;%d;%d;255m%s%s\n' "$red_value" "$green_value" "$row" "$reset"
        index=$(( index + 1 ))
    done
}

step='checking this computer'
installed=0
curl_pid=''
trap 'status=$?; clear_pending; printf "%sfailed while %s (exit %s).\n" "$error_mark" "$step" "$status" >&2; if [[ "$installed" == 0 ]]; then printf "%sThe existing executable has not been replaced. Fix the error above and rerun the installer.\n" "$pad" >&2; fi; exit "$status"' ERR
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
for tool in tar grep cp chmod mv mkdir sleep ps wc; do
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
if command -v sha256sum >/dev/null 2>&1; then checksum_tool=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then checksum_tool=(shasum -a 256)
else fail 'sha256sum or shasum is required to verify the download'; fi

fetch() {
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --retry 3 --retry-delay 2 --connect-timeout 30 --max-time 600 "$@"
}
# Read top-level release fields without confusing nested asset or uploader
# metadata, or braces inside JSON strings, with release fields.
release_metadata() {
    awk -v prerelease_only="$prerelease_only" '
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
            if (quoted) {
                if (escaped) escaped = 0
                else if (c == "\\") escaped = 1
                else if (c == "\"") quoted = 0
                continue
            }
            if (c == "\"") { quoted = 1; continue }
            if (c == "{") {
                depth++
                if (depth == 1) object = ""
            }
            if (c == "}") {
                depth--
                if (depth == 0) {
                    count++
                    release_tag = field("tag_name", object)
                    if (object ~ /"draft"[[:space:]]*:[[:space:]]*false/ &&
                        (!prerelease_only || object ~ /"prerelease"[[:space:]]*:[[:space:]]*true/)) {
                        date = field("published_at", object)
                        if (date > newest) { newest = date; tag = release_tag }
                    }
                }
            }
        }
    }
    END { print count+0, newest, tag }'
}

# Download in the background and draw the bar from the bytes on disk; curl's own
# meter cannot be styled.
download() {
    local url=$1 destination=$2 label=$3 total got=0 started=$SECONDS elapsed rate width=28
    local fill full part bar track index tick=0 eighths=('' ▏ ▎ ▍ ▌ ▋ ▊ ▉)
    if [[ "$fancy" == 0 ]]; then
        fetch --output "$destination" "$url"
        return
    fi
    total=$(fetch --head "$url" 2>/dev/null | awk 'tolower($1) == "content-length:" { size = $2 } END { print size + 0 }' || true)
    total=${total//[!0-9]/}
    printf '\033[?25l'
    printf '  %s↓%s %s%s%s\n' "$cyan" "$reset" "$dim" "$label" "$reset"
    fetch --output "$destination" "$url" &
    curl_pid=$!
    while kill -0 "$curl_pid" 2>/dev/null; do
        got=0
        if [[ -f "$destination" ]]; then got=$(wc -c < "$destination" | tr -d ' '); fi
        elapsed=$(( SECONDS - started ))
        rate=$(( elapsed > 0 ? got / elapsed : 0 ))
        if [[ -n "$total" && "$total" -gt 0 ]]; then
            (( got > total )) && got=$total
            fill=$(( got * width * 8 / total )); full=$(( fill / 8 )); part=$(( fill % 8 ))
            bar=''; index=0
            while (( index < full )); do bar="$bar█"; index=$(( index + 1 )); done
            bar="$bar${eighths[part]}"
            track=''; index=$(( full + (part > 0 ? 1 : 0) ))
            while (( index < width )); do track="$track─"; index=$(( index + 1 )); done
            printf '\r\033[2K    %s%s%s%s%s %3d%%  %s / %s MB' "$violet" "$bar" "$reset" "$dim" "$track" \
                $(( got * 100 / total )) "$(megabytes "$got")" "$(megabytes "$total")"
            if (( rate > 0 )); then
                printf '  %s MB/s  %ss left' "$(megabytes "$rate")" $(( (total - got) / rate ))
            fi
            printf '%s' "$reset"
        else
            printf '\r\033[2K    %s%s%s %s MB' "$violet" "${spinner[tick % 10]}" "$reset" "$(megabytes "$got")"
        fi
        tick=$(( tick + 1 ))
        sleep 0.1
    done
    local status=0
    wait "$curl_pid" || status=$?
    curl_pid=''
    printf '\r\033[2K\033[1A\033[2K\033[?25h'
    return "$status"
}

# Profile writing and verification; output is summarised by the caller.
quote() { local value=${1//\'/\'\\\'\'}; printf "'%s'" "$value"; }
add_path() {
    local profile=$1 path_line=$2 backup
    if [[ -e "$profile" && ! -f "$profile" ]]; then
        warn "not a regular profile: $profile"; return 1
    fi
    if grep -Fqx -- "$path_line" "$profile" 2>/dev/null; then
        already+=("$(tilde "$profile")"); return 0
    fi
    mkdir -p -- "${profile%/*}" || return 1
    if [[ -e "$profile" ]]; then
        backup=$(mktemp "$profile.eirene-backup.XXXXXX") || return 1
        cp -p -- "$profile" "$backup" || return 1
    fi
    printf '\n# Eirene\n%s\n' "$path_line" >> "$profile" || return 1
    grep -Fqx -- "$path_line" "$profile" || return 1
    changed+=("$(tilde "$profile")")
}
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
join() { local IFS=','; local text="$*"; printf '%s' "${text//,/, }"; }

# Linux runs every command inside Bubblewrap. Missing bwrap or blocked user
# namespaces are fixed outside Eirene, so say exactly how now, not mid-task.
# Empty when the setting does not exist on this kernel; never fails under set -e.
read_setting() { local value=''; value=$(cat "$1" 2>/dev/null) || value=''; printf '%s' "${value//[!0-9]/}"; }
bubblewrap_package_command() {
    local sudo=''
    [[ "$(id -u 2>/dev/null || echo 1)" == 0 ]] || sudo='sudo '
    if command -v apt-get >/dev/null 2>&1; then printf '%sapt install bubblewrap' "$sudo"
    elif command -v dnf >/dev/null 2>&1; then printf '%sdnf install bubblewrap' "$sudo"
    elif command -v yum >/dev/null 2>&1; then printf '%syum install bubblewrap' "$sudo"
    elif command -v pacman >/dev/null 2>&1; then printf '%spacman -S bubblewrap' "$sudo"
    elif command -v zypper >/dev/null 2>&1; then printf '%szypper install bubblewrap' "$sudo"
    elif command -v apk >/dev/null 2>&1; then printf '%sapk add bubblewrap' "$sudo"
    elif command -v xbps-install >/dev/null 2>&1; then printf '%sxbps-install -S bubblewrap' "$sudo"
    elif command -v emerge >/dev/null 2>&1; then printf '%semerge sys-apps/bubblewrap' "$sudo"
    fi
}
in_container() {
    [[ -f /.dockerenv || -f /run/.containerenv ]] && return 0
    command -v systemd-detect-virt >/dev/null 2>&1 && systemd-detect-virt --container --quiet 2>/dev/null
}
# A boxed advisory in the installer's colours: title, explanation, then commands.
advise() {
    local title=$1 line
    shift
    clear_pending
    if [[ "$fancy" == 1 ]]; then
        printf '\n  %s╭─%s %s!%s %s%s%s\n' "$yellow" "$reset" "$yellow$bold" "$reset" "$bold" "$title" "$reset" >&2
        for line in "$@"; do
            case "$line" in
                '$ '*) printf '  %s│%s   %s%s%s\n' "$yellow" "$reset" "$bold$cyan" "${line#'$ '}" "$reset" >&2 ;;
                '') printf '  %s│%s\n' "$yellow" "$reset" >&2 ;;
                *) printf '  %s│%s %s%s%s\n' "$yellow" "$reset" "$dim" "$line" "$reset" >&2 ;;
            esac
        done
        printf '  %s╰─%s\n' "$yellow" "$reset" >&2
    else
        printf 'warning: %s\n' "$title" >&2
        for line in "$@"; do
            [[ -n "$line" ]] && printf '  %s\n' "${line#'$ '}" >&2
        done
    fi
}
check_sandbox() {
    [[ "$os_name" == Linux ]] || return 0
    local bwrap command error='' persist='/etc/sysctl.d/90-eirene-userns.conf'
    begin 'Checking the command sandbox'
    bwrap=$(command -v bwrap 2>/dev/null || true)
    if [[ -z "$bwrap" ]]; then
        command=$(bubblewrap_package_command)
        if [[ -n "$command" ]]; then
            advise 'Command sandbox not ready: Bubblewrap is not installed' \
                'Eirene runs every command inside Bubblewrap and never without it,' \
                'so commands will refuse to start until it is installed:' '' \
                "\$ $command" '' 'Then check it inside Eirene with /sandbox.'
        else
            advise 'Command sandbox not ready: Bubblewrap is not installed' \
                'Eirene runs every command inside Bubblewrap and never without it.' \
                "Install your distribution's bubblewrap package, then check with /sandbox."
        fi
        return 0
    fi
    # The same isolation Eirene starts for a command, on a no-op.
    if command -v timeout >/dev/null 2>&1; then
        error=$(timeout 10 "$bwrap" --die-with-parent --new-session --unshare-all --cap-drop ALL \
            --ro-bind / / true 2>&1 >/dev/null) && { done_step "Command sandbox ready $dim(Bubblewrap)$reset"; return 0; }
    else
        error=$("$bwrap" --die-with-parent --new-session --unshare-all --cap-drop ALL \
            --ro-bind / / true 2>&1 >/dev/null) && { done_step "Command sandbox ready $dim(Bubblewrap)$reset"; return 0; }
    fi
    error=${error%%$'\n'*}
    error=${error#bwrap: }
    local reason=${error:-bwrap exited with an error}
    if [[ "$(read_setting /proc/sys/kernel/unprivileged_userns_clone)" == 0 ]]; then
        advise 'Command sandbox blocked: user namespaces are turned off' \
            "Bubblewrap is installed but cannot start ($reason)." \
            'This kernel disallows unprivileged user namespaces. Allow them now:' '' \
            '$ sudo sysctl -w kernel.unprivileged_userns_clone=1' '' \
            'and keep it after a reboot:' '' \
            "\$ echo kernel.unprivileged_userns_clone=1 | sudo tee $persist"
    elif [[ "$(read_setting /proc/sys/user/max_user_namespaces)" == 0 ]]; then
        advise 'Command sandbox blocked: user namespaces are turned off' \
            "Bubblewrap is installed but cannot start ($reason)." \
            'This system allows no user namespaces. Allow them now:' '' \
            '$ sudo sysctl -w user.max_user_namespaces=15000' '' \
            'and keep it after a reboot:' '' \
            "\$ echo user.max_user_namespaces=15000 | sudo tee $persist"
    elif [[ "$(read_setting /proc/sys/kernel/apparmor_restrict_unprivileged_userns)" == 1 ]]; then
        advise 'Command sandbox blocked by AppArmor' \
            "Bubblewrap is installed but cannot start ($reason)." \
            'AppArmor only lets profiled programs use user namespaces. Allow them now:' '' \
            '$ sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0' '' \
            'and keep it after a reboot:' '' \
            "\$ echo kernel.apparmor_restrict_unprivileged_userns=0 | sudo tee $persist" '' \
            'Or give bwrap its own AppArmor profile that allows userns.'
    elif in_container; then
        advise 'Command sandbox blocked inside this container' \
            "Bubblewrap is installed but cannot start ($reason)." \
            'The container forbids nested namespaces. Enable nesting for it' \
            '(Proxmox LXC: features: nesting=1; Docker: a seccomp profile that' \
            'allows unshare), or run Eirene on the host.'
    else
        advise 'Command sandbox cannot start' \
            "Bubblewrap is installed but failed: $reason" \
            'Eirene runs commands only inside it. Check that this kernel allows' \
            'unprivileged user namespaces, then check again with /sandbox.'
    fi
}

if [[ "$path_only" == 0 ]]; then
    show_portrait
    if [[ "$fancy" == 1 ]]; then
        printf '\n  %sE I R E N E%s  %s·  terminal AI agent%s\n\n' "$bold$cyan" "$reset" "$dim" "$reset"
    else
        printf 'Eirene installer\n'
    fi
    done_step "${os_name/Darwin/macOS} · $cpu"

    begin 'Finding the release'
    if [[ "$version" == edge ]]; then
        step='finding the latest unstable release'
        prerelease_only=1
        page=1 newest='' candidate=''
        while :; do
            metadata=$(fetch "https://api.github.com/repos/$repo/releases?per_page=100&page=$page")
            read -r count published tag <<< "$(printf '%s\n' "$metadata" | release_metadata)"
            if [[ -n "$tag" && "$published" > "$newest" ]]; then newest=$published; candidate=$tag; fi
            [[ "$count" == 100 ]] || break
            page=$((page + 1))
        done
        [[ -n "$candidate" ]] || fail 'no published unstable release is available'
        version=$candidate
    elif [[ "$version" == latest ]]; then
        step='finding the latest release; check your connection to github.com'
        resolved=$(fetch --head --output /dev/null --write-out '%{url_effective}' "https://github.com/$repo/releases/latest")
        version=${resolved##*/}
    fi
    [[ "$version" =~ ^v[0-9][A-Za-z0-9._+-]*$ ]] || fail "invalid release tag: $version (expected v followed by a version)"
    done_step "Eirene $version"

    asset="eirene-$target-${version#v}.tar.gz"
    base="https://github.com/$repo/releases/download/$version"
    step='creating temporary files; check free disk space and temporary-directory permissions'
    temporary=$(mktemp -d)
    staged=''
    cleanup() {
        if [[ -n "$curl_pid" ]]; then kill "$curl_pid" 2>/dev/null || true; fi
        [[ "$fancy" == 1 ]] && printf '\033[?25h'
        rm -rf -- "$temporary" || warn "could not remove temporary files: $temporary"
        if [[ -n "$staged" ]]; then rm -f -- "$staged" || warn "could not remove staging file: $staged"; fi
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    step="downloading $asset; check your connection and that release $version has an asset for $target"
    download "$base/$asset" "$temporary/$asset" "$asset"
    [[ -s "$temporary/$asset" ]] || fail 'downloaded archive is empty'
    done_step "Downloaded $asset $dim($(megabytes "$(wc -c < "$temporary/$asset" | tr -d ' ')") MB)$reset"

    begin 'Verifying'
    step='verifying the release checksum'
    fetch --output "$temporary/SHA256SUMS" "$base/SHA256SUMS"
    expected=$(awk -v wanted="$asset" '
        ($2 == wanted || $2 == "*" wanted) && length($1) == 64 && $1 ~ /^[[:xdigit:]]+$/ { count++; sum = tolower($1) }
        END { if (count != 1) exit 1; print sum }' "$temporary/SHA256SUMS") ||
        fail "the release has no valid checksum for $asset"
    actual=$("${checksum_tool[@]}" "$temporary/$asset")
    [[ "${actual%% *}" == "$expected" ]] || fail 'checksum mismatch; the existing installation was not changed'
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
    "$staged" --help > "$temporary/help.txt" 2>&1 || fail 'downloaded executable failed --help'
    [[ -s "$temporary/version.txt" && -s "$temporary/help.txt" ]] || fail 'executable returned empty version or help output'
    done_step 'SHA-256 verified'

    step="replacing $install_dir/eirene"
    mv -f -- "$staged" "$install_dir/eirene"
    staged=''
    installed=1
    done_step "Installed $(tilde "$install_dir/eirene")"
else
    [[ -x "$install_dir/eirene" ]] || fail 'shell setup needs an installed executable'
    temporary=$(mktemp -d)
    trap 'rm -rf -- "$temporary"' EXIT
fi

# POSIX quoting also works in Bash and Zsh; never evaluate a user-supplied path.
initial_path=$PATH
path_line="case \":\$PATH:\" in *$(quote ":$install_dir:")*) ;; *) export PATH=$(quote "$install_dir"):\"\$PATH\" ;; esac"
shell_name=${SHELL:-}
posix_line=$path_line
profiles=()
lines=()
changed=()
already=()
add_profile() { profiles+=("$1"); lines+=("$2"); }
# POSIX login configuration also covers sh, dash and ksh.
add_profile "$HOME/.profile" "$posix_line"
if has_shell bash; then
    add_profile "$HOME/.bashrc" "$posix_line"
    if [[ -f "$HOME/.bash_profile" ]]; then add_profile "$HOME/.bash_profile" "$posix_line"
    elif [[ -f "$HOME/.bash_login" ]]; then add_profile "$HOME/.bash_login" "$posix_line"
    elif [[ "$os_name" == Darwin ]]; then add_profile "$HOME/.bash_profile" "$posix_line"; fi
fi
if has_shell zsh; then
    add_profile "${ZDOTDIR:-$HOME}/.zshrc" "$posix_line"
    add_profile "${ZDOTDIR:-$HOME}/.zprofile" "$posix_line"
fi
if has_shell fish; then
    fish_path=${install_dir//\\/\\\\}
    fish_path=${fish_path//\'/\\\'}
    add_profile "${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/eirene.fish" "contains -- '$fish_path' \$PATH; or set -gx PATH '$fish_path' \$PATH"
fi
if has_shell ksh; then add_profile "$HOME/.kshrc" "$posix_line"; fi
for name in csh tcsh; do
    if has_shell "$name"; then
        csh_line="if ( \":\$PATH:\" !~ *$(quote ":$install_dir:")* ) set path = ( $(quote "$install_dir") \$path )"
        add_profile "$HOME/.${name}rc" "$csh_line"
    fi
done
if has_shell pwsh; then
    ps_path=${install_dir//\'/\'\'}
    add_profile "${XDG_CONFIG_HOME:-$HOME/.config}/powershell/profile.ps1" "if ((\$env:PATH -split [IO.Path]::PathSeparator) -cnotcontains '$ps_path') { \$env:PATH = '$ps_path' + [IO.Path]::PathSeparator + \$env:PATH }"
fi
if has_shell nu; then
    # Nushell double-quoted strings do not interpolate without a $ prefix.
    nu_path=${install_dir//\\/\\\\}
    nu_path=${nu_path//\"/\\\"}
    add_profile "${XDG_CONFIG_HOME:-$HOME/.config}/nushell/env.nu" "\$env.PATH = (\$env.PATH | prepend \"$nu_path\" | uniq)"
fi

path_ready=1
if [[ "${EIRENE_NO_PATH:-0}" != 1 ]]; then
    step='adding Eirene to PATH'
    for index in "${!profiles[@]}"; do
        if ! add_path "${profiles[$index]}" "${lines[$index]}"; then
            path_ready=0
            warn "Eirene is installed, but PATH could not be saved to ${profiles[$index]}. Check permissions, then rerun the installer."
        fi
    done
else
    note 'PATH setup skipped (EIRENE_NO_PATH=1)'
fi

step='verifying the installed command'
bashrc_verified=0
if [[ "${EIRENE_NO_PATH:-0}" != 1 ]]; then
    export PATH="$install_dir:$PATH"
    hash -r
    [[ "$(command -v eirene)" == "$install_dir/eirene" ]] || fail 'PATH resolves to a different eirene'
    if [[ "$path_only" == 0 ]]; then
        installed_version=$(eirene --version 2>&1)
    fi
    if [[ -f "$HOME/.bashrc" ]] && command -v bash >/dev/null 2>&1; then
        # Job control gives the check its own process group. Interactive startup
        # and profiles can create additional groups, so snapshot descendants
        # before signalling the shell; their parent links disappear on exit.
        # Only resolve PATH here: another frozen-binary startup is unnecessary.
        # An interactive Bash on the installer's terminal tries to take it over and
        # is stopped (SIGTTIN/SIGTTOU) until the watchdog fires. A new session has
        # no terminal; setsid -w keeps the exit status. macOS has no setsid.
        detach=()
        if command -v setsid >/dev/null 2>&1 && setsid -w true </dev/null >/dev/null 2>&1; then
            detach=(setsid -w)
        fi
        verify_bash_profile() (
            set +e
            set -m
            PATH="$initial_path" "${detach[@]}" bash --noprofile --norc +m -ic \
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
            bashrc_verified=1
        else
            path_ready=0
            if [[ -f "$temporary/shell-timeout" ]]; then
                warn 'Bash startup exceeded 4 seconds; verification stopped. PATH is saved; use the full path below.'
            else
                warn 'Bash startup verification failed; inspect .bashrc and use the full path below.'
            fi
        fi
    fi
    if (( ${#changed[@]} )); then
        done_step "PATH set in $(join "${changed[@]}")$([[ "$bashrc_verified" == 1 ]] && printf ' %s(checked in ~/.bashrc)%s' "$dim" "$reset")"
    elif (( ${#already[@]} )); then
        done_step "PATH already set$([[ "$bashrc_verified" == 1 ]] && printf ' %s(checked in ~/.bashrc)%s' "$dim" "$reset")"
    fi
elif [[ "$path_only" == 0 ]]; then
    installed_version=$("$install_dir/eirene" --version 2>&1)
fi
if [[ "$path_only" == 1 ]]; then
    [[ "$path_ready" == 1 ]] || fail 'some shell profiles could not be configured or verified'
    exit 0
fi

check_sandbox
launch=$(quote "$install_dir/eirene")
printf '\n%s%s%s is installed.%s\n' "$pad" "$bold$green" "${installed_version:-eirene ${version#v}}" "$reset"
if [[ "${EIRENE_NO_PATH:-0}" == 1 || "$path_ready" == 0 ]]; then
    printf '%sRun it with: %s\n\n' "$pad" "$launch"
elif [[ ":$initial_path:" == *":$install_dir:"* ]]; then
    printf '%sRun: %seirene%s\n\n' "$pad" "$bold" "$reset"
else
    case "${shell_name##*/}" in
        bash) refresh="source $(typed_path "$HOME/.bashrc")" ;;
        zsh) refresh="source $(typed_path "${ZDOTDIR:-$HOME}/.zshrc")" ;;
        fish) refresh="source $(typed_path "${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/eirene.fish")" ;;
        *) refresh="$posix_line" ;;
    esac
    printf '%sOpen a new terminal, or run: %s%s%s\n\n' "$pad" "$dim" "$refresh" "$reset"
fi
