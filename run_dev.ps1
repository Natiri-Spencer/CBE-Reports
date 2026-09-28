# run_dev.ps1
Write-Host "Starting React frontend dev server..."
Start-Process powershell -ArgumentList "cd ../student_reports_frontend; npm start"

Write-Host "Starting FastAPI backend in development mode..."
cd ../student_reports_backend
$env:ENV="DEV"
uvicorn app.main:app --reload
