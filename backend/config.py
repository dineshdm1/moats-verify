"""Configuration management for Moats Verify."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    # Paths
    DATA_DIR: str = os.getenv("DATA_DIR", str(Path(__file__).parent.parent / "data"))
    SQLITE_PATH: str = os.getenv("SQLITE_PATH", "")
    CHROMADB_PATH: str = os.getenv("CHROMADB_PATH", "")

    # Neo4j
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")

    # LLM defaults
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openrouter")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "xiaomi/mimo-v2-flash")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")

    # Embedding defaults
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "openrouter")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")

    # Local LLM
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Server
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    def __init__(self):
        data = Path(self.DATA_DIR)
        data.mkdir(parents=True, exist_ok=True)
        if not self.SQLITE_PATH:
            self.SQLITE_PATH = str(data / "metadata.db")
        if not self.CHROMADB_PATH:
            self.CHROMADB_PATH = str(data / "chromadb")


settings = Settings()
