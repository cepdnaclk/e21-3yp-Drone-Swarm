# PyInstaller build spec for the Drone Swarm local desktop backend.
#
# Build (run from computer_code/, after `npm run build` has produced dist/):
#     pyinstaller api/droneswarm.spec --noconfirm
#
# Produces a single self-contained executable in dist/DroneSwarm(.exe) that
# bundles the Python runtime, the backend, the built React frontend, and the
# calibration files. The user needs neither Python nor Node installed.
#
# Build the executable separately on each target OS: PyInstaller does not
# cross-compile (build Windows .exe on Windows, Linux binary on Linux).

import os

# SPECPATH is injected by PyInstaller and points at the folder holding this
# spec file (computer_code/api).
api_dir = SPECPATH
computer_code_dir = os.path.dirname(api_dir)

dist_frontend = os.path.join(computer_code_dir, "dist")   # `npm run build` output
calibration_dir = os.path.join(api_dir, "calibration")
fleet_json = os.path.join(api_dir, "fleet.json")

datas = [
    (dist_frontend, "dist"),          # Flask serves this as the SPA
    (calibration_dir, "calibration"), # tracker.py loads intrinsics/extrinsics
    (fleet_json, "."),                # seed copied to the user data dir on first run
]

# flask-socketio in threading async_mode pulls in this driver dynamically, so
# PyInstaller's static analysis misses it without an explicit hidden import.
hiddenimports = [
    "engineio.async_drivers.threading",
]

block_cipher = None

a = Analysis(
    [os.path.join(api_dir, "index.py")],
    pathex=[api_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DroneSwarm",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # keep the log/URL console visible for this local server app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
