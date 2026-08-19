# PyInstaller spec, one file per platform.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent

datas, binaries, hiddenimports = collect_all("textual")
extra_datas, extra_binaries, extra_hidden = collect_all("rich")
datas += extra_datas
binaries += extra_binaries
hiddenimports += extra_hidden

datas += [(str(ROOT / "pyproject.toml"), ".")]
datas += [(str(ROOT / "img" / "Eirene.png"), "img")]
datas += [(str(ROOT / "skills"), "skills")]

hiddenimports += [
    "eirene.commands.agents",
    "eirene.commands.btw",
    "eirene.commands.clear",
    "eirene.commands.compact",
    "eirene.commands.connect",
    "eirene.commands.exit",
    "eirene.commands.help",
    "eirene.commands.model",
    "eirene.commands.notification",
    "eirene.commands.processes",
    "eirene.commands.review",
    "eirene.commands.schedule",
    "eirene.commands.skills",
    "eirene.commands.tasks",
    "eirene.commands.usage",
    "eirene.commands.theme",
    "eirene.scheduling.linux_systemd",
    "eirene.scheduling.macos_launchd",
    "eirene.scheduling.windows_schtasks",
    "eirene.providers.anthropic_compat",
    "eirene.providers.gemini",
    "eirene.providers.ollama",
    "eirene.providers.openai_compat",
    "eirene.providers.claude_code",
    "eirene.providers.codex_subscription",
]

excludes = ["tkinter", "unittest", "pydoc_data", "test", "distutils",
            "setuptools", "pip", "PIL", "numpy", "pytest"]

analysis = Analysis(
    [str(ROOT / "build" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
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
