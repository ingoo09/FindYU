"""
검색 비교에 보낼 후보 고르기 (요청당 최대 10건).

- 명세 순서 (공통 명세 4-2): 요청에 적은 장소와 일치 → 습득 시각이 가까운 순 → 등록 최신순(created_at, id)
  장소·시각을 입력하지 않았으면 그 기준은 건너뛴다.
- 사진 검색: 검색 사진과 저장된 사진 임베딩의 코사인 유사도 상위부터 고르고,
  임베딩이 없는 물품(수동 등록, 임베딩 실패, 다른 모델로 만든 임베딩)은 남은 자리를 명세 순서로 채운다.
  대표 사진을 읽을 수 없는 물품은 건너뛴다.
- 자연어 검색: 명세 순서로 고른다 (문장→사진 임베딩은 쓰지 않음).
"""

import json
import math
from datetime import datetime

from ai_retrieval import cosine_score

SOURCE_EMBEDDING = "embedding"
SOURCE_ORDER = "order"


def _norm(text) -> str:
    return "".join(str(text or "").lower().split())


def location_matches(query_location, item_location) -> bool:
    """부분 일치 (어느 쪽이 더 길어도 됨). "IT관" ↔ "IT관(E21)" """
    q, c = _norm(query_location), _norm(item_location)
    return bool(q and c and (q in c or c in q))


def spec_sort_key(item, query_location=None, query_time: datetime | None = None):
    location_rank = 0
    if query_location:
        location_rank = 0 if location_matches(query_location, item.location) else 1

    time_rank = 0.0
    if query_time is not None:
        if item.occurred_at is None:
            time_rank = math.inf
        else:
            time_rank = abs((item.occurred_at - query_time).total_seconds())

    created = item.created_at.timestamp() if item.created_at else float("-inf")
    return (location_rank, time_rank, -created, -(item.id or 0))


def spec_order(items, query_location=None, query_time=None) -> list:
    return sorted(items, key=lambda item: spec_sort_key(item, query_location, query_time))


def stored_embedding(item, model_id: str) -> list[float] | None:
    """같은 모델로 만든 임베딩만 쓴다 (mock 벡터와 Gemini 벡터를 섞지 않음)."""
    if not item.image_embedding_gemini or item.image_embedding_model != model_id:
        return None
    try:
        vector = json.loads(item.image_embedding_gemini)
    except (TypeError, ValueError):
        return None
    return vector if isinstance(vector, list) and vector else None


def image_search_order(items, query_vector, model_id, query_location=None, query_time=None):
    """
    [(item, source, score)] 전체 순서. 임베딩 있는 물품을 유사도 내림차순(같으면 명세 순서)으로 먼저,
    그다음 임베딩 없는 물품을 명세 순서로.
    """
    with_embedding, without = [], []
    for item in items:
        vector = stored_embedding(item, model_id)
        if vector is None:
            without.append(item)
        else:
            with_embedding.append((item, cosine_score(query_vector, vector)))

    with_embedding.sort(
        key=lambda pair: (-pair[1], spec_sort_key(pair[0], query_location, query_time))
    )
    ordered = [(item, SOURCE_EMBEDDING, score) for item, score in with_embedding]
    ordered += [(item, SOURCE_ORDER, None) for item in spec_order(without, query_location, query_time)]
    return ordered


def take_readable(ordered, load_image, limit: int, require_image: bool):
    """
    순서대로 대표 사진을 읽어 limit건을 채운다.
    require_image=True(사진 검색)면 사진을 읽을 수 없는 물품은 건너뛴다.
    반환: [(item, source, score, jpeg_bytes | None)]
    """
    selected = []
    for item, source, score in ordered:
        if len(selected) >= limit:
            break
        jpeg = load_image(item)
        if jpeg is None and require_image:
            continue
        selected.append((item, source, score, jpeg))
    return selected
