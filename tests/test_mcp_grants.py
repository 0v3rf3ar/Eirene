"""Read grants derived from local MCP launch commands."""
from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

import pytest

from eirene.core import paths
from eirene.core.mcp_config import prepare_local
from eirene.tools import isolation, shell


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A user home holding credentials that no derived grant may reach."""
    root = tmp_path / "user"
    (root / ".ssh").mkdir(parents=True)
    (root / ".ssh" / "id_ed25519").write_text("private key", encoding="utf-8")
    (root / "notes.txt").write_text("personal", encoding="utf-8")
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("USERPROFILE", str(root))
    return root


def package_project(base: Path, *markers: str) -> Path:
    """The shotcut-mcp layout: a launcher script importing its sibling package."""
    project = base / "shotcut-mcp"
    (project / "scripts").mkdir(parents=True)
    (project / "shotcut_mcp").mkdir()
    for marker in markers:
        target = project / marker
        target.mkdir() if marker == ".git" else target.write_text("", encoding="utf-8")
    (project / "shotcut_mcp" / "__init__.py").write_text("VALUE = 'imported'\n", encoding="utf-8")
    (project / "scripts" / "server.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "from shotcut_mcp import VALUE\nprint(VALUE)\n", encoding="utf-8")
    return project


def granted(definition, path: Path) -> bool:
    return str(path.resolve()) in definition["read_paths"]


def prepare(command, **extra):
    return prepare_local("demo", {"command": command, **extra})


def assert_private(definition, home: Path):
    home = home.resolve()
    for item in definition["read_paths"]:
        path = Path(item)
        assert path != home and path not in home.parents, item
        assert path != home / ".ssh" and home / ".ssh" not in path.parents, item


@pytest.fixture
def python(monkeypatch):
    monkeypatch.setattr("eirene.core.mcp_config.shutil.which", lambda name: "/usr/bin/python3")


def test_script_gets_its_project_root(home, python):
    project = package_project(home / "Desktop" / "mcp", "pyproject.toml", ".git")
    definition = prepare(["python3", str(project / "scripts" / "server.py")])
    assert granted(definition, project)
    assert_private(definition, home)


def test_script_without_project_markers_gets_its_own_folder(home, python):
    project = package_project(home / "tools")
    definition = prepare(["python3", str(project / "scripts" / "server.py")])
    assert granted(definition, project / "scripts")
    assert not granted(definition, project)


def test_monorepo_package_gets_the_repository(home, python):
    repo = home / "src" / "monorepo"
    (repo / ".git").mkdir(parents=True)
    package = repo / "packages" / "server"
    package.mkdir(parents=True)
    (package / "package.json").write_text("{}", encoding="utf-8")
    (package / "index.js").write_text("", encoding="utf-8")
    definition = prepare(["node", str(package / "index.js")])
    assert granted(definition, repo)


def test_script_loose_in_home_gets_only_itself(home, python):
    script = home / "server.py"
    script.write_text("", encoding="utf-8")
    definition = prepare(["python3", str(script)])
    assert granted(definition, script)
    assert_private(definition, home)


def test_marker_in_home_never_widens_to_home(home, python):
    (home / ".git").mkdir()
    (home / "pyproject.toml").write_text("", encoding="utf-8")
    project = package_project(home / "work")
    definition = prepare(["python3", str(project / "scripts" / "server.py")])
    assert granted(definition, project / "scripts")
    assert_private(definition, home)


def test_credential_folders_are_never_granted(home, python):
    script = home / ".ssh" / "helper.py"
    script.write_text("", encoding="utf-8")
    definition = prepare(["python3", str(script), "--keys", str(home / ".ssh"), str(home)],
                         env={"PYTHONPATH": str(home / ".ssh")})
    assert_private(definition, home)
    assert not any(str(home / ".ssh") in item for item in definition["read_paths"])
    assert definition["_withheld_read_paths"] == [str(script)]
    # Naming the file in read_paths is the explicit way to share it.
    definition = prepare(["python3", str(script)], read_paths=[str(script)])
    assert str(script) in definition["read_paths"] and "_withheld_read_paths" not in definition


def test_eirene_data_is_never_granted_except_plugin_folders(home, python):
    sessions = paths.sessions_dir()
    (sessions / "trap.py").write_text("", encoding="utf-8")
    definition = prepare(["python3", str(sessions / "trap.py"), str(paths.home())])
    assert not any(Path(item) == paths.home() or paths.home() in Path(item).parents
                   for item in definition["read_paths"])
    plugin = package_project(paths.plugins_dir() / "shotcut", "pyproject.toml")
    definition = prepare(["python3", str(plugin / "scripts" / "server.py")])
    assert granted(definition, plugin)


def test_directory_and_module_path_arguments_are_granted(home, python):
    project = package_project(home / "code", "pyproject.toml")
    library = home / "lib" / "python"
    library.mkdir(parents=True)
    definition = prepare(["uv", "run", f"--directory={project}", "server"],
                         env={"PYTHONPATH": str(library)})
    assert granted(definition, project)
    assert granted(definition, library)


def test_relative_script_resolves_against_the_workspace(home, python, tmp_path):
    outside = package_project(tmp_path / "elsewhere", "pyproject.toml")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    definition = prepare_local("demo", {"command": ["python3", "../elsewhere/shotcut-mcp/scripts/server.py"]},
                               workspace)
    assert granted(definition, outside)


def test_linked_script_launches_from_its_real_location(home, python):
    project = package_project(home / "real", "pyproject.toml")
    links = home / "bin"
    links.mkdir()
    try:
        (links / "server.py").symlink_to(project / "scripts" / "server.py")
    except OSError:
        pytest.skip("creating symlinks needs Developer Mode or admin rights on Windows")
    definition = prepare(["python3", str(links / "server.py")])
    assert definition["command"][-1] == str((project / "scripts" / "server.py").resolve())
    assert granted(definition, project)


def test_derived_grants_are_recomputed_and_explicit_ones_kept(home, python):
    project = package_project(home / "a", "pyproject.toml")
    extra = home / "data"
    extra.mkdir()
    first = prepare(["python3", str(project / "scripts" / "server.py")], read_paths=[str(extra)])
    second = prepare_local("demo", first)
    assert second["read_paths"] == first["read_paths"]
    moved = package_project(home / "b", "pyproject.toml")
    third = prepare_local("demo", {**first, "command": ["python3", str(moved / "scripts" / "server.py")]})
    assert granted(third, moved) and not granted(third, project)
    assert str(extra) in third["read_paths"]


def test_older_saved_grants_lose_anything_unsafe(home, python):
    project = package_project(home / "Desktop" / "mcp", "pyproject.toml", ".git")
    script = project / "scripts" / "server.py"
    saved = {"command": ["/usr/bin/python3", str(script)], "_runtime_home": "old",
             "read_paths": [str(script), str(home), "/"]}
    definition = prepare_local("demo", saved)
    assert granted(definition, project)
    assert str(home) not in definition["read_paths"] and "/" not in definition["read_paths"]


def test_case_changes_do_not_reach_credential_stores(home, python):
    # macOS and Windows volumes usually ignore case: ~/.SSH is ~/.ssh there.
    (home / "Library" / "Keychains").mkdir(parents=True)
    for folder in (home / ".SSH-not", home / "LIBRARY" / "keychains" / "tool"):
        folder.mkdir(parents=True, exist_ok=True)
    from eirene.core.mcp_config import _safe_grant
    assert not _safe_grant(home / ".SSH")
    assert not _safe_grant(home / "LIBRARY" / "keychains" / "tool")
    assert not _safe_grant(home.parent / home.name.upper())
    assert _safe_grant(home / ".SSH-not")


@pytest.mark.parametrize("folder", ["/", "/home", "/Users", "/Volumes", "/opt", "/tmp", "/private"])
def test_shared_top_level_folders_are_refused(folder):
    from eirene.core.mcp_config import _safe_grant
    assert not _safe_grant(Path(folder).resolve() if sys.platform != "win32" else Path("C:" + folder))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive and profile layout")
def test_windows_drive_and_profile_folders(home):
    from eirene.core.mcp_config import _safe_grant
    for folder in ("C:\\", "C:\\Users", "C:\\Windows", "C:\\Program Files", "C:\\ProgramData", "D:\\"):
        assert not _safe_grant(Path(folder)), folder
    assert not _safe_grant(home / "AppData" / "Roaming" / "Microsoft" / "Credentials")
    assert _safe_grant(Path("C:\\dev\\tool"))


def test_read_grant_inside_writable_mount_is_not_rebound(workdir, monkeypatch):
    monkeypatch.setattr(isolation.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(isolation.sys, "platform", "linux")
    inner = workdir / "pkg"
    inner.mkdir()
    argv = isolation.command("true", workdir, backend="bubblewrap", read_paths=[inner])
    assert str(inner.resolve()) not in argv


def test_seatbelt_profile_carries_the_project_grant(home, python, workdir, monkeypatch):
    project = package_project(home / "Desktop" / "mcp", "pyproject.toml", ".git")
    definition = prepare(["python3", str(project / "scripts" / "server.py")])
    monkeypatch.setattr(isolation.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    monkeypatch.setattr(isolation.sys, "platform", "darwin")
    argv = isolation.command("true", workdir, backend="seatbelt", read_paths=definition["read_paths"])
    profile = argv[2]
    assert f'(allow file-read* (subpath "{project.resolve()}"))' in profile
    assert str(home.resolve()) + '"' not in profile and ".ssh" not in profile


SANDBOXES = [
    pytest.param("bubblewrap", marks=pytest.mark.skipif(
        sys.platform != "linux" or not shutil.which("bwrap"), reason="Linux Bubblewrap integration")),
    pytest.param("seatbelt", marks=pytest.mark.skipif(
        sys.platform != "darwin" or not shutil.which("sandbox-exec"), reason="macOS Seatbelt integration")),
]


@pytest.mark.skipif(not shutil.which("python3"), reason="needs python3")
@pytest.mark.parametrize("backend", SANDBOXES)
async def test_sandboxed_script_imports_its_package_but_not_home(backend, home, workdir):
    project = package_project(home / "Desktop" / "mcp", "pyproject.toml", ".git")
    definition = prepare_local("shotcut", {"command": ["python3", str(project / "scripts" / "server.py")]},
                               workdir)
    result = await shell.run(shlex.join(definition["command"]), workdir, isolation=backend,
                             isolate_network=True, read_paths=definition["read_paths"])
    assert result.ok and "imported" in result.output, result.output
    for secret in (home / ".ssh" / "id_ed25519", home / "notes.txt"):
        result = await shell.run(f"cat {shlex.quote(str(secret))}", workdir, isolation=backend,
                                 isolate_network=True, read_paths=definition["read_paths"])
        assert not result.ok, result.output


def test_interpreter_outside_usr_gets_its_library_folder(home, tmp_path, monkeypatch):
    """setup-python, pyenv and uv keep libpython and the stdlib in lib/ beside bin/."""
    prefix = tmp_path / "toolcache" / "Python" / "3.14.9" / "x64"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib" / "python3.14").mkdir(parents=True)
    (prefix / "include").mkdir()
    interpreter = prefix / "bin" / "python3"
    interpreter.write_text("", encoding="utf-8")
    monkeypatch.setattr("eirene.core.mcp_config.shutil.which", lambda name: str(interpreter))
    project = package_project(home / "Desktop" / "mcp", "pyproject.toml")
    definition = prepare_local("tool", {"command": ["python3", str(project / "scripts" / "server.py")]})
    reads = set(definition["read_paths"])
    assert str(prefix / "lib") in reads and str(prefix / "bin") in reads
    assert str(prefix) not in reads and str(prefix / "include") not in reads
    assert not any(str(home) == item for item in reads)
