import os
import psycopg2
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from typing import List

from database import engine, get_db
import models
import schemas

class Config:
    DATABASE_URL = os.getenv("DATABASE_URL")
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = FastAPI(title="Sceptic Backend - Phase 2")

@app.get("/health")
def health_check():
    db_status = "not configured"
    
    if Config.DATABASE_URL:
        try:
            # Attempt a quick connection to verify credentials
            conn = psycopg2.connect(Config.DATABASE_URL, connect_timeout=3)
            conn.close()
            db_status = "connected successfully"
        except Exception as e:
            db_status = f"connection failed: {str(e)}"

    return {
        "status": "ok",
        "database_status": db_status,
        "redis_configured": bool(Config.REDIS_URL),
        "message": "Backend is reachable"
    }

@app.get("/audits", response_model=List[schemas.AuditRunResponse])
def get_audits(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    audits = db.query(models.AuditRun).offset(skip).limit(limit).all()
    return audits

@app.post("/webhook")
def webhook_stub():
    return {
        "status": "received",
        "message": "Webhook processing not yet implemented in Phase 2"
    }
