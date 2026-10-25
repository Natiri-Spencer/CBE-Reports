# run_dev.ps1
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot "student_reports_frontend"

Write-Host "Starting React frontend dev server..."
Start-Process -FilePath powershell -WorkingDirectory $frontendPath -ArgumentList "-NoExit", "-Command", "npm start"

Write-Host "Starting FastAPI backend in development mode..."
Set-Location $PSScriptRoot
$env:ENV = "DEV"
python -m uvicorn app.main:app --reload
