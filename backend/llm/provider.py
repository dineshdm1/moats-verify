"""LLM provider abstraction — supports OpenRouter, Ollama, and custom endpoints."""

import httpx
import json
import logging
from typing import AsyncIterator
from dataclasses import dataclass

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    provider: str = "openrouter"  # openrouter, ollama, openai, anthropic, custom
    api_key: str = ""
    base_url: str = ""
    chat_model: str = ""
    embedding_model: str = ""

    @classmethod
    def from_settings(cls) -> "LLMConfig":
        return cls(
            provider=settings.LLM_PROVIDER,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            chat_model=settings.LLM_MODEL,
            embedding_model=settings.EMBEDDING_MODEL,
        )

    @classmethod
    def from_dict(cls, d: dict) -> "LLMConfig":
        return cls(
            provider=d.get("provider", "openrouter"),
            api_key=d.get("api_key", ""),
            base_url=d.get("base_url", ""),
            chat_model=d.get("chat_model", ""),
            embedding_model=d.get("embedding_model", ""),
        )


class LLMProvider:
    """Unified LLM interface for chat and embeddings."""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_settings()
        self._resolve_defaults()

    def _resolve_defaults(self):
        c = self.config
        if c.provider == "openrouter":
            c.base_url = c.base_url or "https://openrouter.ai/api/v1"
            c.chat_model = c.chat_model or "xiaomi/mimo-v2-flash"
            c.embedding_model = c.embedding_model or "qwen/qwen3-embedding-8b"
            c.api_key = c.api_key or settings.LLM_API_KEY
        elif c.provider == "ollama":
            c.base_url = c.base_url or settings.OLLAMA_BASE_URL
            c.chat_model = c.chat_model or "llama3.2:latest"
            c.embedding_model = c.embedding_model or "nomic-embed-text"
        elif c.provider == "openai":
            c.base_url = c.base_url or "https://api.openai.com/v1"
        elif c.provider == "anthropic":
            c.base_url = c.base_url or "https://api.anthropic.com/v1"
        elif c.provider == "custom":
            pass  # User provides everything

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.provider == "openrouter":
            headers["HTTP-Referer"] = "https://moats-verify.local"
            headers["X-Title"] = "Moats Verify"
        return headers

    async def chat(self, messages: list[dict], temperature: float = 0.1,
                   max_tokens: int = 4096, json_mode: bool = False) -> str:
        """Send chat completion request, return full response."""
        body = {
            "model": self.config.chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        url = f"{self.config.base_url}/chat/completions"
        if self.config.provider == "ollama":
            url = f"{self.config.base_url}/v1/chat/completions"

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=self._headers(), json=body)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def chat_stream(self, messages: list[dict], temperature: float = 0.1,
                          max_tokens: int = 4096) -> AsyncIterator[str]:
        """Stream chat completion."""
        body = {
            "model": self.config.chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        url = f"{self.config.base_url}/chat/completions"
        if self.config.provider == "ollama":
            url = f"{self.config.base_url}/v1/chat/completions"

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, headers=self._headers(), json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for a list of texts."""
        if not texts:
            return []

        url = f"{self.config.base_url}/embeddings"
        if self.config.provider == "ollama":
            url = f"{self.config.base_url}/v1/embeddings"

        # Batch in groups of 100
        all_embeddings = []
        for i in range(0, len(texts), 100):
            batch = texts[i:i + 100]
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    url,
                    headers=self._headers(),
                    json={"model": self.config.embedding_model, "input": batch},
                )
                response.raise_for_status()
                data = response.json()
                batch_embeddings = [item["embedding"] for item in data["data"]]
                all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def embed_single(self, text: str) -> list[float]:
        """Get embedding for a single text."""
        result = await self.embed([text])
        return result[0]

    async def test_connection(self) -> dict:
        """Test LLM connection. Returns status dict."""
        try:
            response = await self.chat(
                [{"role": "user", "content": "Say 'ok'"}],
                max_tokens=5, temperature=0,
            )
            return {"status": "ok", "response": response.strip()}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def test_embeddings(self) -> dict:
        """Test embedding connection."""
        try:
            result = await self.embed(["test"])
            return {"status": "ok", "dimensions": len(result[0])}
        except Exception as e:
            return {"status": "error", "error": str(e)}
