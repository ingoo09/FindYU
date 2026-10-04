import math
import re
from difflib import SequenceMatcher

import pandas as pd


class MetadataRepository:
    """
    metadata.csv 읽기/쓰기와
    location/time score 계산을 담당한다.
    """

    def __init__(
        self,
        metadata_path,
        config,
    ):
        self.path = metadata_path
        self.cfg = config

        if not self.path.exists():
            pd.DataFrame(
                columns=[
                    "item_id",
                    "location",
                    "found_time",
                ]
            ).to_csv(
                self.path,
                index=False,
            )

    def load(self):
        return pd.read_csv(
            self.path
        )

    def upsert(
        self,
        item_id,
        location,
        found_time,
    ):
        df = self.load()

        mask = (
            df["item_id"]
            .astype(str)
            == str(item_id)
        )

        if mask.any():
            df.loc[
                mask,
                ["location", "found_time"],
            ] = [
                location,
                found_time,
            ]
        else:
            df.loc[len(df)] = [
                item_id,
                location,
                found_time,
            ]

        df.to_csv(
            self.path,
            index=False,
        )

    @staticmethod
    def _normalize_location(value):
        if (
            value is None
            or pd.isna(value)
        ):
            return ""

        return re.sub(
            r"\s+",
            "",
            str(value).lower(),
        )

    @staticmethod
    def _parse_datetime(value):
        if (
            value is None
            or pd.isna(value)
        ):
            return None

        dt = pd.to_datetime(
            str(value).strip(),
            errors="coerce",
        )

        if pd.isna(dt):
            return None

        return dt.to_pydatetime()

    def location_scores(
        self,
        query_location,
        candidate_ids,
    ):
        df = (
            self.load()
            .set_index("item_id")
        )

        query = (
            self._normalize_location(
                query_location
            )
        )

        scores = {}

        for item_id in candidate_ids:

            if item_id not in df.index:
                scores[item_id] = 0.0
                continue

            candidate = (
                self._normalize_location(
                    df.loc[
                        item_id,
                        "location",
                    ]
                )
            )

            if not query or not candidate:
                score = 0.0

            elif query == candidate:
                score = 1.0

            elif (
                query in candidate
                or candidate in query
            ):
                score = 0.85

            else:
                score = (
                    SequenceMatcher(
                        None,
                        query,
                        candidate,
                    ).ratio()
                )

            scores[item_id] = float(score)

        return scores

    def time_scores(
        self,
        query_time,
        candidate_ids,
    ):
        df = (
            self.load()
            .set_index("item_id")
        )

        lost_time = (
            self._parse_datetime(
                query_time
            )
        )

        scores = {}

        for item_id in candidate_ids:

            if (
                lost_time is None
                or item_id not in df.index
            ):
                scores[item_id] = 0.0
                continue

            found_time = (
                self._parse_datetime(
                    df.loc[
                        item_id,
                        "found_time",
                    ]
                )
            )

            # 분실 이전에 발견된 물건은
            # 논리적으로 후보가 될 수 없다.
            if (
                found_time is None
                or found_time < lost_time
            ):
                scores[item_id] = 0.0
                continue

            delta_hours = (
                found_time - lost_time
            ).total_seconds() / 3600

            scores[item_id] = float(
                math.exp(
                    -delta_hours
                    / self.cfg.time_tau_hours
                )
            )

        return scores
