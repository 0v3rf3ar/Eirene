"""Archive and installer contracts without accessing GitHub or the user's home."""
from __future__ import annotations

import hashlib
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
    checksum = archive.with_name(archive.name + '.sha256').read_bytes()
    assert checksum == f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n'.encode('ascii')


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
    (fixture / 'SHA256SUMS').write_text(''.join(p.read_text() for p in sorted(fixture.glob('*.sha256'))))
    (tools / 'uname').write_text('#!/bin/sh\nif [ "$1" = -s ]; then echo "$TEST_OS"; else echo "$TEST_CPU"; fi\n')
    (tools / 'sysctl').write_text('#!/bin/sh\necho "${TEST_SILICON:-0}"\n')
    (tools / 'curl').write_text(f'#!{sys.executable}\n' + '''import os, sys, shutil
from pathlib import Path
args = sys.argv[1:]
url = args[-1]
with open(os.environ['TEST_LOG'], 'a') as stream: stream.write(url + '\\n')
if url.endswith('/releases/latest'):
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
    def run(**overrides):
        return subprocess.run(['bash', str(ROOT / 'install.sh')], env={**env, **overrides},
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
    assert '/v1.2.3/SHA256SUMS' in requests


def test_installer_detects_apple_silicon_through_rosetta(installer):
    run, _, _ = installer
    assert run(TEST_OS='Darwin', TEST_CPU='x86_64', TEST_SILICON='1').returncode == 0


@pytest.mark.parametrize('kind', ['checksum', 'download'])
def test_installer_failure_preserves_existing_binary(installer, kind):
    run, env, fixture = installer
    assert run().returncode == 0
    binary = Path(env['EIRENE_INSTALL_DIR']) / 'eirene'
    original = binary.read_bytes()
    if kind == 'checksum':
        (fixture / 'SHA256SUMS').write_text('0' * 64 + '  eirene-Linux-amd64-1.2.3.tar.gz\n')
        result = run()
        assert 'checksum mismatch' in result.stderr
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
    (fixture / 'SHA256SUMS').write_text(archive.with_name(archive.name + '.sha256').read_text())
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
