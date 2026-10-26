"""Embedding and Pinecone adapters used by synchronous ingestion."""

from collections.abc import Sequence
from typing import Protocol

from pinecone import Pinecone


class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    def upsert(self, vectors: list[dict], namespace: str) -> None: ...

    def delete(self, ids: list[str], namespace: str) -> None: ...

    def query(
        self, vector: list[float], top_k: int, namespace: str, filters: dict
    ) -> list[tuple[str, float]]: ...


class PineconeVectorStore:
    def __init__(self, api_key: str, index_name: str):
        self.api_key = api_key
        self.index_name = index_name
        self._index = None

    @property
    def index(self):
        if self._index is None:
            self._index = Pinecone(api_key=self.api_key).Index(self.index_name)
        return self._index

    def upsert(self, vectors: list[dict], namespace: str) -> None:
        self.index.upsert(vectors=vectors, namespace=namespace)

    def delete(self, ids: list[str], namespace: str) -> None:
        for offset in range(0, len(ids), 1000):
            self.index.delete(ids=ids[offset : offset + 1000], namespace=namespace)

    def query(
        self, vector: list[float], top_k: int, namespace: str, filters: dict
    ) -> list[tuple[str, float]]:
        result = self.index.query(
            vector=vector,
            top_k=top_k,
            namespace=namespace,
            filter=filters or None,
            include_metadata=False,
        )
        return [(match.id, float(match.score)) for match in result.matches]
