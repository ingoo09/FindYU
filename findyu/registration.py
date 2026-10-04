import json
import shutil
from pathlib import Path
from uuid import uuid4


class RegistrationService:
    """
    습득물 등록 담당.

    현재 VLM은 mock.
    실제 VLM 연결 시 analyze_image()만 교체하면 된다.

    VLM 시스템 프롬프트는
    prompts/vlm_system.txt에서 로딩한다.
    """

    def __init__(
        self,
        config,
        paths,
        metadata,
        vector_store,
        prompt_loader,
    ):
        self.cfg = config
        self.paths = paths

        self.metadata = metadata
        self.vector_store = (
            vector_store
        )

        self.vlm_system_prompt = (
            prompt_loader.load(
                "vlm_system.txt"
            )
        )

    def analyze_image(
        self,
        image_path,
    ):
        # 현재는 로직 검증만 하므로
        # 실제 VLM 대신 mock 결과를 반환.
        if (
            self.cfg
            .registration_analyzer_mode
            == "mock"
        ):
            print(
                "[Mock VLM]",
                image_path,
            )

            return {
                "category":
                    "wireless earphones",

                "brand":
                    "Apple",

                "product":
                    "AirPods",

                "color":
                    "white",

                "features": [
                    "white charging case",
                    "wireless earphones",
                ],
            }

        # 추후 여기에 실제 VLM inference 구현.
        # 사용할 모델명은 self.cfg.registration_vlm_model_name에서 가져온다.
        # 시스템 프롬프트는 self.vlm_system_prompt를 사용한다.
        raise NotImplementedError(
            "실제 VLM inference는 아직 "
            "연결하지 않았습니다."
        )

    def save(
        self,
        image_path,
        location,
        found_time,
        attributes,
    ):
        item_id = (
            uuid4().hex
        )

        source = Path(
            image_path
        )

        suffix = (
            source.suffix.lower()
            or ".jpg"
        )

        destination = (
            self.paths.db_dir
            / f"{item_id}{suffix}"
        )

        shutil.copy2(
            source,
            destination,
        )

        # location/time metadata 저장
        self.metadata.upsert(
            item_id,
            location,
            found_time,
        )

        # VLM 분석 결과 저장
        attribute_path = (
            self.paths.db_dir
            / f"{item_id}.json"
        )

        attribute_path.write_text(
            json.dumps(
                attributes,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # Prototype:
        # 등록 후 전체 vector index 갱신
        self.vector_store.build()

        return item_id
