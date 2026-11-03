"""Embedders. OpenAIEmbedder is the real one (NOT RUN offline). HashEmbedder is a deterministic LEXICAL
dev/test adapter (hashing trick) — it is not semantic and is only selectable with VECTOR_BACKEND=memory."""
import hashlib
import math
import re
from typing import TYPE_CHECKING

from app.agents.llm import map_provider_error
from app.core.exceptions import BadRequest, NotConfigured

if TYPE_CHECKING:
    from app.core.config import Settings

_TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z][a-z0-9]*|\d+")


def tokens(text: str) -> list[str]:
    """Lowercased identifier pieces: snake_case and camelCase are split."""
    return [t.lower() for t in _TOKEN.findall(text)]


class HashEmbedder:
    label = "local lexical demo embeddings (hashing trick, not semantic)"

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in tokens(t):
                v[int(hashlib.sha1(tok.encode()).hexdigest()[:8], 16) % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


class OpenAIEmbedder:
    label = "OpenAI embeddings"

    def __init__(self, s: "Settings"):
        from langchain_openai import OpenAIEmbeddings
        self.dim = s.embedding_dimensions
        self._e = OpenAIEmbeddings(model=s.openai_embedding_model, dimensions=s.embedding_dimensions, api_key=s.openai_api_key,
                                   timeout=s.openai_timeout_seconds, max_retries=1)

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return self._e.embed_documents(texts)
        except Exception as exc:  # noqa: BLE001
            raise map_provider_error(exc) from exc


def check_dimensions(vectors: list[list[float]], expected: int) -> None:
    for v in vectors:
        if len(v) != expected:
            raise BadRequest(f"Embedding dimension {len(v)} does not match EMBEDDING_DIMENSIONS={expected} / the Pinecone index dimension. "
                             "Fix the configuration; vectors were not stored.", code="embedding_dimension_mismatch")


def get_embedder(s: "Settings"):
    if s.openai_configured:
        return OpenAIEmbedder(s)
    if s.vector_backend == "memory":
        return HashEmbedder(s.embedding_dimensions)
    raise NotConfigured("OpenAI is not configured. Set OPENAI_API_KEY to enable embeddings for code search.", code="openai_not_configured")
