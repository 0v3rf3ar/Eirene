# PyInstaller spec, one file per platform.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent

datas, binaries, hiddenimports = collect_all("textual")
extra_datas, extra_binaries, extra_hidden = collect_all("rich")
datas += extra_datas
binaries += extra_binaries
hiddenimports += extra_hidden

image_datas, image_binaries, image_hidden = collect_all("textual_image")
datas += image_datas
binaries += image_binaries
hiddenimports += image_hidden

datas += [(str(ROOT / "pyproject.toml"), ".")]
datas += [(str(ROOT / "img" / "Eirene.png"), "img")]
datas += [(str(ROOT / "eirene" / "ui" / "logo.gray.zlib"), "eirene/ui")]
datas += [(str(ROOT / "eirene" / "ui" / "companion_assets"), "eirene/ui/companion_assets")]
_bundle = ROOT / "eirene" / "plugins"
datas += [(str(path), str(path.parent.relative_to(ROOT)).replace("\\", "/"))
          for path in sorted(_bundle.rglob("*"))
          if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"]

hiddenimports += [
    "eirene.commands.agents",
    "eirene.commands.btw",
    "eirene.commands.clear",
    "eirene.commands.compact",
    "eirene.commands.connect",
    "eirene.commands.exit",
    "eirene.commands.help",
    "eirene.commands.keybindings",
    "eirene.commands.mcp",
    "eirene.commands.model",
    "eirene.commands.notification",
    "eirene.commands.review",
    "eirene.commands.schedule",
    "eirene.commands.skills",
    "eirene.commands.routines",
    "eirene.commands.routine_options",
    "eirene.commands.usage",
    "eirene.commands.theme",
    "eirene.scheduling.linux_systemd",
    "eirene.scheduling.macos_launchd",
    "eirene.scheduling.windows_schtasks",
    "eirene.scheduling.worktree",
    "eirene.scheduling.windows_rights",
    "eirene.providers.anthropic_compat",
    "eirene.providers.gemini",
    "eirene.providers.ollama",
    "eirene.providers.openai_compat",
    "eirene.providers.claude_code",
    "eirene.providers.codex_subscription",
]

hiddenimports += collect_submodules("eirene.commands")
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("mcp.client")
hiddenimports += collect_submodules("mcp.shared")

# Python 3.12+ gets distutils from setuptools. PyInstaller aliases those modules
# while analyzing Windows dependencies, so neither package can be excluded.
excludes = ["tkinter", "unittest", "pydoc_data", "test",
            "pip", "numpy", "pytest",
            # Dev tools present in the build venv; nothing at runtime imports them.
            "mypy", "mypyc", "ast_serialize",
            # Pillow only decodes PNG, JPEG, GIF and WebP pictures here. AVIF,
            # fonts, color management and GUI toolkits each ship large libraries.
            "PIL._avif", "PIL.AvifImagePlugin", "PIL._imagingft", "PIL.ImageFont",
            "PIL._imagingcms", "PIL.ImageCms", "PIL._imagingtk", "PIL.ImageTk",
            "PIL._imagingmath", "PIL.ImageMath", "PIL._imagingmorph", "PIL.ImageMorph",
            "PIL.ImageQt", "PIL.ImageShow", "PIL.ImageGrab"]
if sys.platform != "win32":
    # The distutils alias problem above only exists in Windows analysis.
    excludes += ["setuptools", "distutils", "_distutils_hack", "pkg_resources"]

analysis = Analysis(
    [str(ROOT / "build" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[str(ROOT / "build" / "runtime_hook.py")],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="eirene",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "img" / "Eirene.png") if sys.platform == "win32" else None,
)
