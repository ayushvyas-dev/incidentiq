import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from incidentiq.services import gemini


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body


def test_gemini_chat_maps_analysis_messages_and_usage(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse({
            "candidates": [{"content": {"parts": [{"text": "{\"ok\":"}, {"text": "true}"}]}}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 5},
        })

    monkeypatch.setattr(gemini, "urlopen", fake_urlopen)
    provider = gemini.GeminiChatProvider("secret", "free-model", timeout_seconds=4)
    result = provider.generate(
        [{"role": "system", "content": "fixed policy"}, {"role": "user", "content": "untrusted data"}],
        120,
    )
    request, timeout = requests[0]
    body = json.loads(request.data)
    assert result == ('{"ok":true}', 12, 5)
    assert request.get_header("X-goog-api-key") == "secret"
    assert "secret" not in request.full_url
    assert timeout == 4
    assert body["systemInstruction"]["parts"][0]["text"] == "fixed policy"
    assert body["contents"][0]["parts"][0]["text"] == "untrusted data"
    assert body["generationConfig"]["maxOutputTokens"] == 120


def test_gemini_embeddings_batch_and_dimension(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return FakeResponse({"embeddings": [{"values": [0.1, 0.2]}, {"values": [0.3, 0.4]}]})

    monkeypatch.setattr(gemini, "urlopen", fake_urlopen)
    provider = gemini.GeminiEmbeddings("secret", "embedding-model", 2)
    assert provider.embed(["one", "two"]) == [[0.1, 0.2], [0.3, 0.4]]
    body = json.loads(requests[0].data)
    assert [item["content"]["parts"][0]["text"] for item in body["requests"]] == ["one", "two"]
    assert all(item["outputDimensionality"] == 2 for item in body["requests"])
    assert provider.embed([]) == []


def test_gemini_http_failure_is_sanitized(monkeypatch):
    def fail(*args, **kwargs):
        raise HTTPError("https://redacted", 429, "rate", {}, BytesIO(b"secret response"))

    monkeypatch.setattr(gemini, "urlopen", fail)
    with pytest.raises(gemini.ProviderHTTPError) as exc:
        gemini.GeminiChatProvider("secret-key", "model").generate([], 32)
    assert exc.value.status_code == 429
    assert "secret" not in str(exc.value)


def test_gemini_url_timeout_is_reported_as_timeout(monkeypatch):
    def timeout(*args, **kwargs):
        raise URLError(TimeoutError())

    monkeypatch.setattr(gemini, "urlopen", timeout)
    with pytest.raises(TimeoutError, match="Gemini request timed out"):
        gemini.GeminiChatProvider("key", "model").generate([], 32)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_gemini_rejects_invalid_timeouts(timeout):
    with pytest.raises(ValueError):
        gemini.GeminiChatProvider("secret", "model", timeout)
    with pytest.raises(ValueError):
        gemini.GeminiEmbeddings("secret", "model", 2, timeout)
