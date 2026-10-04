from findyu import (
    FindYUConfig,
    ProjectPaths,
    FindYUApp,
)


def main():
    # =========================================================
    # 기본 설정
    # =========================================================
    #
    # 현재 사용 중인 모델 조합이 FindYUConfig의 default다.
    #
    # 따라서 기본값을 그대로 사용할 경우:
    #     config = FindYUConfig()
    # 만 작성하면 된다.
    #
    # 모델을 바꾸고 싶을 때만 아래처럼 원하는 값만 override한다.
    #
    # 예:
    # config = FindYUConfig(
    #     image_encoder_model_name="facebook/dinov2-base",
    #     query_llm_model_name="Qwen/Qwen2.5-0.5B-Instruct",
    # )
    #
    # 현재는 로직 테스트이므로 Query Parser / Registration VLM은
    # 기본값인 mock mode로 실행된다.
    # =========================================================

    config = FindYUConfig()

    paths = ProjectPaths(
        config
    )

    app = FindYUApp(
        config,
        paths,
    )

    # 프로그램 시작 시 DB 이미지 기반
    # FAISS index를 한 번 생성한다.
    app.initialize()

    print("FindYU ready")


if __name__ == "__main__":
    main()
