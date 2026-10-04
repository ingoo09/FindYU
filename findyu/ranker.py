class Ranker:
    """
    Image / Text / Location / Time score를
    하나의 final score로 합친다.
    """

    def __init__(self, config):
        self.cfg = config

    def rank(
        self,
        candidate_ids,
        image_scores,
        text_scores,
        location_scores,
        time_scores,
    ):
        results = []

        for item_id in candidate_ids:
            components = {
                "image": float(
                    image_scores.get(
                        item_id,
                        0.0,
                    )
                ),
                "text": float(
                    text_scores.get(
                        item_id,
                        0.0,
                    )
                ),
                "location": float(
                    location_scores.get(
                        item_id,
                        0.0,
                    )
                ),
                "time": float(
                    time_scores.get(
                        item_id,
                        0.0,
                    )
                ),
            }

            final_score = sum(
                self.cfg.weights[key]
                * components[key]
                for key
                in self.cfg.weights
            )

            results.append({
                "item_id":
                    item_id,

                "score":
                    float(final_score),

                **components,
            })

        results.sort(
            key=lambda x:
                x["score"],
            reverse=True,
        )

        return results[
            :self.cfg.result_k
        ]
