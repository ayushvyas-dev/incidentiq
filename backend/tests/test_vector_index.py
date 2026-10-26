from types import SimpleNamespace

from incidentiq.services import vector_index


def test_pinecone_adapter_uses_index_namespace_and_metadata(monkeypatch):
    class FakeIndex:
        def upsert(self, **kwargs):
            self.upsert_request = kwargs

        def query(self, **kwargs):
            self.query_request = kwargs
            return SimpleNamespace(matches=[SimpleNamespace(id="chunk-1", score=0.8)])

        def delete(self, **kwargs):
            self.delete_request = kwargs

    class FakePinecone:
        def __init__(self, api_key):
            assert api_key == "pinecone-test"
            self.index = FakeIndex()

        def Index(self, name):
            assert name == "test-index"
            calls.append(name)
            return self.index

    calls = []
    monkeypatch.setattr(vector_index, "Pinecone", FakePinecone)
    store = vector_index.PineconeVectorStore("pinecone-test", "test-index")
    assert calls == []
    records = [{"id": "chunk-1", "values": [0.1], "metadata": {"service": "checkout"}}]
    store.upsert(records, "test-namespace")
    assert calls == ["test-index"]
    assert store.index.upsert_request == {
        "vectors": records,
        "namespace": "test-namespace",
    }
    assert store.query(
        [0.1], 4, "test-namespace", {"service": {"$eq": "checkout"}}
    ) == [("chunk-1", 0.8)]
    assert store.index.query_request["filter"] == {"service": {"$eq": "checkout"}}
    store.delete(["chunk-1"], "test-namespace")
    assert store.index.delete_request == {
        "ids": ["chunk-1"],
        "namespace": "test-namespace",
    }
