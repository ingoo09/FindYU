"""
사진 검색용 이미지 임베딩 (FINDYU_SEARCH_ANALYZER_MODE=baze | mock).

- baze: 팩트챗(BAZE) 게이트웨이 POST /embeddings, model=gemini-embedding-2, dimensions=256
  - 사진은 {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}} 객체로 보낸다.
    data URL을 문자열 그대로 보내면 게이트웨이가 200을 주지만 사진이 아니라 base64 "글자"를 임베딩한다
    (2026-11-25 실험: 사진 1장 = 258토큰, 글자로 처리되면 18만 토큰).
    그래서 usage.prompt_tokens가 장당 MAX_TOKENS_PER_IMAGE를 넘으면 오류로 본다.
  - 재시도하지 않는다 (등록: 1회 시도 후 실패하면 null / 검색: 실패하면 502)
- mock: API 없이 사진 픽셀로 만든 결정적 벡터 (같은 사진 = 1.0). 테스트·개발용

환경변수
- BAZE_API_KEY, FINDYU_BAZE_BASE_URL: 등록 분석과 같은 값
- FINDYU_EMBEDDING_MODEL       기본 gemini-embedding-2
- FINDYU_EMBEDDING_DIMENSIONS  기본 256
- FINDYU_EMBEDDING_TIMEOUT     요청당 제한 시간(초), 기본 60
"""

import base64
import math
import os

from PIL import Image

import baze_analyzer
import gemini_analyzer
from gemini_analyzer import AnalyzerConfigError, AnalyzerError

DEFAULT_MODEL = "gemini-embedding-2"
DEFAULT_DIMENSIONS = 256
DEFAULT_TIMEOUT = 60.0
# 사진으로 처리되면 장당 258토큰. 여유를 두되, 글자로 처리된 경우(수만~수십만)는 확실히 걸러낸다
MAX_TOKENS_PER_IMAGE = 1000


class EmbeddingError(AnalyzerError):
    """임베딩 호출 실패 또는 응답 이상. API에서는 502로 돌려준다."""


def embedding_model() -> str:
    return os.getenv("FINDYU_EMBEDDING_MODEL", "").strip() or DEFAULT_MODEL


def embedding_dimensions() -> int:
    try:
        return int(os.getenv("FINDYU_EMBEDDING_DIMENSIONS", "").strip() or DEFAULT_DIMENSIONS)
    except ValueError:
        return DEFAULT_DIMENSIONS


def image_part(image: Image.Image) -> dict:
    """등록 분석과 같은 전처리(긴 변 1024px JPEG, 메타데이터 제거) 후 image_url 객체로."""
    data = base64.b64encode(gemini_analyzer.encode_image(image)).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}


class GatewayEmbedder:
    """BAZE 게이트웨이 /embeddings. model_id는 DB에 같이 저장해 다른 모델 벡터와 섞지 않는다."""

    def __init__(self, http_client=None):
        self._http = http_client

    @property
    def model_id(self) -> str:
        return f"{embedding_model()}@{embedding_dimensions()}"

    def _client(self):
        if self._http is None:
            import httpx

            timeout = float(os.getenv("FINDYU_EMBEDDING_TIMEOUT", "") or DEFAULT_TIMEOUT)
            self._http = httpx.Client(timeout=timeout)
        return self._http

    def embed_images(self, images: list[Image.Image]) -> list[list[float]]:
        if not images:
            return []
        api_key = os.getenv("BAZE_API_KEY", "").strip()
        if not api_key:
            raise AnalyzerConfigError(baze_analyzer.config_error_message(["BAZE_API_KEY"]))

        dims = embedding_dimensions()
        body = {
            "model": embedding_model(),
            "input": [image_part(image) for image in images],
            "dimensions": dims,
        }
        try:
            response = self._client().post(
                f"{baze_analyzer.baze_base_url()}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
        except Exception as exc:  # 네트워크 오류, 시간 초과
            raise EmbeddingError(f"임베딩 호출 실패: {type(exc).__name__}: {exc}") from exc

        if response.status_code >= 400:
            raise EmbeddingError(
                f"임베딩 API 오류 ({response.status_code}): {response.text.strip()[:300]}"
            )
        try:
            payload = response.json()
            rows = sorted(payload["data"], key=lambda row: row.get("index", 0))
            vectors = [[float(v) for v in row["embedding"]] for row in rows]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError(f"임베딩 응답 형식이 다릅니다: {response.text[:300]}") from exc

        if len(vectors) != len(images):
            raise EmbeddingError(f"임베딩 개수가 다릅니다 (보냄 {len(images)}, 받음 {len(vectors)})")
        if any(len(v) != dims for v in vectors):
            raise EmbeddingError(f"임베딩 차원이 {dims}이 아닙니다: {sorted({len(v) for v in vectors})}")

        tokens = (payload.get("usage") or {}).get("prompt_tokens")
        if tokens is not None and tokens / len(images) > MAX_TOKENS_PER_IMAGE:
            raise EmbeddingError(
                f"사진이 이미지가 아니라 글자로 처리된 것으로 보입니다 "
                f"(장당 {tokens / len(images):.0f}토큰, 기준 {MAX_TOKENS_PER_IMAGE} 이하)"
            )
        return vectors


class MockEmbedder:
    """API 호출 없음. 사진을 16x16 흑백으로 줄인 픽셀값 (평균을 빼고 정규화). 같은 사진이면 1.0."""

    model_id = "mock-pixels@256"

    def __init__(self):
        self.calls = 0

    def embed_images(self, images: list[Image.Image]) -> list[list[float]]:
        self.calls += 1
        vectors = []
        for image in images:
            pixels = list(image.convert("L").resize((16, 16)).tobytes())
            mean = sum(pixels) / len(pixels)
            centered = [p - mean for p in pixels]
            norm = math.sqrt(sum(v * v for v in centered)) or 1.0
            vectors.append([v / norm for v in centered])
        return vectors


def make_embedder(mode: str):
    if mode == "baze":
        return GatewayEmbedder()
    if mode == "mock":
        return MockEmbedder()
    return None  # local: 기존 DINOv2 경로
