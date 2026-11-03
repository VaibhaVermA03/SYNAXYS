"""Vector stores: Pinecone (real) and an explicit process-local memory adapter (dev/tests only).
Every operation takes a namespace; callers derive it from the repository (index_policy.namespace_for)."""
import math
from typing import TYPE_CHECKING

from app.core.exceptions import NotConfigured, RateLimited, UpstreamError

if TYPE_CHECKING:
    from app.core.config import Settings


def map_vector_error(exc: Exception) -> Exception:
    status = getattr(exc, "status", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429:
        return RateLimited("Pinecone rate limit reached", code="pinecone_rate_limited")
    if status in (401, 403):
        return NotConfigured("Pinecone rejected the API key or permissions", code="pinecone_auth_failed")
    return UpstreamError("Pinecone is temporarily unavailable", code="pinecone_unavailable")


def is_namespace_missing(exc: Exception) -> bool:
    return getattr(exc, "status", None) == 404


def _cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)) or 1.0, math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _matches(meta: dict, flt: dict | None) -> bool:
    return all(meta.get(k) == v for k, v in (flt or {}).items())


class InMemoryStore:
    backend = "memory"
    label = "in-memory demo store (process-local, not persisted, NOT Pinecone)"

    def __init__(self):
        self.data: dict[str, dict[str, dict]] = {}

    def check(self) -> None: ...

    def upsert(self, namespace: str, vectors: list[dict]) -> None:
        ns = self.data.setdefault(namespace, {})
        for v in vectors:
            ns[v["id"]] = {"values": list(v["values"]), "metadata": dict(v["metadata"])}

    def query(self, namespace: str, vector: list[float], top_k: int, flt: dict | None = None) -> list[dict]:
        rows = [{"id": i, "score": _cos(vector, r["values"]), "metadata": r["metadata"]} for i, r in self.data.get(namespace, {}).items() if _matches(r["metadata"], flt)]
        return sorted(rows, key=lambda r: (-r["score"], r["id"]))[:top_k]

    def list_ids(self, namespace: str, prefix: str) -> list[str]:
        return sorted(i for i in self.data.get(namespace, {}) if i.startswith(prefix))

    def delete_ids(self, namespace: str, ids: list[str]) -> None:
        for i in ids:
            self.data.get(namespace, {}).pop(i, None)

    def delete_namespace(self, namespace: str) -> None:
        self.data.pop(namespace, None)


class PineconeStore:
    backend = "pinecone"
    label = "Pinecone"

    def __init__(self, s: "Settings"):
        from pinecone import Pinecone
        self._pc = Pinecone(api_key=s.pinecone_api_key)
        self._name, self._dim = s.pinecone_index_name, s.embedding_dimensions
        self._index = self._pc.Index(s.pinecone_index_name)

    def _wrap(self, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            raise map_vector_error(exc) from exc

    def check(self) -> None:
        desc = self._wrap(lambda: self._pc.describe_index(self._name))
        dim = getattr(desc, "dimension", None) or (desc.get("dimension") if isinstance(desc, dict) else None)
        if dim is not None and int(dim) != self._dim:
            raise NotConfigured(f"Pinecone index '{self._name}' has dimension {dim} but EMBEDDING_DIMENSIONS={self._dim}.", code="pinecone_dimension_mismatch")

    def upsert(self, namespace: str, vectors: list[dict]) -> None:
        for i in range(0, len(vectors), 100):
            self._wrap(lambda b=vectors[i:i + 100]: self._index.upsert(vectors=b, namespace=namespace))

    def query(self, namespace: str, vector: list[float], top_k: int, flt: dict | None = None) -> list[dict]:
        res = self._wrap(lambda: self._index.query(vector=vector, top_k=top_k, filter=flt or None, include_metadata=True, namespace=namespace))
        return [{"id": m["id"], "score": m["score"], "metadata": dict(m.get("metadata") or {})} for m in (res.get("matches") if isinstance(res, dict) else res.matches)]

    def list_ids(self, namespace: str, prefix: str) -> list[str]:
        def go():
            ids: list[str] = []
            for page in self._index.list(prefix=prefix, namespace=namespace):
                ids.extend(page)
            return ids
        try:
            return go()
        except Exception as exc:  # noqa: BLE001
            if is_namespace_missing(exc):
                return []
            raise map_vector_error(exc) from exc

    def delete_ids(self, namespace: str, ids: list[str]) -> None:
        for i in range(0, len(ids), 1000):
            self._wrap(lambda b=ids[i:i + 1000]: self._index.delete(ids=b, namespace=namespace))

    def delete_namespace(self, namespace: str) -> None:
        try:
            self._index.delete(delete_all=True, namespace=namespace)
        except Exception as exc:  # noqa: BLE001
            if not is_namespace_missing(exc):  # nothing indexed yet = already clean
                raise map_vector_error(exc) from exc


def indexing_available(s: "Settings") -> tuple[bool, str | None]:
    """(available, reason_code). Used to refuse doomed index/search requests with a clear message."""
    if s.vector_backend == "pinecone" and not s.pinecone_configured:
        return False, "pinecone_not_configured"
    if not s.openai_configured and s.vector_backend != "memory":
        return False, "openai_not_configured"
    return True, None


_MEMORY = InMemoryStore()  # shared within ONE process (tests); API and worker processes do not share it


def get_vector_store(s: "Settings"):
    if s.vector_backend == "memory":
        return _MEMORY
    if not s.pinecone_configured:
        raise NotConfigured("Pinecone is not configured. Set PINECONE_API_KEY and PINECONE_INDEX_NAME.", code="pinecone_not_configured")
    return PineconeStore(s)
