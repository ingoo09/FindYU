"""
AI 브랜치의 LangGraph 검색 흐름을 현재 FastAPI/SQLite 데모에 맞게 단순화한 adapter.

원본 AI 브랜치:
parse -> image_search -> text_search -> merge -> metadata -> rank

중간 데모:
이미 description/location/time이 각각 API 필드로 들어오므로 parse는 생략하고,
DINOv2 / SigLIP2 / metadata / deterministic rank를 LangGraph로 orchestration한다.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class DemoSearchState(TypedDict, total=False):
    image_scores: dict[int, float]
    text_scores: dict[int, float]
    location_scores: dict[int, float]
    time_scores: dict[int, float]
    results: list[dict]


def run_search_graph(
    *,
    candidates,
    query_image_embedding,
    query_text_embedding,
    get_candidate_image_embedding,
    get_candidate_text_image_embedding,
    location_score_fn,
    time_score_fn,
    serialize_fn,
    query_location,
    query_time,
    top_k,
    weights=None,
):
    """
    현재 request의 후보 집합을 closure로 캡처하여 작은 LangGraph를 실행한다.
    DB/ORM 구조를 AI 브랜치의 파일 기반 DB로 강제 변환하지 않기 위한 통합 layer다.
    """
    weights = weights or {
        "image": 0.45,
        "text": 0.25,
        "location": 0.20,
        "time": 0.10,
    }

    def image_search(_state):
        if query_image_embedding is None:
            return {"image_scores": {}}

        return {
            "image_scores": {
                item.id: get_candidate_image_embedding(
                    item, query_image_embedding
                )
                for item in candidates
            }
        }

    def text_search(_state):
        if query_text_embedding is None:
            return {"text_scores": {}}

        return {
            "text_scores": {
                item.id: get_candidate_text_image_embedding(
                    item, query_text_embedding
                )
                for item in candidates
            }
        }

    def metadata(_state):
        return {
            "location_scores": {
                item.id: location_score_fn(query_location, item.location)
                for item in candidates
            }
            if query_location
            else {},
            "time_scores": {
                item.id: time_score_fn(query_time, item.occurred_at)
                for item in candidates
            }
            if query_time is not None
            else {},
        }

    def rank(state):
        results = []

        for item in candidates:
            components = {
                "image": state.get("image_scores", {}).get(item.id),
                "text": state.get("text_scores", {}).get(item.id),
                "location": state.get("location_scores", {}).get(item.id),
                "time": state.get("time_scores", {}).get(item.id),
            }

            present = [
                (weights[name], score)
                for name, score in components.items()
                if score is not None
            ]

            if present:
                total_weight = sum(weight for weight, _ in present)
                final_score = sum(
                    weight * score for weight, score in present
                ) / total_weight
            else:
                final_score = 0.0

            results.append(
                {
                    **serialize_fn(item),
                    "image_similarity": (
                        round(components["image"], 4)
                        if components["image"] is not None
                        else None
                    ),
                    "text_similarity": (
                        round(components["text"], 4)
                        if components["text"] is not None
                        else None
                    ),
                    "location_score": (
                        round(components["location"], 4)
                        if components["location"] is not None
                        else None
                    ),
                    "time_score": (
                        round(components["time"], 4)
                        if components["time"] is not None
                        else None
                    ),
                    "matching_score": round(final_score, 4),
                    "similarity": round(final_score, 4),
                    "scoring_mode": "dinov2+siglip2+metadata+langgraph",
                }
            )

        results.sort(key=lambda row: row["matching_score"], reverse=True)
        return {"results": results[:top_k]}

    graph = StateGraph(DemoSearchState)
    graph.add_node("image_search", image_search)
    graph.add_node("text_search", text_search)
    graph.add_node("metadata", metadata)
    graph.add_node("rank", rank)

    graph.add_edge(START, "image_search")
    graph.add_edge("image_search", "text_search")
    graph.add_edge("text_search", "metadata")
    graph.add_edge("metadata", "rank")
    graph.add_edge("rank", END)

    return graph.compile().invoke({})
