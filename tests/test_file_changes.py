"""Accept mode asks only for commands that may change files."""

import pytest

from eirene.tools.file_changes import changes_files

CHANGES = [
    "rm -rf build", "mv a b", "cp a b", "echo hi > out.txt", "cat a >> b",
    "sed -i 's/a/b/' f", "perl -pi -e 's/a/b/' f", "git checkout main",
    "git reset --hard", "git commit -m x", "npm install", "pip install x",
    "python -m pip install x", "touch x", "mkdir d", "find . -name '*.pyc' -delete",
    "cd src && rm x", "ls | xargs rm", "sudo rm x", "bash -c 'rm x'", "black .",
    "ruff check --fix", "ruff format", "prettier --write .", "tee out.txt",
    "Remove-Item x", "del x", "echo $(rm x)", "python -c \"import os; os.remove('x')\"",
    "tar xzf a.tgz", "curl -o x http://a", "git branch new", "unzip a.zip",
    "cargo fmt", "make clean", "pwsh -c 'Remove-Item x'", "dd if=a of=b",
    "chmod +x x", "git stash", "npm audit fix", "timeout 5 rm x", "VAR=1 rm x",
    "ln -s a b", "uv sync", "sh script.sh", "", "echo 'unterminated",
]
READS = [
    "ls -la", "pytest -q", "python -m pytest tests -q 2>&1 | tail -5", "git status",
    "git diff", "git log --oneline -5", "npm test", "npm run build", "cargo test",
    "go test ./...", "grep -rn foo .", "cat a | sort | uniq", "echo hi > /dev/null",
    "ruff check .", "ruff format --check", "curl https://example.com", "tar tzf a.tgz",
    "find . -name '*.py'", "git branch", "git config --get user.name", "rg foo",
    "python -m pytest 2>/dev/null", "ls 2>&1", "uname -a && whoami",
    "echo 'a > b'", "pip list", "docker ps", "head -n 5 a; tail -n 5 b",
]


@pytest.mark.parametrize("command", CHANGES)
def test_commands_that_change_files_ask(command):
    assert changes_files(command)


@pytest.mark.parametrize("command", READS)
def test_commands_that_only_read_or_run_do_not_ask(command):
    assert not changes_files(command)
