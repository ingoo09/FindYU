from langgraph.graph import (
    StateGraph,
    START,
    END,
)
from langgraph.checkpoint.memory import (
    InMemorySaver,
)
from langgraph.types import (
    interrupt,
)

from .states import (
    SearchState,
    RegistrationState,
)


class FindYUWorkflow:
    """
    LangGraph orchestration만 담당.

    검색 모델, FAISS 구현, ranking 계산은
    SearchEngine / RegistrationService가 담당한다.
    """

    def __init__(
        self,
        search_engine,
        registration_service,
    ):
        self.search_engine = (
            search_engine
        )

        self.registration_service = (
            registration_service
        )

        self.search_graph = (
            self._build_search_graph()
        )

        self.registration_graph = (
            self._build_registration_graph()
        )

    # ==========================================
    # Search nodes
    # ==========================================

    def _parse(self, state):
        parsed = (
            self.search_engine
            .parse(
                state["query"]
            )
        )

        return {
            "text":
                parsed.get("text"),

            "location":
                parsed.get("location"),

            "time":
                parsed.get("time"),

            "retry_count":
                state.get(
                    "retry_count",
                    0,
                ),
        }

    def _image_search(
        self,
        state,
    ):
        return {
            "image_scores":
                self.search_engine
                .image_search(
                    state.get(
                        "image_path"
                    )
                )
        }

    def _text_search(
        self,
        state,
    ):
        return {
            "text_scores":
                self.search_engine
                .text_search(
                    state.get(
                        "text"
                    )
                )
        }

    def _merge(
        self,
        state,
    ):
        candidates = (
            self.search_engine
            .merge_candidates(
                state.get(
                    "image_scores",
                    {},
                ),
                state.get(
                    "text_scores",
                    {},
                ),
            )
        )

        return {
            "candidate_ids":
                candidates
        }

    def _metadata(
        self,
        state,
    ):
        location_scores, time_scores = (
            self.search_engine
            .metadata_scores(
                state.get(
                    "candidate_ids",
                    [],
                ),
                state.get(
                    "location"
                ),
                state.get(
                    "time"
                ),
            )
        )

        return {
            "location_scores":
                location_scores,

            "time_scores":
                time_scores,
        }

    def _rank(
        self,
        state,
    ):
        return {
            "results":
                self.search_engine
                .rank(state)
        }

    def _route_result(
        self,
        state,
    ):
        sufficient = (
            self.search_engine
            .result_is_sufficient(
                state.get(
                    "results",
                    [],
                ),
                state.get(
                    "retry_count",
                    0,
                ),
            )
        )

        return (
            "done"
            if sufficient
            else "ask_user"
        )

    def _ask_user(
        self,
        state,
    ):
        # 여기서 LangGraph 실행이 일시정지된다.
        user_input = interrupt({
            "message":
                "검색 결과가 충분하지 않습니다. "
                "추가 설명이나 사진을 입력해주세요.",

            "can_add": [
                "text",
                "image",
            ],
        })

        if user_input.get(
            "stop",
            False,
        ):
            return {
                "stop": True
            }

        old_query = (
            state.get(
                "query",
                "",
            )
            or ""
        ).strip()

        extra_text = (
            user_input.get(
                "text",
                "",
            )
            or ""
        ).strip()

        new_query = " ".join(
            x
            for x
            in [
                old_query,
                extra_text,
            ]
            if x
        )

        update = {
            "query":
                new_query,

            "retry_count":
                state.get(
                    "retry_count",
                    0,
                ) + 1,

            "stop":
                False,
        }

        # 사용자가 loop에서 새 사진을 넣으면
        # 다음 검색부터 새 이미지가 사용된다.
        if user_input.get(
            "image_path"
        ):
            update[
                "image_path"
            ] = user_input[
                "image_path"
            ]

        return update

    @staticmethod
    def _route_after_user(
        state,
    ):
        return (
            "done"
            if state.get("stop")
            else "retry"
        )

    def _build_search_graph(
        self,
    ):
        graph = StateGraph(
            SearchState
        )

        graph.add_node(
            "parse",
            self._parse,
        )

        graph.add_node(
            "image_search",
            self._image_search,
        )

        graph.add_node(
            "text_search",
            self._text_search,
        )

        graph.add_node(
            "merge",
            self._merge,
        )

        graph.add_node(
            "metadata",
            self._metadata,
        )

        graph.add_node(
            "rank",
            self._rank,
        )

        graph.add_node(
            "ask_user",
            self._ask_user,
        )

        graph.add_edge(
            START,
            "parse",
        )

        graph.add_edge(
            "parse",
            "image_search",
        )

        graph.add_edge(
            "image_search",
            "text_search",
        )

        graph.add_edge(
            "text_search",
            "merge",
        )

        graph.add_edge(
            "merge",
            "metadata",
        )

        graph.add_edge(
            "metadata",
            "rank",
        )

        graph.add_conditional_edges(
            "rank",
            self._route_result,
            {
                "done":
                    END,

                "ask_user":
                    "ask_user",
            },
        )

        # 추가 입력을 받으면 parse부터 다시 실행.
        graph.add_conditional_edges(
            "ask_user",
            self._route_after_user,
            {
                "done":
                    END,

                "retry":
                    "parse",
            },
        )

        return graph.compile(
            checkpointer=
                InMemorySaver()
        )

    # ==========================================
    # Registration nodes
    # ==========================================

    def _analyze_image(
        self,
        state,
    ):
        return {
            "attributes":
                self.registration_service
                .analyze_image(
                    state[
                        "image_path"
                    ]
                )
        }

    def _save_item(
        self,
        state,
    ):
        item_id = (
            self.registration_service
            .save(
                image_path=
                    state[
                        "image_path"
                    ],

                location=
                    state[
                        "location"
                    ],

                found_time=
                    state[
                        "found_time"
                    ],

                attributes=
                    state[
                        "attributes"
                    ],
            )
        )

        return {
            "item_id":
                item_id
        }

    def _build_registration_graph(
        self,
    ):
        graph = StateGraph(
            RegistrationState
        )

        graph.add_node(
            "analyze_image",
            self._analyze_image,
        )

        graph.add_node(
            "save",
            self._save_item,
        )

        graph.add_edge(
            START,
            "analyze_image",
        )

        graph.add_edge(
            "analyze_image",
            "save",
        )

        graph.add_edge(
            "save",
            END,
        )

        return graph.compile()
