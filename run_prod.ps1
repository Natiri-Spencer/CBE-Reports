# run_prod.ps1
Write-Host "Building React frontend..."
cd "C:\Users\Administrator\Desktop\Grade Tool\student_reports_frontend"
npm run build

Write-Host "Starting FastAPI backend in production mode..."
cd "C:\Users\Administrator\Desktop\Grade Tool\student_reports_backend"
$env:ENV="PROD"
python -m uvicorn app.main:app --reload
