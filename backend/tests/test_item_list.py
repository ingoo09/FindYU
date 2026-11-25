from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import item_list as il
import models
from database import Base

T0 = datetime(2026, 11, 20, 9, 0, 0)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    rows = [
        # (id, item_type, category, location, status, 등록 시각(분))
        (1, "found", "스마트폰", "IT관(E21)", "registered", 0),
        (2, "found", "이어폰", "IT관 2층", "registered", 10),
        (3, "found", "지갑", "중앙도서관", "analyzing", 20),
        (4, "lost", "스마트폰", "IT관(E21)", "registered", 30),
        (5, "found", "스마트폰", "50%_할인 매장", "analysis_failed", 40),
        (6, "found", None, None, "registered", 50),
        (7, "found", "스마트폰", "  ", "registered", 50),  # 6과 같은 시각 → id로 정렬
    ]
    for item_id, item_type, category, location, status, minutes in rows:
        session.add(models.Item(
            id=item_id, item_type=item_type, category=category, location=location,
            status=status, created_at=T0 + timedelta(minutes=minutes),
        ))
    session.commit()
    yield session
    session.close()


def _ids(db, **kwargs):
    items, total = il.query_items(db, il.parse_list_query(**kwargs))
    return [item.id for item in items], total


def test_default_is_newest_first_all_items(db):
    ids, total = _ids(db)
    assert ids == [7, 6, 5, 4, 3, 2, 1]  # 같은 시각(6, 7)은 id 큰 것 먼저
    assert total == 7


def test_oldest_sort(db):
    assert _ids(db, sort="oldest")[0] == [1, 2, 3, 4, 5, 6, 7]


@pytest.mark.parametrize("kwargs, expected", [
    ({"item_type": "found"}, [7, 6, 5, 3, 2, 1]),
    ({"item_type": "lost"}, [4]),
    ({"category": "스마트폰"}, [7, 5, 4, 1]),
    ({"category": "모르겠음"}, [7, 6, 5, 4, 3, 2, 1]),  # 모르겠음 = 거르지 않음
    ({"status": "analyzing"}, [3]),
    ({"location": "IT관"}, [4, 2, 1]),               # 부분 일치
    ({"location": "it관"}, [4, 2, 1]),               # 영문 대소문자 무시
    ({"location": "50%_"}, [5]),                     # %, _는 글자 그대로
    ({"location": "%"}, [5]),
    ({"item_type": "found", "category": "스마트폰", "location": "IT관"}, [1]),
])
def test_filters(db, kwargs, expected):
    ids, total = _ids(db, **kwargs)
    assert ids == expected
    assert total == len(expected)


def test_pagination(db):
    q = il.parse_list_query(page="2", page_size="3")
    items, total = il.query_items(db, q)
    assert [i.id for i in items] == [4, 3, 2]
    assert il.page_info(q, total) == {
        "total": 7, "page": 2, "page_size": 3, "total_pages": 3, "has_next": True,
    }

    q = il.parse_list_query(page=3, page_size=3)
    items, total = il.query_items(db, q)
    assert [i.id for i in items] == [1]
    assert il.page_info(q, total)["has_next"] is False

    # 마지막 페이지를 넘으면 빈 목록 (오류 아님)
    q = il.parse_list_query(page=9, page_size=3)
    assert il.query_items(db, q) == ([], 7)


def test_empty_result_page_info():
    q = il.parse_list_query()
    assert il.page_info(q, 0) == {"total": 0, "page": 1, "page_size": 20, "total_pages": 0, "has_next": False}


def test_defaults_and_blank_values():
    q = il.parse_list_query(item_type="", category=" ", location="  ", status="", page="", page_size=None, sort="")
    assert q == il.ListQuery()
    assert q.applied_filters() == {}
    assert il.parse_list_query(item_type="found", location="IT관").applied_filters() == {
        "item_type": "found", "location": "IT관",
    }


@pytest.mark.parametrize("kwargs, message", [
    ({"item_type": "stolen"}, "item_type"),
    ({"category": "헤드폰"}, "category"),
    ({"status": "done"}, "status"),
    ({"sort": "score"}, "sort"),
    ({"page": "0"}, "page"),
    ({"page": "abc"}, "page"),
    ({"page_size": "0"}, "page_size"),
    ({"page_size": str(il.MAX_PAGE_SIZE + 1)}, "page_size"),
])
def test_invalid_values(kwargs, message):
    with pytest.raises(ValueError, match=message):
        il.parse_list_query(**kwargs)


def test_location_options(db):
    # 빈 장소(None, 공백)는 제외, 많은 순 → 이름순
    assert il.location_options(db) == [
        {"location": "IT관(E21)", "count": 2},
        {"location": "50%_할인 매장", "count": 1},
        {"location": "IT관 2층", "count": 1},
        {"location": "중앙도서관", "count": 1},
    ]
    assert il.location_options(db, "lost") == [{"location": "IT관(E21)", "count": 1}]
    with pytest.raises(ValueError):
        il.location_options(db, "stolen")


def test_statuses_match_main():
    """main.py의 상태 상수가 목록 필터 값과 같은 곳을 가리키는지 (main을 import하지 않고 소스로 확인)."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    for name in ("STATUS_ANALYZING", "STATUS_REGISTERED", "STATUS_ANALYSIS_FAILED"):
        assert f"{name} = item_list.{name}" in src
