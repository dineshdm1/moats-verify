"""Configuration settings for Moats Library."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from functools import lru_cache


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    # OpenRouter API
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))

    # Model configuration
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "qwen/qwen3-embedding-8b"))
    chat_model: str = field(default_factory=lambda: os.getenv("CHAT_MODEL", "xiaomi/mimo-v2-flash"))

    # Tavily for web search
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))

    # Agent settings
    agent_name: str = field(default_factory=lambda: os.getenv("AGENT_NAME", "Emma"))
    agent_password: str = field(default_factory=lambda: os.getenv("AGENT_PASSWORD", "argo-30"))

    # OpenRouter app identification (for priority routing)
    app_name: str = field(default_factory=lambda: os.getenv("APP_NAME", "Moats Intelligence"))
    app_url: str = field(default_factory=lambda: os.getenv("APP_URL", "https://github.com/moats-intelligence"))

    # Neo4j connection
    neo4j_uri: str = field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://neo4j:7687"))
    neo4j_user: str = field(default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"))
    neo4j_password: str = field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", "moats_library"))

    # Storage paths
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "/data")))

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def chromadb_path(self) -> Path:
        return self.data_dir / "chromadb"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    def validate(self) -> list[str]:
        """Validate required settings. Returns list of missing keys."""
        missing = []
        if not self.openrouter_api_key:
            missing.append("OPENROUTER_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
