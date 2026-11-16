"""
Gemini 기반 습득물 등록 분석 (FINDYU_REGISTRATION_ANALYZER_MODE=gemini).

- 시스템 프롬프트: prompts/identify_item_v1.1.md
- 구조화 출력: response_schema(아래 IdentifyItemResult)로 JSON 구조와 허용값을 강제
- 결과는 labels.py 기준으로 한 번 더 정규화하고, 품명과 맞지 않는 필드는 비운다

환경변수
- GEMINI_API_KEY       (필수) Google AI Studio API 키
- FINDYU_GEMINI_MODEL  사용할 모델명, 기본 gemini-3.5-flash (예: gemini-3.8-flash로 변경 가능)
- FINDYU_GEMINI_TIMEOUT 요청당 제한 시간(초), 기본 60
"""

import io
import logging
import os
import re
import threading
from pathlib import Path
from typing import Literal, Optional

from PIL import Image
from pydantic import BaseModel, Field, ValidationError

import labels

logger = logging.getLogger("findyu.gemini")

PROMPT_VERSION = "v1.2"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / f"identify_item_{PROMPT_VERSION}.md"

# 2026-11 비교 결과(docs/model_comparison.md) 속도·안정성 기준으로 선택
DEFAULT_MODEL = "gemini-3.5-flash"

MAX_IMAGES = 5
MAX_IMAGE_SIDE = 1024
RETRY_STATUS_CODES = [408, 429, 500, 502, 503, 504]


class AnalyzerConfigError(RuntimeError):
    """API 키·모델명 누락 등 설정 문제. 서버는 계속 동작하고 분석 요청만 실패한다."""


class AnalyzerError(RuntimeError):
    """Gemini 호출 또는 응답 해석 실패."""


# ---------------------------------------------------------
# 응답 스키마 (프롬프트 v1.1의 출력 형식과 일치)
# ---------------------------------------------------------
Confidence = Literal["높음", "보통", "낮음"]


class ConfidenceByField(BaseModel):
    category: Confidence
    manufacturer: Confidence
    device_model: Confidence
    color: Confidence


class GenerationEvidence(BaseModel):
    """세대를 구분하는 특징과 그 특징이 보인 사진 번호 (1부터)"""

    feature: str
    photo: int


class IdentifyItemResult(BaseModel):
    same_item: Optional[bool] = None
    category: Literal["스마트폰", "지갑", "기타"]
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    device_model: Optional[str] = None
    color: Literal[labels.COLORS]  # type: ignore[valid-type]
    features: list[str] = Field(default_factory=list, max_length=5)
    evidence: list[str] = Field(default_factory=list, max_length=4)
    # 식별수준은 모델이 매기지 않고 이 필드로 백엔드가 결정한다 (decide_identification_level)
    generation_evidence: list[GenerationEvidence] = Field(default_factory=list, max_length=3)
    confidence: ConfidenceByField
    device_model_candidates: list[str] = Field(default_factory=list, max_length=2)
    verification_needed: list[str] = Field(default_factory=list, max_length=3)
    has_case: Optional[bool] = None
    wallet_type: Optional[Literal["장지갑", "반지갑", "카드지갑"]] = None
    material: Optional[Literal[labels.MATERIALS]] = None  # type: ignore[valid-type]


def load_system_prompt(path: Path = PROMPT_PATH) -> str:
    text = path.read_text(encoding="utf-8")
    # 변경 이력 등 HTML 주석은 모델에 보내지 않는다
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


# ---------------------------------------------------------
# 설정 / client
# ---------------------------------------------------------
def config_status() -> dict:
    """서버 상태 표시용. API 키 값은 노출하지 않는다."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = gemini_model()
    missing = [] if api_key else ["GEMINI_API_KEY"]
    return {
        "ready": not missing,
        "model": model or None,
        "prompt_version": PROMPT_VERSION,
        "error": config_error_message(missing) if missing else None,
    }


def gemini_model() -> str:
    return os.getenv("FINDYU_GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def config_error_message(missing: list[str]) -> str:
    return (
        f"Gemini 등록 분석에 필요한 환경변수가 없습니다: {', '.join(missing)}. "
        "backend/.env 파일에 설정한 뒤 서버를 다시 시작하세요 (backend/.env.example 참고)."
    )


class GeminiAnalyzer:
    def __init__(self, client=None):
        # 테스트에서는 가짜 client를 주입한다
        self._client = client
        self._lock = threading.Lock()
        self._system_prompt = None

    def _get_client(self):
        status = config_status()
        if not status["ready"]:
            raise AnalyzerConfigError(status["error"])

        if self._client is None:
            with self._lock:
                if self._client is None:
                    from google import genai
                    from google.genai import types

                    timeout_sec = float(os.getenv("FINDYU_GEMINI_TIMEOUT", "60"))
                    self._client = genai.Client(
                        api_key=os.environ["GEMINI_API_KEY"].strip(),
                        http_options=types.HttpOptions(
                            timeout=int(timeout_sec * 1000),
                            # 일시적 오류(429, 5xx)는 SDK가 지수 backoff로 재시도
                            retry_options=types.HttpRetryOptions(
                                attempts=3,
                                initial_delay=2.0,
                                max_delay=10.0,
                                http_status_codes=RETRY_STATUS_CODES,
                            ),
                        ),
                    )
        return self._client

    def _get_system_prompt(self):
        if self._system_prompt is None:
            self._system_prompt = load_system_prompt()
        return self._system_prompt

    def analyze(self, images: list[Image.Image]) -> dict:
        """사진 1장 이상 → 정규화된 등록 정보 dict (normalize_result 참고)."""
        if not images:
            raise ValueError("분석할 사진이 없습니다.")
        if len(images) > MAX_IMAGES:
            raise ValueError(f"사진은 최대 {MAX_IMAGES}장까지 분석할 수 있습니다.")

        client = self._get_client()
        model = gemini_model()

        from google.genai import errors, types

        contents = []
        for index, image in enumerate(images, start=1):
            contents.append(f"사진 {index}")
            contents.append(
                types.Part.from_bytes(data=encode_image(image), mime_type="image/jpeg")
            )
        contents.append(f"위 사진 {len(images)}장의 물품을 식별하세요.")

        config = types.GenerateContentConfig(
            system_instruction=self._get_system_prompt(),
            response_mime_type="application/json",
            response_schema=IdentifyItemResult,
            temperature=0,
        )

        try:
            response = client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except errors.APIError as exc:
            raise AnalyzerError(describe_api_error(exc)) from exc
        except Exception as exc:  # 네트워크 오류, 타임아웃 등
            raise AnalyzerError(f"Gemini 호출 실패: {type(exc).__name__}: {exc}") from exc

        result = parse_response(response)
        normalized = normalize_result(result, image_count=len(images))
        normalized["model"] = model
        return normalized


def describe_api_error(exc) -> str:
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)
    if code in (401, 403) or (code == 400 and "API key" in message):
        return f"Gemini API 키가 유효하지 않거나 권한이 없습니다 ({code}): {message}"
    if code == 404:
        return f"Gemini 모델을 찾을 수 없습니다. FINDYU_GEMINI_MODEL 값을 확인하세요 ({code}): {message}"
    if code == 429:
        return f"Gemini 요청 한도를 초과했습니다 (재시도 후에도 실패, {code}): {message}"
    return f"Gemini API 오류 ({code}): {message}"


def encode_image(image: Image.Image) -> bytes:
    """긴 변 MAX_IMAGE_SIDE로 줄이고 JPEG으로 재인코딩 (EXIF 등 메타데이터 제거)."""
    rgb = image.convert("RGB")
    rgb.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def parse_response(response) -> IdentifyItemResult:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, IdentifyItemResult):
        return parsed

    text = getattr(response, "text", None)
    if not text:
        raise AnalyzerError("Gemini 응답이 비어 있습니다 (안전 필터 차단 등).")
    try:
        return IdentifyItemResult.model_validate_json(text)
    except ValidationError as exc:
        raise AnalyzerError(f"Gemini 응답이 스키마와 맞지 않습니다: {text[:300]}") from exc


def _clean_text(value) -> str | None:
    text = (value or "").strip()
    return text or None


def _clean_list(values, limit: int, exclude: set[str] = frozenset()) -> list[str]:
    result = []
    for value in values or []:
        text = (value or "").strip()
        if text and text not in exclude and text not in result:
            result.append(text)
    return result[:limit]


def clean_generation_evidence(items, image_count: int | None) -> list[dict]:
    """빈 특징, 범위를 벗어난 사진 번호(보내지 않은 사진)를 가진 항목은 버린다."""
    cleaned = []
    for item in items or []:
        feature = (item.feature or "").strip()
        photo = item.photo
        if not feature:
            continue
        if photo < 1 or (image_count is not None and photo > image_count):
            continue
        entry = {"feature": feature, "photo": photo}
        if entry not in cleaned:
            cleaned.append(entry)
    return cleaned[:3]


def decide_identification_level(
    device_model: str | None, category_confidence: str, generation_evidence: list
) -> str:
    """
    식별수준은 모델이 아니라 백엔드가 정한다.
    - 미확인: 기종이 없거나 품명 확신도가 "낮음"
    - 확인  : 세대 구분 근거(특징 + 사진 번호)가 하나 이상 있음
    - 추정  : 기종은 있으나 세대 구분 근거가 없음
    """
    if device_model is None or category_confidence == "낮음":
        return "미확인"
    return "확인" if generation_evidence else "추정"


def normalize_result(result: IdentifyItemResult, image_count: int | None = None) -> dict:
    """스키마 결과를 DB 저장 형식으로 정리하고 품명과 맞지 않는 필드를 비운다."""
    category = labels.normalize_category(result.category) or labels.CATEGORY_OTHER
    color = labels.normalize_color(result.color) or labels.COLOR_UNKNOWN
    device_model = _clean_text(result.device_model)

    candidates = _clean_list(
        result.device_model_candidates, 2, exclude={device_model} if device_model else set()
    )
    verification_needed = _clean_list(result.verification_needed, 3)
    generation_evidence = (
        clean_generation_evidence(result.generation_evidence, image_count)
        if device_model is not None
        else []
    )
    identification_level = decide_identification_level(
        device_model, result.confidence.category, generation_evidence
    )
    features = _clean_list(result.features, 5)

    has_case = result.has_case if category == labels.CATEGORY_PHONE else None
    wallet_type = (
        labels.normalize_wallet_type(result.wallet_type)
        if category == labels.CATEGORY_WALLET
        else None
    )
    material = (
        labels.normalize_material(result.material)
        if category == labels.CATEGORY_WALLET
        else None
    )

    manufacturer = _clean_text(result.manufacturer)
    brand = _clean_text(result.brand)

    confidence_labels = result.confidence.model_dump()
    values = {
        "category": category,
        "manufacturer": manufacturer,
        "device_model": device_model,
        "color": None if color == labels.COLOR_UNKNOWN else color,
    }
    # 값이 없는 항목(null/미확인)의 확신도는 저장하지 않는다
    confidence_scores = {
        field: (labels.confidence_to_score(level) if values[field] is not None else None)
        for field, level in confidence_labels.items()
    }

    return {
        "category": category,
        "color": color,
        "manufacturer": manufacturer,
        "brand": brand,
        "device_model": device_model,
        "device_model_candidates": candidates,
        "identification_level": identification_level,
        "has_case": has_case,
        "wallet_type": wallet_type,
        "material": material,
        "verification_needed": verification_needed,
        "features": " · ".join(features) if features else None,
        "evidence": _clean_list(result.evidence, 4),
        "generation_evidence": generation_evidence,
        "same_item": result.same_item,
        "confidence": confidence_labels,
        "confidence_scores": confidence_scores,
        "prompt_version": PROMPT_VERSION,
    }
