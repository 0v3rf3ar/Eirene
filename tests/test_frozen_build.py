"""Staged publication and stable archives for lazy imports in frozen apps."""
import importlib.util
import os
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest


def load(relative):
    path=Path(__file__).resolve().parents[1]/relative
    spec=importlib.util.spec_from_file_location('build_test_module',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failed_build_preserves_published_binary(tmp_path,monkeypatch):
    build=load('build.py')
    dist=tmp_path/'dist'; dist.mkdir()
    target=dist/('eirene.exe' if os.name=='nt' else 'eirene')
    target.write_bytes(b'working binary')
    monkeypatch.setattr(build,'run',lambda argv:1)
    with pytest.raises(SystemExit):
        build.freeze(Path(sys.executable),dist,tmp_path/'work')
    assert target.read_bytes()==b'working binary'
    assert list(dist.iterdir())==[target]


def test_failed_smoke_preserves_published_binary(tmp_path,monkeypatch):
    build=load('build.py')
    dist=tmp_path/'dist'; dist.mkdir()
    target=dist/('eirene.exe' if os.name=='nt' else 'eirene')
    target.write_bytes(b'working binary')
    def assemble(argv):
        (Path(argv[argv.index('--distpath')+1])/target.name).write_bytes(b'bad binary')
        return 0
    def smoke(path):
        assert path!=target
        assert target.read_bytes()==b'working binary'
        raise RuntimeError('invalid archive')
    monkeypatch.setattr(build,'run',assemble)
    monkeypatch.setattr(build,'smoke',smoke)
    with pytest.raises(RuntimeError,match='invalid archive'):
        build.freeze(Path(sys.executable),dist,tmp_path/'work')
    assert target.read_bytes()==b'working binary'


def test_ci_build_can_publish_without_running_binary_smoke(tmp_path, monkeypatch):
    build = load('build.py')
    dist = tmp_path / 'dist'
    name = 'eirene.exe' if os.name == 'nt' else 'eirene'
    def assemble(argv):
        (Path(argv[argv.index('--distpath') + 1]) / name).write_bytes(b'built binary')
        return 0
    def smoke(path):
        pytest.fail('CI requested a build without per-platform smoke checks')
    monkeypatch.setattr(build, 'run', assemble)
    monkeypatch.setattr(build, 'smoke', smoke)
    binary = build.freeze(Path(sys.executable), dist, tmp_path / 'work', check_binary=False)
    assert binary == dist / name
    assert binary.read_bytes() == b'built binary'


@pytest.mark.skipif(not sys.platform.startswith('linux'),reason='Linux executable handle')
def test_linux_pins_original_executable_handle():
    hook=load('build/runtime_hook.py')
    archive=SimpleNamespace(_filename=sys.executable,_start_offset=123)
    hook.pin_archive(archive,sys.executable,platform='linux')
    assert archive._filename=='/proc/self/exe'
    assert archive._start_offset==123


def test_snapshot_keeps_original_import_bytes_after_replacement(tmp_path):
    hook=load('build/runtime_hook.py')
    executable=tmp_path/'eirene'
    original=zlib.compress(b'original module code')
    executable.write_bytes(b'header'+original)
    archive=SimpleNamespace(_filename=str(executable),_start_offset=6)
    hook.pin_archive(archive,str(executable),platform='darwin')
    try:
        replacement=tmp_path/'new'
        replacement.write_bytes(b'different offsets and archive contents')
        os.replace(replacement,executable)
        assert archive._start_offset==0
        assert zlib.decompress(Path(archive._filename).read_bytes())==b'original module code'
    finally:
        Path(archive._filename).unlink(missing_ok=True)
