import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import search_candidates as sc

T0 = datetime(2026, 11, 20, 12, 0)
MODEL = "mock-pixels@256"


def _item(item_id, location=None, occurred=None, created=0, vector=None, model=MODEL):
    return SimpleNamespace(
        id=item_id, location=location,
        occurred_at=T0 + timedelta(hours=occurred) if occurred is not None else None,
        created_at=T0 + timedelta(minutes=created),
        image_embedding_gemini=json.dumps(vector) if vector is not None else None,
        image_embedding_model=model if vector is not None else None,
    )


def _ids(items):
    return [i.id for i in items]


def test_spec_order_newest_when_no_location_or_time():
    items = [_item(1, created=0), _item(2, created=5), _item(3, created=5)]
    assert _ids(sc.spec_order(items)) == [3, 2, 1]  # 같은 시각이면 id 큰 것 먼저


def test_spec_order_location_then_time_then_newest():
    items = [
        _item(1, "IT관(E21)", occurred=-5, created=0),
        _item(2, "중앙도서관", occurred=0, created=9),
        _item(3, "IT관 2층", occurred=-1, created=1),
        _item(4, "it관", occurred=None, created=8),
        _item(5, None, occurred=0, created=7),
    ]
    ordered = sc.spec_order(items, query_location="IT관", query_time=T0)
    # 장소 일치(1,3,4) 중 시각이 가까운 순(3: 1시간, 1: 5시간, 4: 시각 없음) → 불일치(2, 5)는 시각 같음 → 최신순
    assert _ids(ordered) == [3, 1, 4, 2, 5]


def test_location_matches_both_directions():
    assert sc.location_matches("IT관", "IT관(E21)")
    assert sc.location_matches("IT관(E21) 1층", "IT관(E21)")
    assert not sc.location_matches("IT관", None)
    assert not sc.location_matches(None, "IT관")


def test_image_order_embeddings_first_then_spec_order():
    items = [
        _item(1, vector=[1.0, 0.0], created=0),
        _item(2, vector=[0.6, 0.8], created=1),
        _item(3, created=9),                                  # 임베딩 없음 (수동 등록·실패)
        _item(4, vector=[1.0, 0.0], model="gemini-embedding-2@256", created=8),  # 다른 모델 → 없음 취급
        _item(5, vector=[0.0, 1.0], created=2),
    ]
    ordered = sc.image_search_order(items, [1.0, 0.0], MODEL)
    assert [(i.id, src) for i, src, _ in ordered] == [
        (1, "embedding"), (2, "embedding"), (5, "embedding"), (3, "order"), (4, "order"),
    ]
    assert ordered[0][2] == 1.0 and ordered[3][2] is None


def test_take_readable_skips_unreadable_only_for_image_search():
    ordered = [(_item(i), "order", None) for i in (1, 2, 3, 4)]
    load = lambda item: None if item.id == 2 else b"jpeg"
    picked = sc.take_readable(ordered, load, limit=2, require_image=True)
    assert [(i.id, j) for i, _s, _sc, j in picked] == [(1, b"jpeg"), (3, b"jpeg")]
    picked = sc.take_readable(ordered, load, limit=2, require_image=False)
    assert [(i.id, j) for i, _s, _sc, j in picked] == [(1, b"jpeg"), (2, None)]


def test_broken_stored_embedding_is_ignored():
    item = _item(1, vector=[1.0])
    item.image_embedding_gemini = "not json"
    assert sc.stored_embedding(item, MODEL) is None
