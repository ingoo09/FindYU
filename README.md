# FindYU

객체지향 + LangGraph 기반 분실물 검색/등록 AI 모듈.

## Project Structure

```text
findyu_project_configurable/
├── main.py
├── requirements.txt
│
├── prompts/
│   ├── query_parser_system.txt
│   └── vlm_system.txt
│
└── findyu/
    ├── __init__.py
    ├── config.py
    ├── paths.py
    ├── prompt_loader.py
    ├── models.py
    ├── metadata.py
    ├── vector_store.py
    ├── query_parser.py
    ├── ranker.py
    ├── search_engine.py
    ├── registration.py
    ├── states.py
    ├── workflow.py
    └── app.py
```

## Default Models

`FindYUConfig()` 기본값은 현재 프로젝트에서 사용 중인 조합이다.

```python
image_encoder_model_name = "facebook/dinov2-small"
text_image_encoder_model_name = "google/siglip2-base-patch16-224"
query_llm_model_name = "Qwen/Qwen3-0.6B"
registration_vlm_model_name = "Qwen/Qwen2.5-VL-1.5B-Instruct"
```

현재 기본 실행 mode:

```python
query_parser_mode = "mock"
registration_analyzer_mode = "mock"
```

즉 DINO / SigLIP retrieval은 실제 모델을 사용하고,
Query LLM / VLM은 OOM 방지 및 workflow 검증을 위해 기본적으로 로드하지 않는다.

## Model Override

기본 모델을 그대로 쓰면:

```python
config = FindYUConfig()
```

특정 모델만 변경하려면:

```python
config = FindYUConfig(
    image_encoder_model_name="facebook/dinov2-base",
    query_llm_model_name="Qwen/Qwen2.5-0.5B-Instruct",
)
```

나머지 값은 모두 default가 유지된다.

## Important Config

```python
config = FindYUConfig(
    retrieval_k=50,
    result_k=16,
    min_score=0.35,
    max_retry=2,

    image_weight=0.45,
    text_weight=0.25,
    location_weight=0.20,
    time_weight=0.10,
)
```

## Prompt Management

시스템 프롬프트는 Python 코드 내부에 두지 않는다.

```text
prompts/query_parser_system.txt
prompts/vlm_system.txt
```

`PromptLoader`가 실행 시 파일에서 읽는다.

이 구조 덕분에 prompt 실험 시 Python 코드를 수정할 필요가 없다.

## Run

```bash
pip install -r requirements.txt
python main.py
```
