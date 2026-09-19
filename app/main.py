from fastapi import FastAPI
from app.routes import reports

app = FastAPI(title="Student Reports API", version="1.0")

# Root endpoint
@app.get("/")
def read_root():
    return {"message": "FastAPI is running!"}

# Include reports routes
app.include_router(reports.router, prefix="/reports", tags=["Reports"])
