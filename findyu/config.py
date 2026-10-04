from dataclasses import dataclass
import torch


@dataclass
class FindYUConfig:
    """
    FindYU 전체 설정.

    사용자는 이 Config만 수정하면 다음을 한 곳에서 바꿀 수 있다.
    - 모델 이름
    - mock / real 실행 모드
    - 검색 후보 수
    - 최종 출력 개수
    - confidence threshold
    - retry 횟수
    - ranking 가중치
    - 시간 decay
    - 프로젝트 경로

    현재 프로젝트에서 사용 중인 모델 조합을 default로 유지한다.
    """

    # =========================================================
    # 1. Model configuration
    # =========================================================

    # Image -> Image retrieval
    # 현재 기본값: DINOv2-small
    image_encoder_model_name: str = "facebook/dinov2-small"

    # Text -> Image retrieval
    # 현재 기본값: SigLIP2 base
    text_image_encoder_model_name: str = (
        "google/siglip2-base-patch16-224"
    )

    # Natural-language query parser
    # 현재는 OOM/로직 테스트 때문에 mock을 기본값으로 사용.
    # query_parser_mode="llm"으로 변경하면 아래 모델을 실제 로드한다.
    query_llm_model_name: str = "Qwen/Qwen3-0.6B"

    # Registration image analyzer
    # 실제 VLM 연결 시 사용할 기본 모델명.
    # 현재는 registration_analyzer_mode="mock"이 기본값이므로
    # 이 모델은 자동으로 로드되지 않는다.
    registration_vlm_model_name: str = (
        "Qwen/Qwen2.5-VL-1.5B-Instruct"
    )

    # =========================================================
    # 2. Model execution mode
    # =========================================================

    # "mock" : 사용자 문장을 그대로 text retrieval에 사용
    # "llm"  : query_llm_model_name 모델을 사용해 구조화
    query_parser_mode: str = "mock"

    # "mock" : VLM inference 없이 테스트용 JSON 반환
    # "vlm"  : registration_vlm_model_name 모델 사용
    # 현재 코드에서는 실제 VLM inference 연결부는 TODO 상태.
    registration_analyzer_mode: str = "mock"

    # =========================================================
    # 3. Retrieval / search
    # =========================================================

    # 각 retrieval 모델이 FAISS에서 먼저 가져올 후보 수
    retrieval_k: int = 50

    # 최종 사용자에게 보여줄 결과 수
    result_k: int = 16

    # Top-1 score가 이 값보다 낮으면
    # LangGraph Human-in-the-loop 수행
    #
    # 주의:
    # 현재 DINO / SigLIP raw score는 scale이 다르므로
    # 이 값은 prototype/test용이다.
    min_score: float = 0.35

    # 추가 정보 요청 최대 횟수
    max_retry: int = 2

    # =========================================================
    # 4. Multimodal ranking weights
    # =========================================================

    image_weight: float = 0.45
    text_weight: float = 0.25
    location_weight: float = 0.20
    time_weight: float = 0.10

    # 시간 차이 score:
    # exp(-delta_hour / tau)
    time_tau_hours: float = 48.0

    # =========================================================
    # 5. Runtime / paths
    # =========================================================

    # Google Drive 기준 FindYU 프로젝트 root
    root: str = "/content/drive/MyDrive/FindYU"

    # system prompt 파일 폴더
    prompt_dir: str = "prompts"

    # 기본 device 자동 선택
    device: str = (
        "cuda"
        if torch.cuda.is_available()
        else "cpu"
    )

    @property
    def dtype(self):
        """
        GPU에서는 FP16,
        CPU에서는 FP32 사용.
        """
        return (
            torch.float16
            if self.device == "cuda"
            else torch.float32
        )

    @property
    def weights(self):
        """
        Ranker가 사용하는 modality weight.
        """
        return {
            "image": self.image_weight,
            "text": self.text_weight,
            "location": self.location_weight,
            "time": self.time_weight,
        }
