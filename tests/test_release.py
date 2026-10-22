"""Archive and installer contracts without accessing GitHub or the user's home."""
from __future__ import annotations

import hashlib
import json
import importlib.util
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_release', ROOT / 'scripts/package_release.py')
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


def checksum_entry(archive):
    return f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n'


@pytest.mark.parametrize('target', packager.TARGETS)
def test_release_archives_preserve_binary_and_license(target, tmp_path):
    binary = tmp_path / 'binary'
    binary.write_bytes(b'release binary\x00\xff')
    archive = packager.package(target, binary, tmp_path / 'release', '0.1.7b1')
    label = {'linux-amd64': 'Linux-amd64', 'linux-arm64': 'Linux-arm64',
             'macos-silicon': 'MacOS-silicon', 'windows-amd64': 'Windows-amd64'}[target]
    extension = 'zip' if target == 'windows-amd64' else 'tar.gz'
    assert archive.name == f'eirene-{label}-0.1.7b1.{extension}'
    if target == 'windows-amd64':
        with zipfile.ZipFile(archive) as bundle:
            assert set(bundle.namelist()) == {'eirene.exe', 'LICENSE', 'NOTICE'}
            assert bundle.read('eirene.exe') == binary.read_bytes()
            assert bundle.getinfo('eirene.exe').compress_type == zipfile.ZIP_DEFLATED
    else:
        with tarfile.open(archive) as bundle:
            assert set(bundle.getnames()) == {'eirene', 'LICENSE', 'NOTICE'}
            assert bundle.getmember('eirene').mode == 0o755
            assert bundle.extractfile('eirene').read() == binary.read_bytes()
    assert list(archive.parent.iterdir()) == [archive]


@pytest.fixture
def installer(tmp_path):
    if os.name == 'nt':
        pytest.skip('Bash installer is exercised on Linux and macOS')
    home = tmp_path / 'home'
    home.mkdir()
    tools = tmp_path / 'tools'
    tools.mkdir()
    fixture = tmp_path / 'fixture'
    fixture.mkdir()
    binary = fixture / 'binary'
    binary.write_text('#!/bin/sh\nprintf "Eirene fixture\\n"\n')
    for target in ('linux-amd64', 'linux-arm64', 'macos-silicon'):
        for version in ('1.2.3', '2.3.4', '0.1.7b1'):
            packager.package(target, binary, fixture, version)
    (fixture / 'SHA256SUMS').write_text(''.join(checksum_entry(p) for p in sorted(fixture.glob('*.tar.gz'))))
    (tools / 'uname').write_text('#!/bin/sh\nif [ "$1" = -s ]; then echo "$TEST_OS"; else echo "$TEST_CPU"; fi\n')
    (tools / 'sysctl').write_text('#!/bin/sh\necho "${TEST_SILICON:-0}"\n')
    (tools / 'curl').write_text(f'#!{sys.executable}\n' + '''import os, sys, shutil, json
from urllib.parse import parse_qs, urlsplit
from pathlib import Path
args = sys.argv[1:]
url = args[-1]
with open(os.environ['TEST_LOG'], 'a') as stream: stream.write(url + '\\n' + ' '.join(args) + '\\n')
if '/releases?per_page=' in url:
    pages = json.loads(os.environ.get('TEST_RELEASE_PAGES', '{}'))
    page = parse_qs(urlsplit(url).query)['page'][0]
    print(pages.get(page, os.environ.get('TEST_RELEASES', '[]')))
elif url.endswith('/releases/latest'):
    print('https://github.com/0v3rf3ar/Eirene/releases/tag/v1.2.3', end='')
else:
    if os.environ.get('TEST_FAIL_DOWNLOAD'): sys.exit(22)
    destination = args[args.index('--output') + 1]
    shutil.copyfile(Path(os.environ['TEST_FIXTURE']) / url.rsplit('/', 1)[-1], destination)
''')
    for file in tools.iterdir():
        file.chmod(0o755)
    env = {**os.environ, 'HOME': str(home), 'SHELL': '/bin/bash',
           'PATH': str(tools) + os.pathsep + os.environ['PATH'],
           'TEST_OS': 'Linux', 'TEST_CPU': 'x86_64', 'TEST_FIXTURE': str(fixture),
           'TEST_LOG': str(tmp_path / 'requests.log'), 'EIRENE_NO_PATH': '1',
           'EIRENE_VERSION': 'latest', 'EIRENE_INSTALL_DIR': str(home / 'path with spaces')}
    def run(*arguments, **overrides):
        return subprocess.run(['bash', str(ROOT / 'install.sh'), *arguments], env={**env, **overrides},
                              text=True, capture_output=True, timeout=15)
    return run, env, fixture


@pytest.mark.parametrize('system,cpu,target', [('Linux', 'x86_64', 'Linux-amd64'),
    ('Linux', 'aarch64', 'Linux-arm64'), ('Darwin', 'arm64', 'MacOS-silicon')])
def test_installer_detects_host_and_installs_executable(installer, system, cpu, target):
    run, env, _ = installer
    result = run(TEST_OS=system, TEST_CPU=cpu)
    assert result.returncode == 0, result.stderr
    binary = Path(env['EIRENE_INSTALL_DIR']) / 'eirene'
    assert os.access(binary, os.X_OK)
    assert subprocess.check_output([str(binary), '--version'], text=True).strip() == 'Eirene fixture'
    requests = Path(env['TEST_LOG']).read_text()
    assert f'/v1.2.3/eirene-{target}-1.2.3.tar.gz' in requests
    assert 'SHA256SUMS' not in requests


def test_installer_detects_apple_silicon_through_rosetta(installer):
    run, _, _ = installer
    assert run(TEST_OS='Darwin', TEST_CPU='x86_64', TEST_SILICON='1').returncode == 0


@pytest.mark.parametrize('kind', ['archive', 'download'])
def test_installer_failure_preserves_existing_binary(installer, kind):
    run, env, fixture = installer
    assert run().returncode == 0
    binary = Path(env['EIRENE_INSTALL_DIR']) / 'eirene'
    original = binary.read_bytes()
    if kind == 'archive':
        (fixture / 'eirene-Linux-amd64-1.2.3.tar.gz').write_bytes(b'broken archive')
        result = run()
        assert 'extracting the release archive' in result.stderr
    else:
        result = run(TEST_FAIL_DOWNLOAD='1')
    assert result.returncode != 0
    assert binary.read_bytes() == original


@pytest.mark.parametrize('version', ['v2.3.4', 'v0.1.7b1'])
def test_installer_pinned_version_and_path_update_are_repeatable(installer, version):
    run, env, _ = installer
    for _ in range(2):
        result = run(EIRENE_VERSION=version, EIRENE_NO_PATH='0')
        assert result.returncode == 0, result.stderr
    profile = (Path(env['HOME']) / '.bashrc').read_text()
    assert profile.count('# Eirene') == 1
    assert '/releases/latest' not in Path(env['TEST_LOG']).read_text()


@pytest.mark.parametrize('system,cpu', [('Linux', 'riscv64'), ('Darwin', 'x86_64'), ('FreeBSD', 'amd64'), ('MINGW64_NT', 'x86_64')])
def test_unsupported_hosts_fail_before_downloading(installer, system, cpu):
    run, env, _ = installer
    result = run(TEST_OS=system, TEST_CPU=cpu, TEST_SILICON='0')
    assert result.returncode != 0
    assert not Path(env['TEST_LOG']).exists()


@pytest.mark.parametrize('shell,system,expected', [
    ('/bin/bash', 'Linux', ['.bashrc', '.profile']),
    ('/bin/bash', 'Darwin', ['.bashrc', '.bash_profile']),
    ('/bin/zsh', 'Darwin', ['.zshrc', '.zprofile']),
    ('/bin/sh', 'Linux', ['.profile']),
    ('/bin/fish', 'Linux', ['.config/fish/conf.d/eirene.fish']),
])
def test_installer_persists_path_for_the_users_shell(installer, shell, system, expected):
    run, env, _ = installer
    # Already in this process's PATH does not mean future shells have it.
    result = run(SHELL=shell, TEST_OS=system, TEST_CPU='arm64', EIRENE_NO_PATH='0',
                 PATH=env['EIRENE_INSTALL_DIR'] + os.pathsep + env['PATH'],
                 XDG_CONFIG_HOME=str(Path(env['HOME']) / '.config'), ZDOTDIR=env['HOME'])
    assert result.returncode == 0, result.stderr
    for name in expected:
        assert '# Eirene' in (Path(env['HOME']) / name).read_text()
    assert 'Start now:' in result.stdout
    assert '/connect' in result.stdout
    assert 'new terminal' in result.stdout


@pytest.mark.parametrize('profile', ['.bash_profile', '.bash_login', '.profile'])
def test_installer_preserves_and_backs_up_existing_login_profile(installer, profile):
    run, env, _ = installer
    path = Path(env['HOME']) / profile
    original = '# user settings\nexport MY_SETTING=kept\n'
    path.write_text(original)
    for _ in range(2):
        result = run(EIRENE_NO_PATH='0')
        assert result.returncode == 0, result.stderr
    assert path.read_text().startswith(original)
    backups = list(path.parent.glob(profile + '.eirene-backup.*'))
    assert len(backups) == 1
    assert backups[0].read_text() == original
    assert path.read_text().count('# Eirene') == 1


def test_installer_quotes_paths_and_sourcing_does_not_duplicate_path(installer):
    run, env, _ = installer
    directory = str(Path(env['HOME']) / "space ' quote $dollar `backtick` \\ backslash")
    result = run(EIRENE_INSTALL_DIR=directory, EIRENE_NO_PATH='0', SHELL='/bin/sh')
    assert result.returncode == 0, result.stderr
    profile = str(Path(env['HOME']) / '.profile')
    sourced = subprocess.run(['sh', '-c', '. "$1"; . "$1"; printf "%s" "$PATH"', 'sh', profile],
                             env=env, capture_output=True, text=True, check=True)
    assert sourced.stdout.split(os.pathsep).count(directory) == 1


def test_installer_respects_zdotdir(installer):
    run, env, _ = installer
    directory = Path(env['HOME']) / 'zsh settings'
    result = run(EIRENE_NO_PATH='0', SHELL='/bin/zsh', ZDOTDIR=str(directory))
    assert result.returncode == 0, result.stderr
    assert (directory / '.zshrc').exists()
    assert (directory / '.zprofile').exists()
    assert not (Path(env['HOME']) / '.zshrc').exists()


def test_profile_failure_keeps_installed_binary_and_prints_recovery(installer):
    run, env, _ = installer
    (Path(env['HOME']) / '.bashrc').mkdir()
    result = run(EIRENE_NO_PATH='0')
    assert result.returncode == 0, result.stderr
    assert 'PATH could not be saved' in result.stderr
    assert (Path(env['EIRENE_INSTALL_DIR']) / 'eirene').exists()
    assert 'Start now:' in result.stdout
    assert 'Open a new terminal and run: eirene' not in result.stdout


def test_path_opt_out_does_not_touch_profiles(installer):
    run, env, _ = installer
    result = run()
    assert result.returncode == 0, result.stderr
    assert not (Path(env['HOME']) / '.bashrc').exists()
    assert 'PATH setup skipped' in result.stdout


def test_bad_executable_leaves_previous_installation_intact(installer):
    run, env, fixture = installer
    assert run().returncode == 0
    installed = Path(env['EIRENE_INSTALL_DIR']) / 'eirene'
    original = installed.read_bytes()
    bad = fixture / 'broken'
    bad.write_text('#!/bin/sh\nexit 42\n')
    archive = packager.package('linux-amd64', bad, fixture, '1.2.3')
    (fixture / 'SHA256SUMS').write_text(checksum_entry(archive))
    result = run()
    assert result.returncode != 0
    assert 'could not run' in result.stderr
    assert installed.read_bytes() == original
    assert not list(installed.parent.glob('.eirene.*'))


def test_download_failure_explains_recovery(installer):
    run, _, _ = installer
    result = run(TEST_FAIL_DOWNLOAD='1')
    assert result.returncode != 0
    assert 'downloading' in result.stderr
    assert 'not been replaced' in result.stderr


def test_invalid_path_fails_before_download(installer):
    run, env, _ = installer
    result = run(EIRENE_INSTALL_DIR=env['HOME'] + '/bad:path')
    assert result.returncode != 0
    assert not Path(env['TEST_LOG']).exists()


def test_installer_configures_multiple_detected_shells(installer):
    run, env, _ = installer
    tools = Path(env['PATH'].split(os.pathsep)[0])
    for shell in ('zsh', 'fish', 'ksh', 'csh', 'tcsh', 'pwsh', 'nu'):
        executable = tools / shell
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
    overrides = dict(EIRENE_NO_PATH='0', SHELL='/bin/bash',
                     ZDOTDIR=env['HOME'], XDG_CONFIG_HOME=str(Path(env['HOME']) / '.config'))
    for _ in range(2):
        result = run(**overrides)
        assert result.returncode == 0, result.stderr
    for name in ('.bashrc', '.profile', '.zshrc', '.zprofile', '.kshrc',
                 '.cshrc', '.tcshrc', '.config/fish/conf.d/eirene.fish',
                 '.config/powershell/profile.ps1', '.config/nushell/env.nu'):
        text = (Path(env['HOME']) / name).read_text()
        assert text.count('# Eirene') == 1, name
        assert env['EIRENE_INSTALL_DIR'] in text, name
    assert 'Sourced .bashrc and verified eirene' in result.stdout


def test_installer_sources_bashrc_with_normal_interactive_guard(installer):
    run, env, _ = installer
    marker = Path(env['HOME']) / 'sourced'
    profile = Path(env['HOME']) / '.bashrc'
    profile.write_text('case $- in *i*) ;; *) return ;; esac\nprintf sourced > "$HOME/sourced"\n')
    result = run(EIRENE_NO_PATH='0')
    assert result.returncode == 0, result.stderr
    assert marker.read_text() == 'sourced'
    assert 'Sourced .bashrc and verified eirene' in result.stdout


@pytest.mark.parametrize('exit_code', [0, 9])
def test_bash_startup_failure_does_not_claim_shell_is_ready(installer, exit_code):
    run, env, _ = installer
    (Path(env['HOME']) / '.bashrc').write_text(f'exit {exit_code}\n')
    result = run(EIRENE_NO_PATH='0')
    assert result.returncode == 0, result.stderr
    assert 'Bash startup verification failed' in result.stderr
    assert 'Open a new terminal and run: eirene' not in result.stdout
    assert (Path(env['EIRENE_INSTALL_DIR']) / 'eirene').exists()


def test_staged_help_failure_preserves_existing_binary(installer):
    run, env, fixture = installer
    assert run().returncode == 0
    installed = Path(env['EIRENE_INSTALL_DIR']) / 'eirene'
    original = installed.read_bytes()
    bad = fixture / 'broken-help'
    bad.write_text('#!/bin/sh\nif [ "$1" = --help ]; then exit 7; fi\necho version\n')
    archive = packager.package('linux-amd64', bad, fixture, '1.2.3')
    (fixture / 'SHA256SUMS').write_text(checksum_entry(archive))
    result = run()
    assert result.returncode != 0
    assert 'failed --help' in result.stderr
    assert installed.read_bytes() == original


def test_shell_configuration_mode_does_not_download_or_replace_binary(installer):
    run, env, _ = installer
    assert run().returncode == 0
    binary = Path(env['EIRENE_INSTALL_DIR']) / 'eirene'
    original = binary.read_bytes()
    request_log = Path(env['TEST_LOG'])
    original_requests = request_log.read_text()
    result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--configure-shells'],
                            env={**env, 'EIRENE_NO_PATH': '0'}, capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert binary.read_bytes() == original
    assert request_log.read_text() == original_requests
    assert (Path(env['HOME']) / '.bashrc').exists()


def test_redirected_installer_has_readable_steps_and_no_escape_codes(installer):
    run, _, _ = installer
    result = run(NO_COLOR='1')
    assert result.returncode == 0, result.stderr
    for number in range(1, 8):
        assert f'[{number}/7]' in result.stdout
    assert '\x1b' not in result.stdout + result.stderr
    assert 'Executable extracted' in result.stdout
    assert 'SHA256SUMS' not in Path(installer[1]['TEST_LOG']).read_text()
    assert all(not line.startswith(' ') for line in result.stdout.splitlines())


@pytest.mark.parametrize('system', ['Linux', 'Darwin'])
@pytest.mark.parametrize('job_control', [False, True])
def test_slow_bash_profile_has_portable_deadline_and_stops_children(installer, system, job_control):
    import time

    run, env, _ = installer
    profile = Path(env['HOME']) / '.bashrc'
    profile.write_text(('set -m\n' if job_control else '') +
                       'sh -c \'trap "" TERM; echo $$ > "$HOME/profile-child.pid"; sleep 30\'\n')
    # The portable watchdog must work even with no usable timeout utility.
    tools = Path(env['PATH'].split(os.pathsep)[0])
    timeout = tools / 'timeout'
    timeout.write_text('#!/bin/sh\nexit 99\n')
    timeout.chmod(0o755)
    started = time.monotonic()
    result = run(EIRENE_NO_PATH='0', TEST_OS=system, TEST_CPU='arm64')
    assert time.monotonic() - started < 8
    assert result.returncode == 0, result.stderr
    assert 'Bash startup exceeded 4 seconds' in result.stderr
    assert 'Checking .bashrc (up to 4 seconds)' in result.stdout
    assert 'Start now:' in result.stdout
    assert 'Open a new terminal and run: eirene' not in result.stdout
    pid = (Path(env['HOME']) / 'profile-child.pid').read_text().strip()
    state = subprocess.run(['ps', '-o', 'stat=', '-p', pid], capture_output=True, text=True)
    assert not state.stdout.strip() or state.stdout.strip().startswith('Z')


def test_watchdog_finishes_cleanup_when_profile_shell_exits_on_term(installer, tmp_path):
    import signal
    import time

    run, env, _ = installer
    home = Path(env['HOME'])
    (home / '.bashrc').write_text(
        'sh -c \'trap "" TERM; echo $$ > "$HOME/profile-child.pid"; '
        'echo $PPID > "$HOME/profile-parent.pid"; sleep 30\'\n')
    # Reproduce macOS's early shell exit even when this test runs on Linux.
    # The watchdog's group TERM still reaches the resistant child, but the
    # group leader is forced to exit before the delayed group KILL.
    environment = tmp_path / 'early-exit.bash'
    environment.write_text('''
kill() {
    builtin kill "$@"
    status=$?
    if [[ "$1" == -TERM && -f "$HOME/profile-parent.pid" ]]; then
        parent=$(cat "$HOME/profile-parent.pid")
        if [[ "${3:-}" == "-$parent" ]]; then
            builtin kill -KILL "$parent" 2>/dev/null
        fi
    fi
    return "$status"
}
''')
    try:
        started = time.monotonic()
        result = run(EIRENE_NO_PATH='0', BASH_ENV=str(environment))
        assert time.monotonic() - started < 8
        assert result.returncode == 0, result.stderr
        assert 'Bash startup exceeded 4 seconds' in result.stderr
        pid = (home / 'profile-child.pid').read_text().strip()
        state = subprocess.run(['ps', '-o', 'stat=', '-p', pid], capture_output=True, text=True)
        assert not state.stdout.strip() or state.stdout.strip().startswith('Z')
    finally:
        parent_file = home / 'profile-parent.pid'
        if parent_file.exists():
            try:
                os.killpg(int(parent_file.read_text().strip()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_installer_runs_only_three_executable_checks(installer):
    run, env, fixture = installer
    binary = fixture / 'counted'
    binary.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$HOME/binary-checks"\necho fixture\n')
    archive = packager.package('linux-amd64', binary, fixture, '1.2.3')
    (fixture / 'SHA256SUMS').write_text(checksum_entry(archive))
    result = run(EIRENE_NO_PATH='0')
    assert result.returncode == 0, result.stderr
    assert (Path(env['HOME']) / 'binary-checks').read_text().splitlines() == [
        '--version', '--help', '--version']


def test_terminal_installer_displays_portrait_and_requests_live_progress(installer):
    if os.name == 'nt':
        pytest.skip('POSIX terminal test')
    import errno
    import pty
    import select
    import time

    _, env, _ = installer
    master, slave = pty.openpty()
    process = subprocess.Popen(['bash', str(ROOT / 'install.sh')],
                               env={**env, 'TERM': 'xterm-256color', 'COLUMNS': '80'},
                               stdin=subprocess.DEVNULL, stdout=slave, stderr=slave)
    os.close(slave)
    output = bytearray()
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if not ready:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            output.extend(chunk)
        assert process.wait(timeout=2) == 0, output.decode()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
    import re
    text = re.sub(r'\x1b\[[0-9;]*m', '', output.decode())
    assert '⠻⣷' in text
    assert '[3/7] Download' in text
    assert '--progress-bar' in Path(env['TEST_LOG']).read_text()


@pytest.mark.parametrize('arguments,version', [(['edge'], 'latest'), (['--edge'], 'v1.2.3'), ([], 'edge')])
def test_edge_installs_newest_published_prerelease(installer, arguments, version):
    run, env, _ = installer
    releases = [
        dict(tag_name='v2.3.4', prerelease=False, draft=False, published_at='2026-10-17T00:00:00Z'),
        dict(tag_name='v99b1', prerelease=True, draft=True, published_at='2026-10-18T00:00:00Z'),
        dict(tag_name='v1.0b1', prerelease=True, draft=False, published_at='2026-10-14T00:00:00Z',
             assets=[dict(name='nested {asset}', published_at='2026-10-19T00:00:00Z')]),
        dict(tag_name='v0.1.7b1', prerelease=True, draft=False, published_at='2026-10-16T00:00:00Z',
             body='A quote " and a brace } should not affect parsing.'),
    ]
    result = run(*arguments, EIRENE_VERSION=version, TEST_RELEASES=json.dumps(releases))
    assert result.returncode == 0, result.stderr
    requests = Path(env['TEST_LOG']).read_text()
    assert '/v0.1.7b1/eirene-Linux-amd64-0.1.7b1.tar.gz' in requests
    assert '--connect-timeout 30 --max-time 600' in requests
    assert '/releases/latest' not in requests


def test_edge_without_prereleases_preserves_existing_install(installer):
    run, env, _ = installer
    assert run().returncode == 0
    binary = Path(env['EIRENE_INSTALL_DIR']) / 'eirene'
    original = binary.read_bytes()
    result = run('edge', TEST_RELEASES='[]')
    assert result.returncode != 0
    assert 'no published unstable release' in result.stderr
    assert binary.read_bytes() == original


def test_installer_rejects_unknown_arguments(installer):
    result = installer[0]('--typo')
    assert result.returncode != 0
    assert 'unknown argument' in result.stderr


def test_edge_checks_later_release_pages(installer):
    run, env, _ = installer
    first_page = [dict(tag_name=f'v1.0.{i}', prerelease=False, draft=False) for i in range(100)]
    second_page = [dict(tag_name='v0.1.7b1', prerelease=True, draft=False,
                        published_at='2026-10-16T00:00:00Z')]
    pages = {'1': json.dumps(first_page, indent=2), '2': json.dumps(second_page, indent=2)}
    result = run('edge', TEST_RELEASE_PAGES=json.dumps(pages))
    assert result.returncode == 0, result.stderr
    requests = Path(env['TEST_LOG']).read_text()
    assert 'per_page=100&page=2' in requests
    assert '/v0.1.7b1/eirene-Linux-amd64-0.1.7b1.tar.gz' in requests


@pytest.fixture
def termux_installer(installer):
    run, env, fixture = installer
    tools = Path(env['PATH'].split(os.pathsep)[0])
    state = fixture / 'installed.json'
    apt_log = fixture / 'apt.log'
    versions = ('0.1.20b1', '0.1.20b2', '0.1.20')
    for version in versions:
        debian_version = version.replace('b', '~b')
        (fixture / f'eirene-Termux-aarch64-{version}.deb').write_text(json.dumps({
            'Package': 'eirene', 'Architecture': 'aarch64', 'Version': debian_version,
            'runtime': version}))
    (fixture / 'SHA256SUMS').write_text(''.join(checksum_entry(p) for p in sorted(fixture.glob('*.deb'))))
    scripts = {
        'dpkg-deb': '''import json, sys
from pathlib import Path
print(json.loads(Path(sys.argv[2]).read_text())[sys.argv[3]])
''',
        'dpkg-query': '''import json, os, sys
from pathlib import Path
state = Path(os.environ['TEST_INSTALLED'])
if not state.exists(): sys.exit(1)
print('install ok installed')
print(json.loads(state.read_text())['Version'])
''',
        'dpkg': '''import sys
from packaging.version import Version
assert sys.argv[1] == '--compare-versions' and sys.argv[3] == 'gt'
sys.exit(0 if Version(sys.argv[2].replace('~', '')) > Version(sys.argv[4].replace('~', '')) else 1)
''',
        'sha256sum': '''import hashlib, sys
from pathlib import Path
print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest() + '  ' + sys.argv[1])
''',
        'apt-get': '''import json, os, sys
from pathlib import Path
with open(os.environ['TEST_APT_LOG'], 'a') as stream: stream.write(json.dumps(sys.argv[1:]) + '\\n')
if os.environ.get('TEST_APT_FAIL') in ('1', sys.argv[1]): sys.exit(17)
if sys.argv[1] == 'update': sys.exit(0)
assert sys.argv[1] == 'install' and '-y' in sys.argv
package = json.loads(Path(sys.argv[-1]).read_text())
Path(os.environ['TEST_INSTALLED']).write_text(json.dumps(package))
binary = Path(os.environ['TEST_BIN']) / 'eirene'
binary.write_text('#!/bin/sh\\nif [ "$1" = --version ]; then echo "eirene ' + package['runtime'] + '"; else echo "Eirene usage"; fi\\n')
binary.chmod(0o755)
''',
    }
    for name, body in scripts.items():
        path = tools / name
        path.write_text(f'#!{sys.executable}\n' + body)
        path.chmod(0o755)

    def release(version, date, *, prerelease=True, uploaded=True):
        return dict(tag_name='v' + version, draft=False, prerelease=prerelease, published_at=date,
                    assets=[dict(name=f'eirene-Termux-aarch64-{version}.deb',
                                 state='uploaded' if uploaded else 'new')])

    releases = [
        dict(tag_name='v9.0.0', draft=False, prerelease=False, published_at='2026-10-24T00:00:00Z',
             assets=[dict(name='eirene-Linux-arm64-9.0.0.tar.gz', state='uploaded')]),
        release('0.1.20b2', '2026-10-23T00:00:00Z'),
        release('0.1.20b1', '2026-10-22T00:00:00Z'),
    ]
    base = dict(PREFIX='/data/data/com.termux/files/usr', TERMUX_VERSION='0.118.0',
                TEST_OS='Linux', TEST_CPU='aarch64', EIRENE_INSTALL_DIR='/data/data/com.termux/files/usr/bin',
                TEST_RELEASES=json.dumps(releases), TEST_INSTALLED=str(state),
                TEST_BIN=str(tools), TEST_APT_LOG=str(apt_log))

    def install(*args, **overrides):
        return run(*args, **{**base, **overrides})
    return install, env, fixture, state, apt_log, release


def test_termux_installer_installs_and_upgrades_with_apt(termux_installer):
    run, env, _, state, apt_log, _ = termux_installer
    first = run(EIRENE_VERSION='v0.1.20b1')
    assert first.returncode == 0, first.stderr
    assert json.loads(state.read_text())['Version'] == '0.1.20~b1'
    updated = run()
    assert updated.returncode == 0, updated.stderr
    assert json.loads(state.read_text())['Version'] == '0.1.20~b2'
    assert [json.loads(row)[0] for row in apt_log.read_text().splitlines()] == ['update', 'install'] * 2
    requests = Path(env['TEST_LOG']).read_text()
    assert 'eirene-Termux-aarch64-0.1.20b2.deb' in requests and 'SHA256SUMS' in requests
    assert 'eirene-Linux-arm64' not in requests and '/releases/latest' not in requests
    assert 'may be a beta' in updated.stdout
    assert not (Path(env['HOME']) / '.bashrc').exists()


@pytest.mark.parametrize('problem', ['checksum', 'identity', 'architecture', 'version', 'duplicate_checksum'])
def test_termux_rejects_invalid_package_before_apt(termux_installer, problem):
    run, _, fixture, state, apt_log, _ = termux_installer
    package = fixture / 'eirene-Termux-aarch64-0.1.20b2.deb'
    body = json.loads(package.read_text())
    if problem == 'checksum':
        package.write_bytes(b'corrupted')
    elif problem == 'duplicate_checksum':
        manifest = fixture / 'SHA256SUMS'
        manifest.write_text(manifest.read_text() + checksum_entry(package))
    else:
        field = {'identity': 'Package', 'architecture': 'Architecture', 'version': 'Version'}[problem]
        body[field] = 'wrong'
        package.write_text(json.dumps(body))
        (fixture / 'SHA256SUMS').write_text(checksum_entry(package))
    result = run()
    assert result.returncode != 0
    assert not state.exists() and not apt_log.exists()


def test_termux_installer_does_not_downgrade(termux_installer):
    run, _, _, state, apt_log, _ = termux_installer
    assert run().returncode == 0
    original = state.read_bytes(), apt_log.read_bytes()
    result = run(EIRENE_VERSION='v0.1.20b1')
    assert result.returncode != 0 and 'refusing to downgrade' in result.stderr
    assert (state.read_bytes(), apt_log.read_bytes()) == original


@pytest.mark.parametrize('cpu', ['x86_64', 'armv7l'])
def test_termux_unsupported_architecture_fails_before_download(termux_installer, cpu):
    run, env, _, _, apt_log, _ = termux_installer
    result = run(TEST_CPU=cpu)
    assert result.returncode != 0 and 'unsupported Termux architecture' in result.stderr
    assert not Path(env['TEST_LOG']).exists() and not apt_log.exists()


def test_termux_latest_and_edge_select_matching_uploaded_assets(termux_installer):
    run, env, _, state, _, release = termux_installer
    stable = release('0.1.20', '2026-10-24T00:00:00Z', prerelease=False)
    beta = release('0.1.20b2', '2026-10-23T00:00:00Z')
    uploading = release('0.1.20b3', '2026-10-25T00:00:00Z', uploaded=False)
    draft = {**release('0.1.20b4', '2026-10-26T00:00:00Z'), 'draft': True}
    metadata = json.dumps([uploading, stable, draft, beta], indent=2)
    # Edge must skip a newer stable release; default Android installation may use it.
    result = run('edge', TEST_RELEASES=metadata)
    assert result.returncode == 0, result.stderr
    assert json.loads(state.read_text())['runtime'] == '0.1.20b2'
    result = run(TEST_RELEASES=metadata)
    assert result.returncode == 0, result.stderr
    assert json.loads(state.read_text())['runtime'] == '0.1.20'
    assert '/v0.1.20/eirene-Termux-aarch64-0.1.20.deb' in Path(env['TEST_LOG']).read_text()


def test_termux_skips_releases_without_matching_packages(termux_installer):
    run, _, _, state, apt_log, _ = termux_installer
    result = run(TEST_RELEASES=json.dumps([dict(tag_name='v9.0.0', draft=False, prerelease=True,
                    published_at='2026-10-24T00:00:00Z',
                    body='"name": "eirene-Termux-aarch64-9.0.0.deb"',
                    author=dict(name='eirene-Termux-aarch64-9.0.0.deb'),
                    assets=[dict(name='other.deb', state='uploaded')])]))
    assert result.returncode != 0 and 'no compatible published Termux package' in result.stderr
    assert not state.exists() and not apt_log.exists()


@pytest.mark.parametrize(('stage', 'message'), [
    ('update', 'refreshing Termux package indexes'),
    ('install', 'installing or upgrading the Eirene package'),
])
def test_termux_package_install_failure_is_reported(termux_installer, stage, message):
    run, _, _, _, _, _ = termux_installer
    result = run(TEST_APT_FAIL=stage)
    assert result.returncode != 0 and message in result.stderr
    if stage == 'install':
        assert 'existing executable was not changed' not in result.stderr


def test_termux_release_selection_checks_later_pages(termux_installer):
    run, env, _, state, _, release = termux_installer
    first_page = [dict(tag_name=f'v9.0.{n}', draft=False, prerelease=False,
                       published_at='2026-10-24T00:00:00Z', assets=[]) for n in range(100)]
    package = release('0.1.20b2', '2026-10-23T00:00:00Z')
    package['assets'][0]['uploader'] = dict(name='other.deb', state='new')
    pages = {'1': json.dumps(first_page), '2': json.dumps([package], indent=2)}
    result = run(TEST_RELEASE_PAGES=json.dumps(pages))
    assert result.returncode == 0, result.stderr
    assert json.loads(state.read_text())['runtime'] == '0.1.20b2'
    assert 'per_page=100&page=2' in Path(env['TEST_LOG']).read_text()


def test_termux_rejects_custom_install_directory(termux_installer):
    run, env, _, _, _, _ = termux_installer
    result = run(EIRENE_INSTALL_DIR=env['HOME'] + '/bin')
    assert result.returncode != 0 and 'custom EIRENE_INSTALL_DIR is unsupported' in result.stderr
    assert not Path(env['TEST_LOG']).exists()
