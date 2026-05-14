"""
IDP — Intelligent Document Processing
FastAPI application entry point.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import schemas, documents, erp, dashboard


# ── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once at startup before accepting requests.
    Creates all database tables if they don't exist.
    """
    print(f"Starting IDP...")
    print(f"LLM Provider : {settings.llm_provider}")
    print(f"LLM Model    : {settings.llm_model}")
    print(f"Database     : {settings.database_url}")
    print(f"Upload dir   : {settings.upload_dir}")
    init_db()
    print("Database tables ready.")
    print("IDP is running.")
    yield
    print("IDP shutting down.")


# ── App ────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Intelligent Document Processing (IDP)",
    description=(
        "AI-powered document extraction platform. "
        "Upload PDFs, extract structured JSON, "
        "download or deliver to ERP systems."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ── CORS ───────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ────────────────────────────────────────────────────────────────

app.include_router(schemas.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(erp.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")


# ── Health endpoints ───────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {
        "app": "Intelligent Document Processing",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
    }


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}