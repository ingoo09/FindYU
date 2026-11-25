import json

import pytest
from PIL import Image

import gemini_embedding as ge
from gemini_analyzer import AnalyzerConfigError, AnalyzerError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeHttp:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def post(self, url, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if self.error:
            raise self.error
        return self.response


def _ok(n, dims=256, tokens_per_image=258):
    return FakeResponse(200, {
        "data": [{"index": i, "embedding": [0.1] * dims} for i in reversed(range(n))],
        "usage": {"prompt_tokens": tokens_per_image * n},
    })


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BAZE_API_KEY", "test-key")
    monkeypatch.setenv("FINDYU_BAZE_BASE_URL", "https://example.test/v1/gateway")
    monkeypatch.delenv("FINDYU_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("FINDYU_EMBEDDING_DIMENSIONS", raising=False)


def _img(color="red"):
    return Image.new("RGB", (2000, 1500), color)


def test_request_uses_image_url_objects(env):
    http = FakeHttp(_ok(2))
    embedder = ge.GatewayEmbedder(http_client=http)
    vectors = embedder.embed_images([_img("red"), _img("blue")])

    assert len(vectors) == 2 and len(vectors[0]) == 256
    call = http.calls[0]
    assert call["url"] == "https://example.test/v1/gateway/embeddings"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    body = call["json"]
    assert body["model"] == "gemini-embedding-2" and body["dimensions"] == 256
    for part in body["input"]:
        # data URL 문자열이 아니라 image_url 객체여야 사진으로 처리된다
        assert part["type"] == "image_url"
        assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert embedder.model_id == "gemini-embedding-2@256"


def test_text_like_token_count_is_rejected(env):
    # 2026-11-25 실험: data URL을 글자로 처리하면 사진 1장에 182,079토큰
    http = FakeHttp(_ok(1, tokens_per_image=182079))
    with pytest.raises(ge.EmbeddingError, match="글자로 처리"):
        ge.GatewayEmbedder(http_client=http).embed_images([_img()])


@pytest.mark.parametrize("response, message", [
    (_ok(1, dims=128), "차원"),
    (FakeResponse(200, {"data": [], "usage": {}}), "개수"),
    (FakeResponse(200, None, text="<html>"), "형식"),
    (FakeResponse(500, None, text="upstream error"), "500"),
    (FakeResponse(429, None, text="quota"), "429"),
])
def test_bad_responses(env, response, message):
    with pytest.raises(ge.EmbeddingError, match=message):
        ge.GatewayEmbedder(http_client=FakeHttp(response)).embed_images([_img()])


def test_network_error_is_wrapped_and_not_retried(env):
    http = FakeHttp(error=RuntimeError("connection reset"))
    with pytest.raises(AnalyzerError, match="임베딩 호출 실패"):
        ge.GatewayEmbedder(http_client=http).embed_images([_img()])
    assert len(http.calls) == 1


def test_missing_key(monkeypatch):
    monkeypatch.delenv("BAZE_API_KEY", raising=False)
    http = FakeHttp(_ok(1))
    with pytest.raises(AnalyzerConfigError, match="BAZE_API_KEY"):
        ge.GatewayEmbedder(http_client=http).embed_images([_img()])
    assert http.calls == []


def test_mock_embedder_is_deterministic():
    from ai_retrieval import cosine_score

    a = Image.linear_gradient("L").convert("RGB")
    b = Image.linear_gradient("L").rotate(90).convert("RGB")
    mock = ge.MockEmbedder()
    va, va2, vb = mock.embed_images([a, a.copy(), b])
    assert cosine_score(va, va2) == pytest.approx(1.0)
    assert cosine_score(va, vb) < 0.5
    assert mock.model_id != ge.GatewayEmbedder().model_id  # DB에서 서로 섞이지 않게


def test_make_embedder():
    assert isinstance(ge.make_embedder("baze"), ge.GatewayEmbedder)
    assert isinstance(ge.make_embedder("mock"), ge.MockEmbedder)
    assert ge.make_embedder("local") is None
