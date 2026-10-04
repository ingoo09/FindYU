from typing import (
    TypedDict,
    Optional,
)


class SearchState(
    TypedDict,
    total=False,
):
    query: str
    image_path: Optional[str]

    text: Optional[str]
    location: Optional[str]
    time: Optional[str]

    image_scores: dict[str, float]
    text_scores: dict[str, float]

    candidate_ids: list[str]

    location_scores: dict[str, float]
    time_scores: dict[str, float]

    results: list[dict]

    retry_count: int
    stop: bool


class RegistrationState(
    TypedDict,
    total=False,
):
    image_path: str
    location: str
    found_time: str

    attributes: dict
    item_id: str
