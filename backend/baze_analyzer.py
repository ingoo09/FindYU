"""
학교 팩트챗(마인드로직 BAZE API Gateway) 기반 습득물 등록 분석
(FINDYU_REGISTRATION_ANALYZER_MODE=baze).

- OpenAI 호환 /chat/completions 로 Gemini 모델을 호출한다.
- 시스템 프롬프트, 응답 스키마(IdentifyItemResult), 정규화·식별수준 결정은
  gemini 모드(gemini_analyzer.py)와 같은 것을 그대로 쓴다 → DB 저장 형식도 같다.
- 구조화 출력: response_format=json_schema 로 요청하고, 응답은 백엔드에서 pydantic으로 다시 검증한다.
  (2026-11-25 확인: 게이트웨이에서 이미지 입력과 json_schema enum 제약이 모두 동작)

환경변수
- BAZE_API_KEY          (필수) 팩트챗 API 키
- FINDYU_BAZE_BASE_URL  기본 https://factchat-cloud.mindlogic.ai/v1/gateway
- FINDYU_BAZE_MODEL     기본 gemini-3.5-flash (예: gemini-3.8-flash)
- FINDYU_BAZE_TIMEOUT   요청당 제한 시간(초), 기본 120
"""

import base64
import logging
import os
import threading
import time

from PIL import Image

import gemini_analyzer as ga
from gemini_analyzer import AnalyzerConfigError, AnalyzerError

logger = logging.getLogger("findyu.baze")

DEFAULT_BASE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway"
DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_TIMEOUT = 120.0

RETRY_ATTEMPTS = 3
RETRY_INITIAL_DELAY = 2.0
RETRY_MAX_DELAY = 10.0


def baze_model() -> str:
    return os.getenv("FINDYU_BAZE_MODEL", "").strip() or DEFAULT_MODEL


def baze_base_url() -> str:
    return (os.getenv("FINDYU_BAZE_BASE_URL", "").strip() or DEFAULT_BASE_URL).rstrip("/")


def config_status() -> dict:
    """서버 상태 표시용. API 키 값은 노출하지 않는다."""
    api_key = os.getenv("BAZE_API_KEY", "").strip()
    missing = [] if api_key else ["BAZE_API_KEY"]
    return {
        "ready": not missing,
        "base_url": baze_base_url(),
        "model": baze_model(),
        "prompt_version": ga.PROMPT_VERSION,
        "error": config_error_message(missing) if missing else None,
    }


def config_error_message(missing: list[str]) -> str:
    return (
        f"BAZE(팩트챗) 등록 분석에 필요한 환경변수가 없습니다: {', '.join(missing)}. "
        "backend/.env 파일에 설정한 뒤 서버를 다시 시작하세요 (backend/.env.example 참고)."
    )


def response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "identify_item",
            # pydantic 스키마(Optional → anyOf null, 기본값 등)는 OpenAI strict 규칙과 맞지 않으므로
            # strict는 끄고, 결과는 parse_response에서 pydantic으로 검증한다
            "strict": False,
            "schema": ga.IdentifyItemResult.model_json_schema(),
        },
    }


def build_messages(system_prompt: str, images: list[Image.Image]) -> list[dict]:
    content = []
    for index, image in enumerate(images, start=1):
        data = base64.b64encode(ga.encode_image(image)).decode("ascii")
        content.append({"type": "text", "text": f"사진 {index}"})
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}
        )
    content.append({"type": "text", "text": f"위 사진 {len(images)}장의 물품을 식별하세요."})
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]


def describe_http_error(status: int, body: str) -> str:
    message = body.strip()[:500]
    if status in (401, 403):
        return f"BAZE API 키가 유효하지 않거나 권한이 없습니다 ({status}): {message}"
    if status == 404:
        return f"BAZE 모델 또는 주소를 찾을 수 없습니다. FINDYU_BAZE_MODEL·FINDYU_BAZE_BASE_URL을 확인하세요 ({status}): {message}"
    if status == 429:
        return f"BAZE 요청 한도를 초과했습니다 (재시도 후에도 실패, {status}): {message}"
    return f"BAZE API 오류 ({status}): {message}"


def extract_content(payload: dict) -> str | None:
    try:
        content = payload["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
    if isinstance(content, list):  # 일부 게이트웨이는 content part 배열로 준다
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str):
        return None
    text = content.strip()
    # 프롬프트 방식 응답처럼 ```json 코드 블록으로 감싼 경우도 허용
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text or None


class BazeAnalyzer:
    def __init__(self, http_client=None, sleep=time.sleep):
        # 테스트에서는 가짜 http client를 주입한다
        self._http = http_client
        self._sleep = sleep
        self._lock = threading.Lock()
        self._system_prompt = None

    def _get_http(self):
        if self._http is None:
            with self._lock:
                if self._http is None:
                    import httpx

                    timeout = float(os.getenv("FINDYU_BAZE_TIMEOUT", "") or DEFAULT_TIMEOUT)
                    self._http = httpx.Client(timeout=timeout)
        return self._http

    def _get_system_prompt(self):
        if self._system_prompt is None:
            self._system_prompt = ga.load_system_prompt()
        return self._system_prompt

    def _post(self, url: str, headers: dict, body: dict):
        """일시적 오류(408/429/5xx, 네트워크 오류)는 지수 backoff로 최대 RETRY_ATTEMPTS번 시도."""
        delay = RETRY_INITIAL_DELAY
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            last = attempt == RETRY_ATTEMPTS
            try:
                response = self._get_http().post(url, headers=headers, json=body)
            except Exception as exc:  # 네트워크 오류, 타임아웃 등
                if last:
                    raise AnalyzerError(
                        f"BAZE 호출 실패: {type(exc).__name__}: {exc}"
                    ) from exc
            else:
                if response.status_code < 400:
                    return response
                if response.status_code not in ga.RETRY_STATUS_CODES or last:
                    raise AnalyzerError(describe_http_error(response.status_code, response.text))
            logger.warning("BAZE 일시적 오류, %.0f초 후 재시도 (%d/%d)", delay, attempt, RETRY_ATTEMPTS)
            self._sleep(delay)
            delay = min(delay * 2, RETRY_MAX_DELAY)
        raise AssertionError("unreachable")

    def analyze(self, images: list[Image.Image]) -> dict:
        """사진 1장 이상 → 정규화된 등록 정보 dict (gemini_analyzer.normalize_result와 같은 형식)."""
        if not images:
            raise ValueError("분석할 사진이 없습니다.")
        if len(images) > ga.MAX_IMAGES:
            raise ValueError(f"사진은 최대 {ga.MAX_IMAGES}장까지 분석할 수 있습니다.")

        status = config_status()
        if not status["ready"]:
            raise AnalyzerConfigError(status["error"])

        model = baze_model()
        body = {
            "model": model,
            "messages": build_messages(self._get_system_prompt(), images),
            "response_format": response_format(),
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {os.environ['BAZE_API_KEY'].strip()}"}
        response = self._post(f"{baze_base_url()}/chat/completions", headers, body)

        try:
            payload = response.json()
        except ValueError as exc:
            raise AnalyzerError(f"BAZE 응답이 JSON이 아닙니다: {response.text[:300]}") from exc

        text = extract_content(payload)
        if not text:
            raise AnalyzerError(f"BAZE 응답이 비어 있습니다: {str(payload)[:300]}")

        result = ga.parse_response(_TextResponse(text))
        normalized = ga.normalize_result(result, image_count=len(images))
        normalized["model"] = model
        return normalized


class _TextResponse:
    """gemini_analyzer.parse_response가 text 경로로 pydantic 검증하도록 감싼다."""

    parsed = None

    def __init__(self, text: str):
        self.text = text
