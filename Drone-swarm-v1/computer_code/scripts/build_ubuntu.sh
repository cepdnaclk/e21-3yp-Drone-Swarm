#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="$project_dir/venv"
release_dir="$project_dir/release"

cd "$project_dir"
if [[ ! -x "$venv_dir/bin/python" ]]; then
  python3 -m venv "$venv_dir"
fi

"$venv_dir/bin/python" -m pip install --upgrade pip
"$venv_dir/bin/python" -m pip install \
  -r api/requirements.txt \
  -r api/requirements-build.txt
npm ci
npm run build

"$venv_dir/bin/python" -m PyInstaller api/droneswarm.spec \
  --noconfirm \
  --clean \
  --distpath dist_exe \
  --workpath build/pyinstaller

mkdir -p "$release_dir"
chmod +x dist_exe/DroneSwarm
tar -C dist_exe -czf "$release_dir/DroneSwarm-Ubuntu-x64.tar.gz" DroneSwarm
echo "Release created at $release_dir/DroneSwarm-Ubuntu-x64.tar.gz"
