"""
검색 비교 어댑터 연결부 (백엔드 소유). 실제 비교는 AI 담당의 backend/search_analyzer.py가 한다.

백엔드가 후보를 최대 10건으로 좁힌 뒤, 검색 입력과 후보 묶음을 Gemini 비교 한 번에 넘긴다.
모델은 입력 후보 ID의 순서와 짧은 근거만 돌려주고, 백엔드가 ID를 검증해 DB 레코드와 붙인다.

AI 담당이 구현할 함수 (docs/REQUESTS.md 2026-11-25 요청 참고)

    # backend/search_analyzer.py
    def compare(query: dict, candidates: list[dict]) -> dict:
        '''{"results": [{"id": 12, "match_reasons": ["..."]}, ...]}  배열 순서 = 순위'''

    - query: {"kind": "image"|"text", "text": str|None, "image_jpeg": bytes|None,
              "location": str|None, "occurred_at": "YYYY-MM-DDTHH:MM"|None}
    - candidates: [{"id": int, "category": str|None, "description": str|None,
                    "form_values": {..체크 폼 값..}, "location": str|None,
                    "occurred_at": str|None, "image_jpeg": bytes|None}, ...]  (최대 10건)
    - image_jpeg는 긴 변 1024px JPEG 바이트(EXIF 회전 반영, 메타데이터 제거). 파일 경로·URL은 보내지 않는다
    - 실패는 gemini_analyzer.AnalyzerError(호출·응답 오류, API 502) /
      AnalyzerConfigError(키·설정 없음, API 503)로 올린다

FINDYU_SEARCH_ANALYZER_MODE
- mock : API 호출 없음. 받은 후보 순서를 그대로 순위로, match_reasons는 빈 배열
- baze : search_analyzer.compare 호출 (모듈이 아직 없으면 503)
- local: 이 어댑터를 쓰지 않는 기존 DINOv2·SigLIP2 검색 (main.py)
"""

import importlib
import io
from dataclasses import asdict, dataclass, field

from PIL import Image

import gemini_analyzer
from gemini_analyzer import AnalyzerConfigError, AnalyzerError

MAX_CANDIDATES = 10
MAX_REASONS = 3
MAX_REASON_LENGTH = 200
ANALYZER_MODULE = "search_analyzer"


class AdapterOutputError(AnalyzerError):
    """어댑터(모델)가 계약과 다른 결과를 냄. API에서는 502."""


@dataclass
class SearchQuery:
    kind: str                        # "image" | "text"
    text: str | None = None
    image_jpeg: bytes | None = None
    location: str | None = None
    occurred_at: str | None = None


@dataclass
class SearchCandidate:
    id: int
    category: str | None = None
    description: str | None = None
    form_values: dict = field(default_factory=dict)
    location: str | None = None
    occurred_at: str | None = None
    image_jpeg: bytes | None = None


def to_jpeg(image: Image.Image) -> bytes:
    """등록 분석·임베딩과 같은 전처리."""
    return gemini_analyzer.encode_image(image)


def jpeg_to_image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def _mock_compare(query: dict, candidates: list[dict]) -> dict:
    return {"results": [{"id": c["id"], "match_reasons": []} for c in candidates]}


def _load_analyzer():
    try:
        module = importlib.import_module(ANALYZER_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != ANALYZER_MODULE:
            raise
        raise AnalyzerConfigError(
            "검색 비교 어댑터(backend/search_analyzer.py)가 아직 없습니다. "
            "AI 담당 작업 전에는 FINDYU_SEARCH_ANALYZER_MODE=mock으로 실행하세요."
        ) from exc
    if not callable(getattr(module, "compare", None)):
        raise AnalyzerConfigError("backend/search_analyzer.py에 compare(query, candidates) 함수가 없습니다.")
    return module


def compare(mode: str, query: SearchQuery, candidates: list[SearchCandidate]) -> list[dict]:
    """
    후보를 비교해 검증된 [{"id", "match_reasons"}]를 순위 순서로 돌려준다.
    후보가 없으면 호출하지 않는다.
    """
    if not candidates:
        return []
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError(f"후보는 최대 {MAX_CANDIDATES}건까지 비교합니다.")

    query_dict = asdict(query)
    candidate_dicts = [asdict(c) for c in candidates]
    if mode == "mock":
        raw = _mock_compare(query_dict, candidate_dicts)
    elif mode == "baze":
        raw = _load_analyzer().compare(query_dict, candidate_dicts)
    else:
        raise ValueError(f"검색 어댑터 모드가 아닙니다: {mode}")
    return validate_results(raw, [c.id for c in candidates])


def validate_results(raw, sent_ids: list[int]) -> list[dict]:
    """
    모델 출력 검사: 형식, 정수 ID, 보낸 후보에 있는 ID, 중복 없음.
    하나라도 어긋나면 전체를 실패로 본다 (일부만 버리면 순위를 믿을 수 없으므로).
    보낸 후보 중 일부만 돌려주는 것은 허용한다 (모델이 관련 없다고 본 후보).
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
        raise AdapterOutputError(f"검색 비교 결과 형식이 다릅니다: {str(raw)[:200]}")

    allowed = set(sent_ids)
    seen = set()
    results = []
    for row in raw["results"]:
        if not isinstance(row, dict):
            raise AdapterOutputError(f"검색 비교 결과 항목 형식이 다릅니다: {str(row)[:200]}")
        item_id = row.get("id")
        if isinstance(item_id, bool) or not isinstance(item_id, int):
            raise AdapterOutputError(f"후보 ID가 정수가 아닙니다: {item_id!r}")
        if item_id not in allowed:
            raise AdapterOutputError(f"보내지 않은 후보 ID가 있습니다: {item_id}")
        if item_id in seen:
            raise AdapterOutputError(f"후보 ID가 중복됐습니다: {item_id}")
        seen.add(item_id)

        reasons = row.get("match_reasons", [])
        if reasons is None:
            reasons = []
        if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
            raise AdapterOutputError(f"match_reasons는 문자열 배열이어야 합니다: {str(reasons)[:200]}")
        cleaned = [r.strip()[:MAX_REASON_LENGTH] for r in reasons if r and r.strip()]
        results.append({"id": item_id, "match_reasons": cleaned[:MAX_REASONS]})
    return results
