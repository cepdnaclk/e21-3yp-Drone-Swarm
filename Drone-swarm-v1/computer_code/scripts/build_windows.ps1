$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectDir "venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$ReleaseDir = Join-Path $ProjectDir "release"
$BundleDir = Join-Path $ProjectDir "build\windows-release"
$ReleaseArchive = Join-Path $ReleaseDir "DroneSwarm-Windows-x64.zip"

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
    New-Item -ItemType Directory -Force -Path $BundleDir | Out-Null
    Copy-Item -Force `
        -LiteralPath (Join-Path $ProjectDir "dist_exe\DroneSwarm.exe") `
        -Destination (Join-Path $BundleDir "DroneSwarm.exe")
    Copy-Item -Force `
        -LiteralPath (Join-Path $ProjectDir "..\sender_esp32\sender_esp32.ino") `
        -Destination (Join-Path $BundleDir "sender_esp32.ino")
    Copy-Item -Force `
        -LiteralPath (Join-Path $ProjectDir "..\receiver_esp32\receiver_drone1\receiver_drone1.ino") `
        -Destination (Join-Path $BundleDir "receiver_drone1.ino")
    Compress-Archive -Force -Path (Join-Path $BundleDir "*") -DestinationPath $ReleaseArchive

    Write-Host "Release created at $ReleaseArchive"
}
finally {
    Pop-Location
}
