import json

import pytest
from PIL import Image

import baze_analyzer as ba
import gemini_analyzer as ga
from gemini_analyzer import AnalyzerConfigError, AnalyzerError


def _payload(**overrides):
    data = {
        "same_item": True,
        "category": "스마트폰",
        "manufacturer": "애플",
        "brand": "애플",
        "device_model": "iPhone 15 Pro",
        "color": "검정",
        "features": ["투명 케이스"],
        "evidence": ["사진 1: 트리플 카메라"],
        "confidence": {"category": "높음", "manufacturer": "높음", "device_model": "보통", "color": "낮음"},
        "generation_evidence": [{"feature": "측면 액션 버튼", "photo": 2}],
        "device_model_candidates": ["iPhone 15 Pro Max"],
        "verification_needed": [],
        "has_case": True,
        "wallet_type": None,
        "material": None,
    }
    data.update(overrides)
    return data


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload, ensure_ascii=False)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _ok(content):
    return FakeResponse(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _analyzer(*responses):
    http = FakeHttp(responses)
    return ba.BazeAnalyzer(http_client=http, sleep=lambda _: None), http


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BAZE_API_KEY", "test-key")
    monkeypatch.setenv("FINDYU_BAZE_MODEL", "test-model")
    monkeypatch.delenv("FINDYU_BAZE_BASE_URL", raising=False)


def _image(color="red"):
    return Image.new("RGB", (2000, 1000), color)


def test_missing_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("BAZE_API_KEY", raising=False)
    analyzer, http = _analyzer()
    with pytest.raises(AnalyzerConfigError, match="BAZE_API_KEY"):
        analyzer.analyze([_image()])
    assert http.calls == []


def test_defaults_and_status_never_exposes_key(monkeypatch):
    monkeypatch.setenv("BAZE_API_KEY", "secret-value")
    monkeypatch.setenv("FINDYU_BAZE_MODEL", " ")
    monkeypatch.setenv("FINDYU_BAZE_BASE_URL", "")
    status = ba.config_status()
    assert status["ready"] is True
    assert status["model"] == "gemini-3.5-flash"
    assert status["base_url"] == "https://factchat-cloud.mindlogic.ai/v1/gateway"
    assert "secret-value" not in json.dumps(status)


def test_request_structure_multiple_images(env, monkeypatch):
    monkeypatch.setenv("FINDYU_BAZE_BASE_URL", "https://example.test/v1/gateway/")
    analyzer, http = _analyzer(_ok(json.dumps(_payload(), ensure_ascii=False)))
    result = analyzer.analyze([_image("red"), _image("blue")])

    call = http.calls[0]
    assert call["url"] == "https://example.test/v1/gateway/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    body = call["json"]
    assert body["model"] == "test-model"
    assert body["temperature"] == 0
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == ga.IdentifyItemResult.model_json_schema()

    system, user = body["messages"]
    assert system["role"] == "system" and "Step 4" in system["content"]
    texts = [p["text"] for p in user["content"] if p["type"] == "text"]
    assert texts == ["사진 1", "사진 2", "위 사진 2장의 물품을 식별하세요."]
    images = [p for p in user["content"] if p["type"] == "image_url"]
    assert len(images) == 2
    assert images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    # gemini 모드와 같은 정규화 결과 (식별수준은 백엔드가 결정)
    assert result["model"] == "test-model"
    assert result["identification_level"] == "확인"
    assert result["generation_evidence"] == [{"feature": "측면 액션 버튼", "photo": 2}]
    assert result["prompt_version"] == ga.PROMPT_VERSION


def test_same_output_as_gemini_normalization(env):
    payload = _payload()
    analyzer, _ = _analyzer(_ok(json.dumps(payload, ensure_ascii=False)))
    result = analyzer.analyze([_image(), _image()])
    expected = ga.normalize_result(ga.IdentifyItemResult.model_validate(payload), image_count=2)
    expected["model"] = "test-model"
    assert result == expected


def test_accepts_code_fenced_json(env):
    content = "```json\n" + json.dumps(_payload(), ensure_ascii=False) + "\n```"
    analyzer, _ = _analyzer(_ok(content))
    assert analyzer.analyze([_image()])["device_model"] == "iPhone 15 Pro"


def test_rejects_values_outside_schema(env):
    analyzer, _ = _analyzer(_ok(json.dumps(_payload(color="자주"), ensure_ascii=False)))
    with pytest.raises(AnalyzerError, match="스키마"):
        analyzer.analyze([_image()])


@pytest.mark.parametrize("response", [
    _ok(""),
    FakeResponse(200, {"choices": []}),
    FakeResponse(200, None, text="<html>"),
])
def test_empty_or_bad_response(env, response):
    analyzer, _ = _analyzer(response)
    with pytest.raises(AnalyzerError):
        analyzer.analyze([_image()])


def test_retries_transient_errors_then_succeeds(env):
    analyzer, http = _analyzer(
        FakeResponse(503, None, text="busy"),
        RuntimeError("connection reset"),
        _ok(json.dumps(_payload(), ensure_ascii=False)),
    )
    assert analyzer.analyze([_image()])["category"] == "스마트폰"
    assert len(http.calls) == 3


def test_quota_error_keeps_status_code_after_retries(env):
    analyzer, http = _analyzer(*[FakeResponse(429, None, text="quota") for _ in range(3)])
    with pytest.raises(AnalyzerError, match="429"):
        analyzer.analyze([_image()])
    assert len(http.calls) == ba.RETRY_ATTEMPTS


def test_auth_error_is_not_retried(env):
    analyzer, http = _analyzer(FakeResponse(401, None, text="bad key"))
    with pytest.raises(AnalyzerError, match="키가 유효하지"):
        analyzer.analyze([_image()])
    assert len(http.calls) == 1


def test_image_count_limits(env):
    analyzer, _ = _analyzer()
    with pytest.raises(ValueError):
        analyzer.analyze([])
    with pytest.raises(ValueError):
        analyzer.analyze([_image()] * (ga.MAX_IMAGES + 1))
