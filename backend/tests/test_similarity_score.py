from types import SimpleNamespace

import pytest

from ai_retrieval import cosine_score
from search_graph import run_search_graph


@pytest.mark.parametrize("a, b, expected", [
    ([1, 0], [1, 0], 1.0),            # 같은 방향
    ([1, 0], [0, 1], 0.0),            # 직교 = 관련 없음 → 0 (예전 변환이면 0.5)
    ([1, 0], [-1, 0], 0.0),           # 반대 방향도 0
    ([3, 4], [6, 8], 1.0),            # 정규화되지 않은 벡터도 코사인으로 계산
    ([1, 1], [1, 0], 2 ** -0.5),
    ([], [1], 0.0),
    ([1, 0], [1, 0, 0], 0.0),         # 차원이 다르면 0
    ([0, 0], [1, 0], 0.0),            # 영벡터
])
def test_cosine_score_is_plain_cosine_clipped(a, b, expected):
    assert cosine_score(a, b) == pytest.approx(expected)


def _run(items, image_scores=None, text_scores=None, locations=None, query_location=None):
    image_scores = image_scores or {}
    text_scores = text_scores or {}
    return run_search_graph(
        candidates=items,
        query_image_embedding=[1.0] if image_scores else None,
        query_text_embedding=[1.0] if text_scores else None,
        get_candidate_image_embedding=lambda item, _q: image_scores[item.id],
        get_candidate_text_image_embedding=lambda item, _q: text_scores[item.id],
        location_score_fn=lambda _q, loc: (locations or {}).get(loc, 0.0),
        time_score_fn=lambda _q, _t: None,
        serialize_fn=lambda item: {"id": item.id},
        query_location=query_location,
        query_time=None,
        top_k=5,
    )["results"]


def _items(*ids):
    return [SimpleNamespace(id=i, location=f"loc{i}", occurred_at=None) for i in ids]


def test_results_have_similarity_score_sorted_desc():
    results = _run(_items(1, 2, 3), image_scores={1: 0.2, 2: 0.9, 3: 0.5})
    assert [r["id"] for r in results] == [2, 3, 1]
    assert [r["similarity_score"] for r in results] == [0.9, 0.5, 0.2]
    # 이전 이름은 같은 값으로 남겨 둔다 (프론트 전환 전까지)
    for r in results:
        assert r["matching_score"] == r["similarity"] == r["similarity_score"]


def test_weighted_score_uses_present_components_only():
    # 이미지 0.45, 텍스트 0.25 → (0.45*0.8 + 0.25*0.2) / 0.7
    results = _run(_items(1), image_scores={1: 0.8}, text_scores={1: 0.2})
    assert results[0]["similarity_score"] == pytest.approx((0.45 * 0.8 + 0.25 * 0.2) / 0.7, abs=1e-4)
    assert results[0]["image_similarity"] == 0.8
    assert results[0]["text_similarity"] == 0.2
    assert results[0]["location_score"] is None
