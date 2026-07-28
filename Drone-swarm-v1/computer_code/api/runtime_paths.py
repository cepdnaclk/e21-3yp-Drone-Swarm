"""Resolve bundled resources and writable Drone Swarm runtime directories.

PyInstaller extracts bundled files into a temporary, read-only-in-practice
directory.  User-modified state therefore lives outside the executable:

* Windows: ``%APPDATA%/DroneSwarm``
* Linux: ``$XDG_CONFIG_HOME/DroneSwarm`` or ``~/.config/DroneSwarm``

Set ``DRONE_SWARM_DATA_DIR`` to override the location (useful for development
and automated tests).
"""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys


APP_NAME = "DroneSwarm"
SOURCE_API_DIR = Path(__file__).resolve().parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_DIR = (
    Path(getattr(sys, "_MEIPASS")).resolve()
    if IS_FROZEN
    else SOURCE_API_DIR
)


def _default_user_data_dir() -> Path:
    override = os.environ.get("DRONE_SWARM_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        root = Path(xdg_config).expanduser() if xdg_config else Path.home() / ".config"
    return root / APP_NAME


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    frontend_dist_dir: Path
    fleet_file: Path
    settings_file: Path
    uploads_dir: Path
    logs_dir: Path
    calibration_dir: Path


def _copy_missing_tree(source: Path, destination: Path) -> None:
    """Seed missing defaults without overwriting user-calibrated files."""
    if not source.is_dir():
        return
    for source_path in source.rglob("*"):
        relative = source_path.relative_to(source)
        destination_path = destination / relative
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
        elif not destination_path.exists():
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)


def ensure_runtime_data() -> RuntimePaths:
    """Create writable runtime folders and seed first-run default files."""
    data_dir = _default_user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    uploads_dir = data_dir / "uploads"
    logs_dir = data_dir / "logs"
    calibration_dir = data_dir / "current_calibration"
    for directory in (uploads_dir, logs_dir, calibration_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for filename in ("fleet.json", "settings.json"):
        source = BUNDLE_DIR / filename
        destination = data_dir / filename
        if source.is_file() and not destination.exists():
            shutil.copy2(source, destination)

    _copy_missing_tree(BUNDLE_DIR / "current_calibration", calibration_dir)

    frontend_dist_dir = (
        BUNDLE_DIR / "dist"
        if IS_FROZEN
        else SOURCE_API_DIR.parent / "dist"
    )
    return RuntimePaths(
        data_dir=data_dir,
        frontend_dist_dir=frontend_dist_dir,
        fleet_file=data_dir / "fleet.json",
        settings_file=data_dir / "settings.json",
        uploads_dir=uploads_dir,
        logs_dir=logs_dir,
        calibration_dir=calibration_dir,
    )
