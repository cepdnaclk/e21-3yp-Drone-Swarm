$ErrorActionPreference = "Stop"
$env:PYTHONDONTWRITEBYTECODE = "1"

Write-Host "== Python unit/integration/regression tests =="
python -B -m unittest discover -s tests/python -p "test_*.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Drone UI TypeScript/Vite regression build =="
Push-Location "Drone-swarm-v1/computer_code"
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

Write-Host "All tests passed."
