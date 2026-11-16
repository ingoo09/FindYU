import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
from PIL import Image

import gemini_analyzer as ga
import labels


def _payload(**overrides):
    data = {
        "same_item": True,
        "category": "스마트폰",
        "manufacturer": "애플",
        "brand": "애플",
        "device_model": "iPhone 15 Pro",
        "color": "검정",
        "features": ["투명 케이스", "뒷면 스티커"],
        "evidence": ["사진 1: 트리플 카메라"],
        "confidence": {"category": "높음", "manufacturer": "높음", "device_model": "보통", "color": "낮음"},
        "identification_level": "추정",
        "device_model_candidates": ["iPhone 15 Pro", "iPhone 14 Pro"],
        "verification_needed": ["측면 버튼 사진"],
        "has_case": True,
        "wallet_type": "반지갑",
        "material": "가죽",
    }
    data.update(overrides)
    return data


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return self.response


def _client(response=None, error=None):
    return SimpleNamespace(models=FakeModels(response, error))


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("FINDYU_GEMINI_MODEL", "test-model")


def _image(color="red"):
    return Image.new("RGB", (2000, 1000), color)


# ---------------------------------------------------------
# 설정
# ---------------------------------------------------------
def test_missing_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("FINDYU_GEMINI_MODEL", "test-model")

    status = ga.config_status()
    assert status["ready"] is False
    assert "GEMINI_API_KEY" in status["error"]
    assert "backend/.env" in status["error"]

    with pytest.raises(ga.AnalyzerConfigError, match="GEMINI_API_KEY"):
        ga.GeminiAnalyzer(client=_client()).analyze([_image()])


def test_blank_key_and_default_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    monkeypatch.delenv("FINDYU_GEMINI_MODEL", raising=False)
    status = ga.config_status()
    assert "GEMINI_API_KEY" in status["error"]
    # 모델명은 없으면 기본값
    assert status["model"] == "gemini-3.5-flash"

    monkeypatch.setenv("FINDYU_GEMINI_MODEL", "gemini-3.8-flash")
    assert ga.config_status()["model"] == "gemini-3.8-flash"


def test_config_status_never_exposes_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value-123")
    monkeypatch.setenv("FINDYU_GEMINI_MODEL", "m")
    assert "secret-value-123" not in json.dumps(ga.config_status())


# ---------------------------------------------------------
# 호출 구조
# ---------------------------------------------------------
def test_request_structure_multiple_images(env):
    client = _client(SimpleNamespace(parsed=ga.IdentifyItemResult(**_payload()), text=None))
    result = ga.GeminiAnalyzer(client=client).analyze([_image(), _image("blue")])

    call = client.models.calls[0]
    assert call["model"] == "test-model"
    assert call["contents"][0] == "사진 1"
    assert call["contents"][2] == "사진 2"
    assert "2장" in call["contents"][-1]

    part = call["contents"][1]
    assert part.inline_data.mime_type == "image/jpeg"
    with Image.open(__import__("io").BytesIO(part.inline_data.data)) as sent:
        assert max(sent.size) == ga.MAX_IMAGE_SIDE  # 긴 변 축소

    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is ga.IdentifyItemResult
    assert config.temperature == 0
    assert "FindYU" in config.system_instruction
    assert "<!--" not in config.system_instruction  # 변경 이력 주석은 보내지 않음

    assert result["model"] == "test-model"
    assert result["prompt_version"] == "v1.1"


def test_falls_back_to_text_when_parsed_missing(env):
    client = _client(SimpleNamespace(parsed=None, text=json.dumps(_payload(), ensure_ascii=False)))
    result = ga.GeminiAnalyzer(client=client).analyze([_image()])
    assert result["device_model"] == "iPhone 15 Pro"


@pytest.mark.parametrize("text", [None, "", "not json", json.dumps({"category": "노트북"})])
def test_bad_response_raises_analyzer_error(env, text):
    client = _client(SimpleNamespace(parsed=None, text=text))
    with pytest.raises(ga.AnalyzerError):
        ga.GeminiAnalyzer(client=client).analyze([_image()])


def test_api_error_is_wrapped_with_hint(env):
    from google.genai import errors

    exc = errors.ClientError(404, {"error": {"code": 404, "message": "model not found", "status": "NOT_FOUND"}})
    with pytest.raises(ga.AnalyzerError, match="FINDYU_GEMINI_MODEL"):
        ga.GeminiAnalyzer(client=_client(error=exc)).analyze([_image()])

    exc = errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT"}})
    with pytest.raises(ga.AnalyzerError, match="API 키"):
        ga.GeminiAnalyzer(client=_client(error=exc)).analyze([_image()])


def test_network_error_is_wrapped(env):
    with pytest.raises(ga.AnalyzerError, match="TimeoutError"):
        ga.GeminiAnalyzer(client=_client(error=TimeoutError("slow"))).analyze([_image()])


def test_image_count_limits(env):
    analyzer = ga.GeminiAnalyzer(client=_client())
    with pytest.raises(ValueError):
        analyzer.analyze([])
    with pytest.raises(ValueError):
        analyzer.analyze([_image()] * (ga.MAX_IMAGES + 1))


# ---------------------------------------------------------
# 결과 정규화
# ---------------------------------------------------------
def test_normalize_phone():
    result = ga.normalize_result(ga.IdentifyItemResult(**_payload()))

    assert result["category"] == "스마트폰"
    assert result["has_case"] is True
    # 스마트폰이면 지갑 전용 필드는 비움
    assert result["wallet_type"] is None
    assert result["material"] is None
    # device_model과 같은 후보는 제외
    assert result["device_model_candidates"] == ["iPhone 14 Pro"]
    assert result["features"] == "투명 케이스 · 뒷면 스티커"
    assert result["confidence_scores"] == {
        "category": 0.9, "manufacturer": 0.9, "device_model": 0.6, "color": 0.3,
    }
    assert result["confidence"]["device_model"] == "보통"


def test_normalize_wallet():
    result = ga.normalize_result(ga.IdentifyItemResult(**_payload(
        category="지갑", device_model=None, manufacturer=None, brand="닥스",
        identification_level="추정", device_model_candidates=[], color="갈색",
    )))
    assert result["wallet_type"] == "반지갑"
    assert result["material"] == "가죽"
    assert result["has_case"] is None
    # 기종이 없으면 식별수준은 미확인, 값이 없는 항목의 확신도는 저장하지 않음
    assert result["identification_level"] == "미확인"
    assert result["confidence_scores"]["device_model"] is None
    assert result["confidence_scores"]["manufacturer"] is None
    assert result["confidence_scores"]["color"] == 0.3


def test_normalize_other_clears_specific_fields():
    result = ga.normalize_result(ga.IdentifyItemResult(**_payload(category="기타", color="미확인")))
    assert (result["has_case"], result["wallet_type"], result["material"]) == (None, None, None)
    assert result["color"] == "미확인"
    assert result["confidence_scores"]["color"] is None


def test_schema_rejects_values_outside_lists():
    with pytest.raises(Exception):
        ga.IdentifyItemResult(**_payload(color="투명"))
    with pytest.raises(Exception):
        ga.IdentifyItemResult(**_payload(category="이어폰"))
    with pytest.raises(Exception):
        ga.IdentifyItemResult(**_payload(confidence={"category": "매우높음", "manufacturer": "높음", "device_model": "높음", "color": "높음"}))


def test_schema_converts_for_gemini():
    from google import genai
    from google.genai import _transformers as t

    schema = t.t_schema(genai.Client(api_key="x")._api_client, ga.IdentifyItemResult).model_dump(exclude_none=True)
    props = schema["properties"]
    assert props["category"]["enum"] == list(labels.CATEGORIES)
    assert props["color"]["enum"] == list(labels.COLORS)
    assert props["material"]["enum"] == list(labels.MATERIALS)
    assert props["material"]["nullable"] is True


# ---------------------------------------------------------
# 프롬프트와 labels.py 동기화
# ---------------------------------------------------------
def test_prompt_lists_match_labels():
    prompt = ga.load_system_prompt()
    for value in (*labels.COLORS, *labels.MATERIALS, *labels.CATEGORIES, *labels.WALLET_TYPES,
                  *labels.CONFIDENCE_LEVELS, *labels.IDENTIFICATION_LEVELS):
        assert value in prompt, f"프롬프트에 '{value}'가 없음"

    # 프롬프트 예시 JSON의 키 = 스키마 필드
    example = json.loads(re.search(r"\{\s*\"same_item\".*?\n\}", prompt, re.DOTALL).group(0))
    assert set(example) == set(ga.IdentifyItemResult.model_fields)
    assert set(example["confidence"]) == set(ga.ConfidenceByField.model_fields)


def test_confidence_mapping():
    assert labels.confidence_to_score("높음") == 0.9
    assert labels.confidence_to_score("보통") == 0.6
    assert labels.confidence_to_score("낮음") == 0.3
    assert labels.confidence_to_score("모름") is None
    assert labels.confidence_to_score(None) is None


def test_exif_rotation_is_applied_for_analysis(tmp_path):
    """휴대폰 사진의 EXIF 회전(Orientation=6)을 반영해 세로로 세워야 한다."""
    import ast
    from PIL import ImageOps

    src = Image.new("RGB", (400, 300), "red")
    exif = src.getexif()
    exif[0x0112] = 6
    path = tmp_path / "rotated.jpg"
    src.save(path, exif=exif)

    # main.py를 import하면 모델·DB가 초기화되므로 함수만 꺼내 실행한다
    main_src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    func = next(n for n in ast.parse(main_src).body if isinstance(n, ast.FunctionDef) and n.name == "open_analysis_image")
    namespace = {"Image": Image, "ImageOps": ImageOps}
    exec(compile(ast.Module(body=[func], type_ignores=[]), "main.py", "exec"), namespace)

    assert namespace["open_analysis_image"](path).size == (300, 400)
