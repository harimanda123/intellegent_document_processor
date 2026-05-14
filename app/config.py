from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # ── LLM Configuration (runtime configurable) ──────────────────────
    # Provider: openai | anthropic | groq | ollama | openai_compatible
    llm_provider: str = "groq"
    llm_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    # Base URL — override for Ollama or any OpenAI-compatible provider
    # Leave empty to use provider default
    llm_base_url: str = ""

    # ── Database ───────────────────────────────────────────────────────
    # SQLite by default — change to postgresql://user:pass@host/db
    database_url: str = "sqlite:///./idp.db"

    # ── App ────────────────────────────────────────────────────────────
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 50

    # ── Review ─────────────────────────────────────────────────────────
    # Confidence threshold for require_review="auto" mode.
    # Documents with avg_confidence below this are routed to PENDING_REVIEW.
    auto_review_threshold: float = 0.80

    # ── CORS ───────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173"

    class Config:
        env_file = ".env"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


settings = Settings()