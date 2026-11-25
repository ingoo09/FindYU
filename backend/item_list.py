"""
물품 목록 조회 (GET /items): 필터 + 최신순 정렬 + 페이지 나누기.

통합 Dashboard의 "전체 습득물 최신순 목록, 장소·품목 필터"용.
DB 쿼리만 다루고 응답 직렬화는 main.serialize_item이 한다.
"""

from dataclasses import dataclass

from sqlalchemy import func

import check_form
import models

# 물품 상태 (main.py와 분석 작업이 같은 값을 쓴다)
STATUS_ANALYZING = "analyzing"
STATUS_REGISTERED = "registered"
STATUS_ANALYSIS_FAILED = "analysis_failed"
STATUSES = (STATUS_ANALYZING, STATUS_REGISTERED, STATUS_ANALYSIS_FAILED)

ITEM_TYPES = ("found", "lost")
SORTS = ("newest", "oldest")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class ListQuery:
    item_type: str | None = None
    category: str | None = None
    location: str | None = None
    status: str | None = None
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    sort: str = "newest"

    def applied_filters(self) -> dict:
        return {
            key: value
            for key, value in (
                ("item_type", self.item_type),
                ("category", self.category),
                ("location", self.location),
                ("status", self.status),
            )
            if value is not None
        }


def _blank_to_none(value):
    text = (value or "").strip()
    return text or None


def _parse_int(value, name: str, default: int) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{name}는 정수여야 합니다.") from exc


def parse_list_query(
    item_type=None, category=None, location=None, status=None, page=None, page_size=None, sort=None
) -> ListQuery:
    """쿼리 문자열 → ListQuery. 잘못된 값은 ValueError (API에서 400)."""
    item_type = _blank_to_none(item_type)
    if item_type is not None and item_type not in ITEM_TYPES:
        raise ValueError(f"item_type은 {', '.join(ITEM_TYPES)} 중 하나여야 합니다.")

    status = _blank_to_none(status)
    if status is not None and status not in STATUSES:
        raise ValueError(f"status는 {', '.join(STATUSES)} 중 하나여야 합니다.")

    sort = _blank_to_none(sort) or "newest"
    if sort not in SORTS:
        raise ValueError(f"sort는 {', '.join(SORTS)} 중 하나여야 합니다.")

    page = _parse_int(page, "page", 1)
    if page < 1:
        raise ValueError("page는 1 이상이어야 합니다.")
    page_size = _parse_int(page_size, "page_size", DEFAULT_PAGE_SIZE)
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size는 1~{MAX_PAGE_SIZE} 사이여야 합니다.")

    return ListQuery(
        item_type=item_type,
        # 체크 폼과 같은 품목 값. "모르겠음"이면 거르지 않음
        category=check_form.validate_category(category),
        location=_blank_to_none(location),
        status=status,
        page=page,
        page_size=page_size,
        sort=sort,
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered(db, q: ListQuery):
    query = db.query(models.Item)
    if q.item_type:
        query = query.filter(models.Item.item_type == q.item_type)
    if q.category:
        query = query.filter(models.Item.category == q.category)
    if q.status:
        query = query.filter(models.Item.status == q.status)
    if q.location:
        # 장소는 자유 입력이라 부분 일치 ("IT관" → "IT관(E21)", "IT관 2층")
        query = query.filter(
            models.Item.location.ilike(f"%{_escape_like(q.location)}%", escape="\\")
        )
    return query


def query_items(db, q: ListQuery) -> tuple[list, int]:
    """(현재 페이지 물품, 필터 후 전체 개수). 등록 시각이 같으면 id로 순서를 고정한다."""
    query = _filtered(db, q)
    total = query.count()
    if q.sort == "newest":
        order = (models.Item.created_at.desc(), models.Item.id.desc())
    else:
        order = (models.Item.created_at.asc(), models.Item.id.asc())
    items = (
        query.order_by(*order)
        .offset((q.page - 1) * q.page_size)
        .limit(q.page_size)
        .all()
    )
    return items, total


def page_info(q: ListQuery, total: int) -> dict:
    total_pages = (total + q.page_size - 1) // q.page_size
    return {
        "total": total,
        "page": q.page,
        "page_size": q.page_size,
        "total_pages": total_pages,
        "has_next": q.page < total_pages,
    }


def location_options(db, item_type: str | None = None) -> list[dict]:
    """장소 필터 선택지: 등록된 장소와 물품 수 (많은 순, 같으면 이름순). 빈 장소는 제외."""
    item_type = _blank_to_none(item_type)
    if item_type is not None and item_type not in ITEM_TYPES:
        raise ValueError(f"item_type은 {', '.join(ITEM_TYPES)} 중 하나여야 합니다.")

    location = func.trim(models.Item.location)
    query = db.query(location, func.count(models.Item.id)).filter(location != "")
    if item_type:
        query = query.filter(models.Item.item_type == item_type)
    rows = query.group_by(location).all()
    rows.sort(key=lambda row: (-row[1], row[0]))
    return [{"location": name, "count": count} for name, count in rows]
