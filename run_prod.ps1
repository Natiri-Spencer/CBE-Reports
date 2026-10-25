# run_prod.ps1
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot "student_reports_frontend"

Write-Host "Building React frontend..."
Set-Location $frontendPath
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Starting FastAPI backend in production mode..."
Set-Location $PSScriptRoot
$env:ENV = "PROD"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
