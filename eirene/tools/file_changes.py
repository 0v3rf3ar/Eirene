"""Whether a shell command can create, change, move or delete files.

Accept mode runs commands without asking unless this says they may
touch files. It errs toward asking: anything it cannot read clearly counts
as a change. It is a guide for approvals, not a sandbox; the sandbox still
limits what a command can reach.
"""

from __future__ import annotations

import re
import shlex
from pathlib import PurePath

# Commands whose whole purpose is to change files.
WRITERS = frozenset({
    # posix
    "rm", "rmdir", "unlink", "shred", "mv", "cp", "install", "ln", "mkdir",
    "touch", "truncate", "dd", "chmod", "chown", "chgrp", "chattr", "rsync",
    "scp", "tee", "patch", "tar", "unzip", "zip", "gzip", "gunzip", "bzip2",
    "bunzip2", "xz", "unxz", "7z", "7za", "zstd", "unrar", "mkfifo", "mknod",
    "split", "csplit", "wget", "curl", "sponge", "rename", "srm", "trash",
    "trash-put", "gio",
    # windows cmd
    "del", "erase", "rd", "move", "copy", "xcopy", "robocopy", "ren", "md",
    "mklink", "attrib", "icacls", "takeown", "format", "cipher",
    # powershell (lower-cased)
    "remove-item", "ri", "move-item", "mi", "copy-item", "cpi", "new-item",
    "ni", "set-content", "sc", "add-content", "ac", "out-file", "rename-item",
    "rni", "clear-content", "clc", "clear-item", "cli", "expand-archive",
    "compress-archive", "tee-object", "set-item", "si", "new-itemproperty",
    "set-itemproperty", "remove-itemproperty", "mkdir.exe",
})

# Read-only uses of the writers above.
_READ_ONLY_USES = {
    "tar": lambda args: bool(args) and _flag_letters(args[0], "t") and not
           _flag_letters(args[0], "cxurA"),
    "unzip": lambda args: any(a in {"-l", "-v", "-t", "-Z", "-p"} for a in args),
    "zip": lambda args: any(a in {"-T", "-sf"} for a in args),
    "gzip": lambda args: any(a in {"-l", "-t", "-c", "--list", "--test", "--stdout"} for a in args),
    "xz": lambda args: any(a in {"-l", "-t", "-c", "--list", "--test", "--stdout"} for a in args),
    "zstd": lambda args: any(a in {"-l", "-t", "-c", "--list", "--test", "--stdout"} for a in args),
    "7z": lambda args: bool(args) and args[0] in {"l", "t"},
    "7za": lambda args: bool(args) and args[0] in {"l", "t"},
    # Fetching to stdout only.
    "curl": lambda args: not any(a in {"-o", "-O", "--output", "--remote-name",
                                       "--remote-name-all", "-T", "--upload-file",
                                       "-J", "--create-dirs", "-c", "--cookie-jar"}
                                 or a.startswith(("--output=", "-o")) and a != "-o"
                                 for a in args),
    "wget": lambda args: any(a in {"-O-", "--spider"} for a in args) or (
        "-O" in args and args.index("-O") + 1 < len(args) and args[args.index("-O") + 1] == "-"),
    "gio": lambda args: bool(args) and args[0] in {"info", "list", "cat", "mime", "help", "version"},
}

GIT_WRITES = frozenset({
    "add", "rm", "mv", "checkout", "switch", "restore", "reset", "clean",
    "commit", "merge", "rebase", "pull", "stash", "apply", "am",
    "cherry-pick", "revert", "init", "clone", "worktree", "push", "fetch",
    "submodule", "gc", "prune", "filter-branch", "filter-repo", "lfs",
    "update-index", "update-ref", "notes", "replace", "bisect", "sparse-checkout",
    "format-patch", "archive", "bundle",
})

# Package managers and build tools: these sub-commands install or remove files.
PACKAGE_WRITES = {
    "npm": {"install", "i", "ci", "add", "uninstall", "remove", "rm", "un", "update",
            "up", "upgrade", "link", "unlink", "prune", "dedupe", "init", "pack",
            "publish", "rebuild", "audit fix", "exec", "x", "create"},
    "pnpm": {"install", "i", "add", "remove", "rm", "uninstall", "update", "up",
             "link", "unlink", "prune", "import", "dlx", "create", "init"},
    "yarn": {"install", "add", "remove", "upgrade", "up", "link", "unlink",
             "init", "create", "dlx"},
    "bun": {"install", "i", "add", "remove", "rm", "update", "link", "unlink",
            "init", "create", "x"},
    "pip": {"install", "uninstall", "download", "wheel"},
    "pip3": {"install", "uninstall", "download", "wheel"},
    "uv": {"add", "remove", "sync", "lock", "init", "venv", "pip", "tool"},
    "poetry": {"add", "remove", "install", "update", "lock", "init", "new", "build"},
    "pipx": {"install", "uninstall", "upgrade", "inject"},
    "cargo": {"add", "remove", "rm", "install", "uninstall", "new", "init",
              "update", "fmt", "fix", "clean", "publish"},
    "go": {"get", "install", "mod", "fmt", "generate", "clean", "work"},
    "gem": {"install", "uninstall", "update", "build"},
    "bundle": {"install", "update", "add", "remove"},
    "composer": {"install", "require", "remove", "update", "create-project"},
    "dotnet": {"add", "remove", "new", "restore", "publish", "format", "clean"},
    "apt": {"install", "remove", "purge", "autoremove", "upgrade", "full-upgrade"},
    "apt-get": {"install", "remove", "purge", "autoremove", "upgrade", "dist-upgrade"},
    "dnf": {"install", "remove", "erase", "upgrade", "update"},
    "yum": {"install", "remove", "erase", "upgrade", "update"},
    "pacman": {"-S", "-R", "-U", "-Syu", "-Sy", "-Rs", "-Rns", "-Su"},
    "brew": {"install", "uninstall", "remove", "upgrade", "reinstall", "link", "unlink"},
    "winget": {"install", "uninstall", "upgrade"},
    "choco": {"install", "uninstall", "upgrade"},
    "scoop": {"install", "uninstall", "update"},
    "conda": {"install", "remove", "uninstall", "update", "create"},
    "make": {"clean", "install", "uninstall", "distclean"},
}

# Formatters and fixers that rewrite files in place, and the flags that make
# them do so. ``None`` means they always write.
FORMATTERS: dict[str, set[str] | None] = {
    "black": None, "isort": None, "autopep8": {"-i", "--in-place"},
    "yapf": {"-i", "--in-place"}, "gofmt": {"-w"}, "goimports": {"-w"},
    "rustfmt": None, "clang-format": {"-i"}, "shfmt": {"-w", "--write"},
    "prettier": {"--write", "-w"}, "eslint": {"--fix"}, "stylelint": {"--fix"},
    "rubocop": {"-a", "-A", "--autocorrect", "--auto-correct", "--autocorrect-all"},
    "terraform": None,
}

INPLACE_EDITORS = frozenset({"sed", "gsed", "perl", "ruby"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish", "busybox"})
POWERSHELLS = frozenset({"pwsh", "powershell"})
WRAPPERS = frozenset({"sudo", "doas", "env", "command", "exec", "nohup", "time",
                      "nice", "ionice", "stdbuf", "builtin", "caffeinate",
                      "xargs", "parallel", "watch", "timeout", "cmd", "start", "call"})
NULL_TARGETS = frozenset({"/dev/null", "nul", "$null", "/dev/stdout", "/dev/stderr"})
SEPARATORS = frozenset({";", "&&", "||", "|", "&", "|&", "(", ")", "\n"})

# Inline scripts that plainly write or delete (python -c, node -e and the like).
INLINE_WRITE = re.compile(
    r"os\.(remove|unlink|rename|replace|rmdir|removedirs|makedirs|mkdir)|shutil\.|"
    r"\.(write_text|write_bytes|unlink|rmdir|mkdir|rename|replace|touch)\(|"
    r"open\([^)]*['\"][wax+]|"
    r"fs\.(unlink|rm|rmdir|writeFile|appendFile|rename|mkdir|copyFile|cp)|"
    r"File\.(write|delete|open)|FileUtils|Remove-Item|Set-Content|Out-File")


def changes_files(command: str) -> bool:
    """True when ``command`` may create, change, move or delete a file."""
    text = (command or "").strip()
    if not text:
        return True
    if "$(" in text or "`" in text or "<(" in text or ">(" in text:
        return True  # A command built at run time cannot be read in advance.
    if INLINE_WRITE.search(text):
        return True
    try:
        tokens = _split(text)
    except ValueError:
        return True
    segment: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _is_write_redirect(token):
            target = tokens[index + 1] if index + 1 < len(tokens) else ""
            if token.endswith("&") and target.isdigit():
                index += 2  # >&1 and 2>&1 point at another stream.
                continue
            if target.lower() not in NULL_TARGETS:
                return True
            index += 2
            continue
        if token in SEPARATORS:
            if segment and _segment_changes(segment):
                return True
            segment = []
        elif not _is_redirect(token):
            segment.append(token)
        index += 1
    return bool(segment) and _segment_changes(segment)


def _split(text: str) -> list[str]:
    lexer = shlex.shlex(text.replace("\r\n", "\n"), posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    out: list[str] = []
    for token in lexer:
        # Keep "2>" and ">>" as one redirect token.
        if out and token and token[0] in "<>" and out[-1].isdigit() and _touching(text, out[-1], token):
            out[-1] += token
            continue
        out.append(token)
    return out


def _touching(text: str, left: str, right: str) -> bool:
    return f"{left}{right}" in text


def _is_redirect(token: str) -> bool:
    return bool(token) and token.lstrip("0123456789&").startswith(("<", ">"))


def _is_write_redirect(token: str) -> bool:
    return _is_redirect(token) and ">" in token


def _segment_changes(tokens: list[str]) -> bool:
    tokens = list(tokens)
    while tokens:
        while tokens and "=" in tokens[0] and not tokens[0].startswith(("-", "=")):
            tokens.pop(0)  # VAR=value prefix
        if not tokens:
            return False
        name = _name(tokens[0])
        args = tokens[1:]
        if name in WRAPPERS:
            tokens = _unwrap(name, args)
            continue
        return _command_changes(name, args)
    return False


def _name(token: str) -> str:
    name = PurePath(token.strip("'\"").replace("\\", "/")).name.lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _unwrap(name: str, args: list[str]) -> list[str]:
    """The command a wrapper such as sudo or xargs runs."""
    rest = list(args)
    if name == "timeout":
        while rest and rest[0].startswith("-"):
            rest.pop(0)
        return rest[1:]  # drop the duration
    if name == "cmd":
        while rest and rest[0].lower() in {"/c", "/k", "/s", "/q", "/d"}:
            rest.pop(0)
        return rest
    while rest and rest[0].startswith("-"):
        option = rest.pop(0)
        # Options that take a value, for the wrappers that use them.
        if name in {"sudo", "doas"} and option in {"-u", "-g", "-C", "-D"} and rest:
            rest.pop(0)
        elif name == "xargs" and option in {"-I", "-n", "-L", "-P", "-d", "-a", "-E", "-s"} and rest:
            rest.pop(0)
        elif name in {"nice", "ionice"} and option in {"-n", "-c"} and rest:
            rest.pop(0)
        elif name == "watch" and option in {"-n", "-d"} and rest:
            rest.pop(0)
    return rest


def _command_changes(name: str, args: list[str]) -> bool:
    lowered = [a.lower() for a in args]
    if name in SHELLS:
        for flag, script in zip(args, args[1:]):
            if flag in {"-c", "-lc", "-ic", "-ec"}:
                return changes_files(script)
        # Running a script file: its contents are unknown.
        return any(not a.startswith("-") for a in args)
    if name in POWERSHELLS:
        for flag, script in zip(lowered, args[1:]):
            if flag in {"-c", "-command", "-encodedcommand", "-ec"}:
                return flag in {"-encodedcommand", "-ec"} or changes_files(script)
        return any(a in {"-file", "-f"} for a in lowered)
    if name in WRITERS:
        check = _READ_ONLY_USES.get(name)
        return not (check and check(args))
    if name in INPLACE_EDITORS:
        return any(a.startswith("-i") or a.startswith("--in-place")
                   or (name in {"perl", "ruby"} and re.fullmatch(r"-[a-zA-Z]*i\S*", a))
                   for a in args)
    if name == "awk" or name == "gawk":
        return any("inplace" in a for a in args)
    if name == "find":
        return any(a in {"-delete", "-exec", "-execdir", "-ok", "-okdir"}
                   or a.startswith(("-fprint", "-fls")) for a in args)
    if name == "git":
        return _git_changes(args)
    if name in PACKAGE_WRITES:
        words = [a for a in args if not a.startswith("-")] if name != "pacman" else args
        if name == "npm" and len(words) >= 2 and words[0] == "audit" and words[1] == "fix":
            return True
        if name == "npm" and words and words[0] in {"run", "run-script", "test", "t", "start"}:
            return False
        return bool(words) and words[0] in PACKAGE_WRITES[name]
    if name in {"python", "python3", "py"} and len(args) >= 2 and args[0] == "-m":
        module = args[1]
        if module in {"pip", "black", "isort", "autopep8", "venv", "virtualenv"}:
            return module != "pip" or (len(args) > 2 and args[2] in PACKAGE_WRITES["pip"])
        if module == "ruff":
            return _ruff_changes(args[2:])
    if name == "ruff":
        return _ruff_changes(args)
    if name in FORMATTERS:
        flags = FORMATTERS[name]
        if flags is None:
            return name != "terraform" or (bool(args) and args[0] in {"fmt", "apply", "destroy", "init", "import"})
        return any(a in flags or any(a.startswith(f + "=") for f in flags) for a in args)
    return False


def _ruff_changes(args: list[str]) -> bool:
    if args and args[0] == "format":
        return not any(a in {"--check", "--diff"} for a in args)
    return any(a in {"--fix", "--unsafe-fixes"} or a.startswith("--fix=true") for a in args) \
        and "--diff" not in args


def _git_changes(args: list[str]) -> bool:
    rest = list(args)
    while rest and rest[0].startswith("-"):
        option = rest.pop(0)
        if option in {"-C", "-c", "--git-dir", "--work-tree"} and rest:
            rest.pop(0)
    if not rest:
        return False
    sub, more = rest[0], rest[1:]
    if sub in GIT_WRITES:
        return True
    if sub == "branch":
        return any(a in {"-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move",
                         "--copy", "-f", "--force", "-u", "--set-upstream-to",
                         "--unset-upstream", "--edit-description"} for a in more) or (
            bool(more) and not any(a.startswith("-") for a in more))
    if sub == "tag":
        return any(a in {"-d", "--delete", "-a", "-s", "-f", "-m"} for a in more) or (
            bool(more) and not any(a.startswith("-") for a in more))
    if sub == "remote":
        return bool(more) and more[0] in {"add", "remove", "rm", "rename", "set-url",
                                          "set-head", "prune", "update"}
    if sub == "config":
        return not any(a in {"--get", "--get-all", "--get-regexp", "--list", "-l",
                             "--show-origin"} for a in more) and len(
            [a for a in more if not a.startswith("-")]) >= 2
    if sub == "diff" or sub == "log" or sub == "show":
        return any(a.startswith("--output") for a in more)
    return False


def _flag_letters(token: str, letters: str) -> bool:
    flag = token.lstrip("-")
    return any(letter in flag for letter in letters)
