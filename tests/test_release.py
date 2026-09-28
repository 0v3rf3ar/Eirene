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
