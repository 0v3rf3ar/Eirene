"""GitHub prerelease classification and manifest/tag agreement."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_metadata', ROOT / 'scripts/release_metadata.py')
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


@pytest.mark.parametrize('version,expected', [
    ('0.2.0a1', True), ('0.2.0a10', True), ('0.2.0b1', True),
    ('0.2.0rc0', True), ('0.2.0rc1', True), ('0.2.0rc10', True),
    ('0.2.0', False), ('1.0.0', False), ('10.20.30', False),
])
def test_channels_and_matching_tags(tmp_path, version, expected):
    manifest = tmp_path / 'pyproject.toml'
    manifest.write_text(f'[project]\nversion = "{version}"\n\n[other]\nversion = "99.9.9"\n')
    assert metadata.classify(manifest, 'v' + version) is expected
    assert metadata.classify(manifest) is expected


@pytest.mark.parametrize('version', ['0.2.0-rc.1', '0.2.0alpha1', '0.2', 'v0.2.0',
    '01.2.3', '0.2.0RC1', '0.2.0rc01', '0.2.0.dev1', '0.2.0.post1', '0.2.0+local'])
def test_manifest_requires_canonical_supported_version(version):
    with pytest.raises(ValueError):
        metadata.is_prerelease(version)


def test_wrong_tag_fails_before_publication(tmp_path):
    manifest = tmp_path / 'pyproject.toml'
    manifest.write_text('[project]\nversion = "0.2.0rc1"\n')
    for tag in ('v0.2.0', 'v0.2.0-rc.1', 'v0.2.0rc2'):
        with pytest.raises(ValueError, match='must match'):
            metadata.classify(manifest, tag)
