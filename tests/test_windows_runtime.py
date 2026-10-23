"""Portable validation of Windows grant and environment boundaries."""
import pytest

from eirene.core.errors import ToolError
from eirene.tools import windows_runtime as runtime
from eirene.tools.windows_appcontainer import _environment


def test_grants_reject_reparse_points_before_acl_updates(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "workspace"
    root.mkdir()
    try:
        (root / "escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks is unavailable on this host")
    with pytest.raises(ToolError, match="reparse points"):
        runtime._check_tree(root)


def test_private_environment_paths_cannot_be_overridden(tmp_path):
    home = tmp_path / "private"
    block = _environment(str(tmp_path), home, str(tmp_path / "local"), {
        "home": "outside", "TEMP": "outside", "Path": "explicit-tool-path",
        "LANG": "en_US.UTF-8",
    })
    values = dict(entry.split("=", 1) for entry in block.rstrip("\0").split("\0"))
    assert values["HOME"] == str(home) and values["TEMP"] == str(home)
    assert values["Path"] == "explicit-tool-path" and "PATH" not in values


@pytest.mark.parametrize("extra", [{"X": "bad\0value"}, {"BAD=KEY": "value"}, {"": "value"}])
def test_environment_rejects_invalid_entries(tmp_path, extra):
    with pytest.raises(ToolError):
        _environment(str(tmp_path), tmp_path, str(tmp_path), extra)
