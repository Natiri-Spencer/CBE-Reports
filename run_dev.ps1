# run_dev.ps1
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot "student_reports_frontend"

Write-Host "Starting React frontend dev server..."
Start-Process -FilePath powershell -WindowStyle Hidden -WorkingDirectory $frontendPath -ArgumentList "-NoExit", "-Command", "npm start"

Write-Host "Starting FastAPI backend in development mode..."
Set-Location $PSScriptRoot
$env:ENV = "DEV"
$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = "python" }
$uvicornArguments = @("-m", "uvicorn", "app.main:app", "--no-access-log", "--no-proxy-headers", "--reload")
if (Test-Path -LiteralPath ".env") { $uvicornArguments += @("--env-file", ".env") }
& $pythonPath @uvicornArguments
