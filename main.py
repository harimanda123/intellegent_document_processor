"""
IDP — Intelligent Document Gateway
Root entry point. Launches the FastAPI application via uvicorn.

Usage:
    python main.py
    # or
    uvicorn app.main:app --reload
"""
import uvicorn
from app.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
        log_level="info",
    )
