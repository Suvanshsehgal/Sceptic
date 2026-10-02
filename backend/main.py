import os
import psycopg2
from fastapi import FastAPI
from pydantic import BaseModel

class Config:
    DATABASE_URL = os.getenv("DATABASE_URL")
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = FastAPI(title="Sceptic Backend - Phase 1")

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

@app.post("/webhook")
def webhook_stub():
    return {
        "status": "received",
        "message": "Webhook processing not yet implemented in Phase 1"
    }
