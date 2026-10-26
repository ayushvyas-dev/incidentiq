"""Google Gemini REST adapters for chat fallback and embeddings."""

import json
import math
import socket
from collections.abc import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class ProviderHTTPError(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"Provider returned HTTP {status_code}")
        self.status_code = status_code


def _post_json(url: str, payload: dict, timeout: float, api_key: str) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as error:
        raise ProviderHTTPError(error.code) from None
    except TimeoutError:
        raise TimeoutError("Gemini request timed out") from None
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise TimeoutError("Gemini request timed out") from None
        raise ConnectionError("Gemini connection failed") from None


class GeminiChatProvider:
    provider = "gemini"

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 20):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate(
        self, messages: Sequence[dict[str, str]], max_output_tokens: int
    ) -> tuple[str, int | None, int | None]:
        system_instruction = next((item["content"] for item in messages if item["role"] == "system"), None)
        contents = [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in messages if item["role"] != "system"
        ]
        payload = {
            "contents": contents,
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0,
                "maxOutputTokens": max_output_tokens,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(self.model, safe='')}:generateContent"
        )
        response = _post_json(endpoint, payload, self.timeout_seconds, self.api_key)
        candidates = response.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        content = "".join(part.get("text", "") for part in parts)
        usage = response.get("usageMetadata", {})
        return content, usage.get("promptTokenCount"), usage.get("candidatesTokenCount")


class GeminiEmbeddings:
    """Gemini-only embedding adapter; output dimension must match the Pinecone index."""

    def __init__(self, api_key: str, model: str, dimension: int, timeout_seconds: float = 20):
        if (
            not api_key or not model or dimension < 1
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
        ):
            raise ValueError("Gemini embedding configuration is invalid")
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.timeout_seconds = timeout_seconds

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = f"models/{self.model}"
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(self.model, safe='')}:batchEmbedContents"
        )
        payload = {
            "requests": [
                {
                    "model": model,
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": self.dimension,
                }
                for text in texts
            ]
        }
        response = _post_json(endpoint, payload, self.timeout_seconds, self.api_key)
        return [item["values"] for item in response["embeddings"]]
