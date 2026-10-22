#!/usr/bin/env python3
"""Build an experimental .deb inside the official native Termux container."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PACKAGES = {'cffi', 'cryptography', 'pillow', 'rpds-py'}


def run(*argv, **kwargs):
    print('»', ' '.join(map(str, argv)), flush=True)
    subprocess.run(list(map(str, argv)), check=True, **kwargs)


def main():
    from release_metadata import read_version, is_prerelease
    version = read_version(ROOT / 'pyproject.toml')
    if not is_prerelease(version):
        raise SystemExit('Termux packaging is experimental: use a prerelease version')
    prefix = Path(os.environ['PREFIX'])
    if str(prefix) != '/data/data/com.termux/files/usr':
        raise SystemExit('Only the standard com.termux prefix is supported')
    if subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip() != 'aarch64':
        raise SystemExit('The experimental package currently targets aarch64 only')
    python_version = f'{sys.version_info.major}.{sys.version_info.minor}'
    if python_version != '3.14':
        raise SystemExit('This beta targets Termux Python 3.14')
    # Termux targets Android API 24; its container cannot infer this from an
    # Android system runtime, so maturin needs an explicit wheel platform level.
    os.environ.setdefault('ANDROID_API_LEVEL', '24')
    lock = tomllib.loads((ROOT / 'uv.lock').read_text())
    core = next(p for p in lock['package'] if p['name'] == 'pydantic-core')
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='eirene-termux-') as temporary:
        work = Path(temporary)
        source = work / 'core.tar.gz'
        with urlopen(core['sdist']['url'], timeout=120) as response:
            source.write_bytes(response.read())
        assert hashlib.sha256(source.read_bytes()).hexdigest() == core['sdist']['hash'].split(':')[1]
        with tarfile.open(source) as archive:
            archive.extractall(work / 'core', filter='data')
        core_root, = (work / 'core').iterdir()
        wheels = work / 'wheels'
        run('maturin', 'build', '--release', '--interpreter', sys.executable,
            '--out', wheels, cwd=core_root)
        stage = work / 'package'
        home = stage / prefix.relative_to('/') / 'share/eirene'
        vendor = home / 'vendor'
        vendor.mkdir(parents=True)
        requirements = Path('/input/requirements.txt').read_text()
        requirements = '\n'.join(line for line in requirements.splitlines()
            if not re.match(r'^(?:' + '|'.join(SYSTEM_PACKAGES | {'pydantic-core'}) + r')==', line))
        required = work / 'requirements.txt'
        required.write_text(requirements + '\n')
        run(sys.executable, '-m', 'pip', 'install', '--no-deps', '--no-build-isolation',
            '--target', vendor, '-r', required, *sorted(wheels.glob('*.whl')))
        for library in (vendor / 'pydantic_core').glob('*.so'):
            run('patchelf', '--add-needed', f'libpython{python_version}.so', library)
        app = home / 'app'
        shutil.copytree(ROOT / 'eirene', app / 'eirene', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for filename in ('pyproject.toml', 'LICENSE', 'NOTICE'):
            shutil.copy2(ROOT / filename, app / filename)
        shutil.copytree(ROOT / 'img', app / 'img')
        (home / 'launch.py').write_text(
            'import sys\nfrom pathlib import Path\n'
            'root = Path(__file__).resolve().parent\n'
            'sys.path[:0] = [str(root / "app"), str(root / "vendor")]\n'
            'from eirene.__main__ import main\nraise SystemExit(main())\n')
        binary = stage / prefix.relative_to('/') / 'bin/eirene'
        binary.parent.mkdir(parents=True)
        binary.write_text(f'#!{prefix}/bin/sh\nexec {prefix}/bin/python {prefix}/share/eirene/launch.py "$@"\n')
        binary.chmod(0o755)
        control = stage / 'DEBIAN'
        control.mkdir()
        deb_version = re.sub(r'(a|b|rc)(\d+)$', r'~\1\2', version)
        native = {p['name']: p['version'] for p in lock['package'] if p['name'] in SYSTEM_PACKAGES}
        dependencies = ['bash', 'python (>= 3.14)', 'python (<< 3.15)']
        dependencies += [f'python-{name} (>= {native[name]})' for name in ('cryptography', 'pillow', 'rpds-py')]
        (control / 'control').write_text(
            f'Package: eirene\nVersion: {deb_version}\nArchitecture: aarch64\n'
            'Maintainer: Eirene maintainers <noreply@github.com>\n'
            'Homepage: https://github.com/0v3rf3ar/Eirene\n'
            'Description: Experimental Eirene beta for Termux (Android ARM64)\n'
            f'Depends: {", ".join(dependencies)}\n')
        package = output / f'eirene-Termux-aarch64-{version}.deb'
        run('dpkg-deb', '--build', '--root-owner-group', stage, package)
        run('dpkg', '--install', package)
        env = dict(os.environ, PYTHONPATH=f'{prefix}/share/eirene/app:{prefix}/share/eirene/vendor',
                   EIRENE_HOME=str(work / 'data'), EIRENE_NO_UPDATE_CHECK='1')
        run(prefix / 'bin/eirene', '--version', env=env)
        run(prefix / 'bin/eirene', '--doctor', '--json', env=env)
        run(sys.executable, ROOT / 'scripts/smoke_termux.py', env=env)
        run(sys.executable, ROOT / 'scripts/smoke_binary_ui.py', prefix / 'bin/eirene', env=env)
        (output / 'termux-build.txt').write_text(
            f'Version: {version}\nPython: {sys.version}\nArchitecture: aarch64\n'
            'Runtime: official Termux Docker container (Android/Bionic userspace)\n'
            'Passed: native imports, CLI, doctor, approved shell, file reads, PTY UI\n'
            'Physical Android device validation: not performed\n')


if __name__ == '__main__':
    main()
