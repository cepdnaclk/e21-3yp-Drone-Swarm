"""PyInstaller one-file build for the local Drone Swarm application."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


API_DIR = Path(SPECPATH).resolve()
PROJECT_DIR = API_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "dist"
ICON_PATH = PROJECT_DIR / "logo.ico"

if not (FRONTEND_DIR / "index.html").is_file():
    raise SystemExit(
        "Frontend build not found. Run `npm run build` in computer_code first."
    )

cv2_datas, cv2_binaries, cv2_hiddenimports = collect_all("cv2")

datas = [
    (str(FRONTEND_DIR), "dist"),
    (str(API_DIR / "current_calibration"), "current_calibration"),
    (str(API_DIR / "fleet.json"), "."),
    (str(API_DIR / "settings.json"), "."),
] + cv2_datas

hiddenimports = sorted(set(
    ["importlib.resources"]
    + cv2_hiddenimports
    # scipy.stats._sobol imports importlib.resources dynamically from a
    # compiled extension, so PyInstaller cannot discover it by AST analysis.
    + collect_submodules("importlib.resources")
    + collect_submodules("engineio.async_drivers")
    + collect_submodules("serial.tools")
))

a = Analysis(
    [str(API_DIR / "index.py")],
    pathex=[str(API_DIR)],
    binaries=cv2_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DroneSwarm",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
)
