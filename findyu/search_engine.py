class SearchEngine:
    """
    검색 알고리즘만 담당한다.

    LangGraph의 존재를 전혀 모르게 만들어
    workflow와 실제 retrieval 로직을 분리한다.
    """

    def __init__(
        self,
        config,
        parser,
        vector_store,
        metadata,
        ranker,
    ):
        self.cfg = config

        self.parser = parser
        self.vector_store = (
            vector_store
        )
        self.metadata = metadata
        self.ranker = ranker

    def parse(self, query):
        return self.parser.parse(
            query
        )

    def image_search(
        self,
        image_path,
    ):
        return (
            self.vector_store
            .search_image(
                image_path
            )
        )

    def text_search(
        self,
        text,
    ):
        return (
            self.vector_store
            .search_text(
                text
            )
        )

    @staticmethod
    def merge_candidates(
        image_scores,
        text_scores,
    ):
        return list(
            set(image_scores)
            | set(text_scores)
        )

    def metadata_scores(
        self,
        candidate_ids,
        location,
        time,
    ):
        location_scores = (
            self.metadata
            .location_scores(
                location,
                candidate_ids,
            )
            if location
            else {}
        )

        time_scores = (
            self.metadata
            .time_scores(
                time,
                candidate_ids,
            )
            if time
            else {}
        )

        return (
            location_scores,
            time_scores,
        )

    def rank(self, state):
        return (
            self.ranker.rank(
                candidate_ids=
                    state.get(
                        "candidate_ids",
                        [],
                    ),

                image_scores=
                    state.get(
                        "image_scores",
                        {},
                    ),

                text_scores=
                    state.get(
                        "text_scores",
                        {},
                    ),

                location_scores=
                    state.get(
                        "location_scores",
                        {},
                    ),

                time_scores=
                    state.get(
                        "time_scores",
                        {},
                    ),
            )
        )

    def result_is_sufficient(
        self,
        results,
        retry_count,
    ):
        if (
            retry_count
            >= self.cfg.max_retry
        ):
            return True

        if not results:
            return False

        return (
            float(
                results[0]["score"]
            )
            >= self.cfg.min_score
        )
