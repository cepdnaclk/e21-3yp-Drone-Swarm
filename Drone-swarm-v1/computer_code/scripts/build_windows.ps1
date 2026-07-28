$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectDir "venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$ReleaseDir = Join-Path $ProjectDir "release"

Push-Location $ProjectDir
try {
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        python -m venv $VenvDir
    }

    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -r "api\requirements.txt" -r "api\requirements-build.txt"
    npm.cmd ci
    npm.cmd run build

    & $PythonExe -m PyInstaller "api\droneswarm.spec" `
        --noconfirm `
        --clean `
        --distpath "dist_exe" `
        --workpath "build\pyinstaller"

    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
    Copy-Item -Force `
        -LiteralPath (Join-Path $ProjectDir "dist_exe\DroneSwarm.exe") `
        -Destination (Join-Path $ReleaseDir "DroneSwarm-Windows-x64.exe")

    Write-Host "Release created at $ReleaseDir\DroneSwarm-Windows-x64.exe"
}
finally {
    Pop-Location
}
