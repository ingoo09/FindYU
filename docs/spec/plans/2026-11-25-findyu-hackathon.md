# FindYU 5시간 해커톤 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한 커밋에서 습득물 등록·사진과 자연어 검색·통합 Dashboard를 연결하고 5시간 안에 시연한다.

**Architecture:** FastAPI와 SQLite가 등록·조회·체크 폼을 맡고, 사진 검색은 FactChat `gemini-embedding-2`와 저장된 사진 벡터로 후보를 선별한다. 자연어 검색은 장소·시각·최신순으로 후보를 뽑고, 두 검색 모두 최대 10건을 Gemini 비교에 한 번 넘긴다. React는 최종 순위와 근거를 보여주고, Dashboard는 기존 목록·상세 API를 호출한다.

**Tech Stack:** Python, FastAPI, SQLAlchemy, SQLite, Pillow, httpx, pytest, React 18, Vite, 영남대 FactChat API Gateway.

**Spec:** [README 변경표](../README.md)를 먼저 읽고 [공통 원본](../00_공통.md)과 [PM·통합](../01_PM_통합.md) · [AI](../02_AI.md) · [백엔드·DB](../03_백엔드_DB.md) · [프론트엔드](../04_프론트엔드.md) · [Dashboard](../05_Dashboard.md)를 읽는다. 정확한 요청·응답은 [저장소 `docs/API.md`](https://github.com/ingoo09/FindYU/blob/a75ed9cba429b448f89b52d7fbb00162bba00a9f/docs/API.md)가 우선이다. README가 사진 후보 선별과 검색 모드에 대해 원본 명세를 보완한다. 나머지는 원본 명세를 적용한다.

## Global Constraints

- 5시간. T+4:00 기능 동결. 최종 1시간은 통합 오류·실사용 검증·시연 준비에 쓴다.
- 등록 UI는 `스마트폰`, `이어폰`, `지갑`과 기본 사진 2장·보완 3장이다. 서버 1~5장 입력과 기존 DB를 보존한다. 장수·순서·대표 사진의 계약은 `image`와 반복 `extra_images`다.
- Gemini 등록 분석과 최종 비교에 `FINDYU_BAZE_MODEL`을 공유한다. 개발 실호출 `gemini-3.8-flash`, 실사용 `gemini-4-argon`. 사진 선별용 임베딩은 별도 `FINDYU_EMBEDDING_MODEL=gemini-embedding-2`, `FINDYU_EMBEDDING_DIMENSIONS=256`으로 두 환경에서 일치시킨다.
- `/search`는 비교 후보 최대 10건, 검색 사진 1장과 후보 대표 사진 최대 1장씩, 최종 비교 1회, 결과 최대 5건이다. 사진 검색에 현재 모델의 저장 벡터가 있으면 검색 사진 임베딩 1회가 선행한다. 비교·임베딩 점수와 소유권 추정을 사용자에게 표시하지 않는다.
- 검색 기본값은 AI 비교 모듈이 병합되기 전까지 `mock`이다. 병합·확인 후 백엔드 PR에서 코드 기본값을 `baze`로 전환한다. 개발과 CI는 두 모드를 명시적으로 `mock`, 실호출 프로필은 두 모드를 `baze`로 둔다. 실사용·시연에 로컬 모델 로딩을 요구하지 않는다.
- Dashboard는 `item_type=found&sort=newest&page_size=20`, 품목·장소 서버 필터와 상세를 사용한다. 새 라우터·DB 마이그레이션·분석 재처리는 이번 범위 밖이다.
- `BAZE_API_KEY`는 각자 서버의 로컬 `.env` 또는 실사용 서버의 비밀 변수에 둔다. 에이전트 프롬프트, 채팅, PR, 프론트 환경변수에 전달하지 않는다. 시연 사진은 허락을 받고 식별정보를 제거한다. 외부 오류에 게이트웨이 원문을 노출하지 않는다.
- 최신 `main`을 기준으로 역할별 작업 브랜치와 PR을 사용한다. 병합은 PM이 맡고 API 변경은 백엔드가 `docs/API.md`와 함께 커밋한다. 소유 경계를 넘는 변경은 `docs/REQUESTS.md` 규칙으로 전달한다.

## Review Focus

1. 수동 등록은 등록 분석 호출 0회로 저장을 끝낸다. 이후 사진 임베딩 1회가 실패해도 같은 ID로 조회·후보 조회가 된다. 재시작 때 전체 백필을 실행하지 않는다 — 작업 3·9.
2. 다른 모델·차원 또는 손상된 저장 벡터는 순위 비교에서 제외한다. 후보 사진 파일이 손상됐으면 다음으로 읽을 수 있는 후보로 채우며, 비교는 최대 10건, 벡터가 전혀 없으면 질의 임베딩 0회다 — 작업 4.
3. 모델이 중복·목록 밖 ID 또는 원문이 포함된 오류를 반환하면 결과를 신뢰하지 않고 정제된 502를 보낸다 — 작업 2·4.
4. 사용자가 품목을 수정하거나 사진을 교체하면 늦은 분석 응답과 다른 품목의 기존 분석 값이 적용되지 않는다 — 작업 3·5.
5. Dashboard의 복합 필터를 빠르게 바꿀 때 늦게 온 이전 응답이 현재 선택을 덮지 않는다 — 작업 7.

---

## 저장소 기준과 변경 범위

[GitHub `main` 대조 커밋 `a75ed9c`](https://github.com/ingoo09/FindYU/tree/a75ed9cba429b448f89b52d7fbb00162bba00a9f)에는 PR #12의 `defer_analysis`, SQLite v8 사진 임베딩 컬럼, 검색 선별·연결부, 수동 백필 도구와 목록 API가 있다. 이 경로와 테스트를 재사용한다. `backend/search_analyzer.py`와 홈 Dashboard 모듈은 이 커밋에서 확인되지 않았다. 작업 시작 시 최신 SHA를 다시 확인하고 이미 병합된 기능은 회귀 테스트만 한다. 모델 요청의 `image_url` 입력 형식은 영남대 문서를 따른다. [FactChat 임베딩 API](https://docs.mindlogic.ai/docs/ynu-ac/api-gateway/reference/embeddings)

| 경로 | 담당 | 이 계획에서의 책임 |
|---|---|---|
| `backend/baze_analyzer.py`, `backend/search_analyzer.py`, `backend/prompts/search_compare_v1.md`, `backend/scripts/test_search_analyzer.py` | 최준서 | 공용 설정·인증, 검색 모델 요청/응답, 주입한 HTTP로 테스트 |
| `backend/main.py`, `backend/search_candidates.py`, `backend/search_adapter.py`, `backend/gemini_embedding.py`, `backend/.env.example`, `backend/tests/test_search_api.py`, `backend/tests/test_search_candidates.py`, `backend/tests/test_gemini_embedding.py`, `backend/tests/test_search_adapter.py`, `docs/API.md` | 권기백 | 기존 등록·임베딩·선별 경로 재사용, 최종 비교 연결, 사진·자연어 분기 및 호환 검증 |
| `backend/tools/backfill_gemini_embeddings.py` | 권기백 실행 · 최인구 데이터 준비 | 시연용 SQLite 복사본의 임베딩 대상 확인·보완, 모델·차원 및 호출량 확인 |
| `frontend/src/App.jsx`, 필요 시 `frontend/src/styles.css` | 김승보 | 기존 등록·검색 화면 수정, Dashboard 연결 |
| `frontend/src/dashboard/FoundItemsDashboard.jsx`, 필요 시 같은 폴더 `dashboard.css` | 이수형 | 목록·필터·상세를 단일 섹션으로 제공 |
| `AGENTS.md`, `CLAUDE.md`, `docs/HANDOFF.md`, `demo/` | 최인구 | 역할 안내 정합성, 리허설과 비밀 없는 결과 기록 |

## 5시간 운영표

| 시간 | 병렬 작업 | 인수 조건 |
|---|---|---|
| T+0:00~0:20 | 작업 1. AI·백엔드 인터페이스, 프론트 mock, Dashboard import. 임베딩 권한과 시연 DB 복사본 확인 | SHA·담당·모델 권한·실행 대상 기록. 권한 확인을 기다리는 동안 mock 진행 |
| T+0:20~2:00 | 작업 2~7 병렬. 백엔드는 기존 등록·임베딩 테스트를 먼저 실행하고 AI 결과는 fixture로 대체 | 등록·두 검색 모드·Dashboard를 개별 검증. PM은 시연 사진·정답 ID 준비 |
| T+2:00~3:30 | AI PR → 백엔드 비교·모드 전환 → 프론트 등록·검색 PR. Dashboard PR → 홈 연결 PR. 시연 DB에서 백필 dry-run | 작업 8 병합, 한 `main`에서 세 흐름 1회 확인 |
| T+3:30~4:00 | 작업 9의 Flash·Argon 실호출. 시연 비용 범위에서 백필 후 사진·자연어 검색 확인 | 임베딩 경로와 최종 비교 시간을 분리해 기록. Flash·Argon에서 저장 벡터 호환 확인 |
| T+4:00~5:00 | 기능 동결, 작업 9의 통합 확인·녹화·발표 준비 | 통합 SHA, 모델, E2E 결과, Gateway 장애 시 시연 경로 기록 |

팀원이 직접 준비할 항목은 [역할별 전달 체크리스트](2026-11-25-findyu-team-inputs.md)에 있다.

### 작업 1 — 착수와 인수 조건 확정 · PM·전원

**Files:** `docs/HANDOFF.md`, `AGENTS.md`, `CLAUDE.md` (PM 권한).

**Interfaces:** 입력은 사용자 지정 수정본과 최신 `main`. 산출물은 현재 SHA, 승인된 사진 목록, T+4:00 동결, 아래 작업 2의 `compare(query, candidates)` 계약과 작업 7의 Dashboard props를 담은 공지다.

- [ ] 각 작업 사본에서 `git status --short`, `git branch --show-current`, `git fetch origin`, `git rev-parse origin/main`을 확인한다. 기존 작업을 보존하고 `origin/main` 기준 역할 브랜치를 사용한다.
- [ ] 체크리스트의 각 담당이 `준비 / 대기 / 미확인`을 보고한다. AI·PM은 사용할 계정에서 Flash·Argon 접근을, 백엔드·PM은 시연 계정에서 `GET /models/?type=embedding`과 `gemini-embedding-2` 접근을 확인한다. 실제 키 없이 진행할 담당자는 `mock`으로 시작한다.
- [ ] `docs/HANDOFF.md`에 시작 SHA, PR 순서, 시연 DB·사진 복사본 위치, 세 모델의 권한 상태를 적는다. PM은 `AGENTS.md`·`CLAUDE.md`에 README 변경표와 `docs/API.md`를 우선 읽도록 연결하고 이미 병합된 임베딩·DB v8과 당일 해야 할 스모크를 구분한다.
- [ ] `git diff --check` 후 소유 문서만 커밋한다. API 문서는 작업 3·4에서 백엔드가 갱신한다.

### 작업 2 — FactChat 검색 비교 어댑터 · 최준서 / Codex

**Files:** 생성 `backend/search_analyzer.py`, `backend/prompts/search_compare_v1.md`, `backend/scripts/test_search_analyzer.py`. 수정 `backend/baze_analyzer.py`.

**Interfaces:** `search_analyzer.compare(query: dict, candidates: list[dict]) -> dict`. `query`는 `kind: "image"|"text"`, `text`, `image_jpeg`, `location`, `occurred_at`; `candidates`는 `id: int`, `category`, `description`, `form_values: dict`, `location`, `occurred_at`, `image_jpeg`를 갖는다. 이미지 값은 `bytes | None`, 나머지 메타데이터는 `str | None`이다. 출력은 `{"results": [{"id": int, "match_reasons": list[str]}]}`다. 기존 `gemini_analyzer.AnalyzerConfigError`는 설정 불가, `AnalyzerError`는 공급자·출력 오류다. 임베딩과 선별은 백엔드가 끝낸 뒤 이 함수를 부르며 어댑터에는 벡터와 숫자 점수를 건네지 않는다.

- [ ] 모의 `httpx` 전송으로 `test_flash_and_argon_use_same_contract`, `test_error_keeps_gateway_body_private`를 작성한다. 입력 후보 ID 12, 사진 검색 JPEG 1장과 후보 JPEG 1장을 넣은 뒤 `assert sent["model"] == configured_model`, `assert len(posts) == 1`, `assert output == {"results":[{"id":12,"match_reasons":[]}]}`를 검사한다. 429·503·비정상 JSON에서 `AnalyzerError`가 나고 응답에 넣은 `private-probe` 문자열이 예외와 로그에 나타나지 않는지 확인한다. 3.8 Flash와 4 Argon을 각각 입력한다.
- [ ] `backend/`에서 `PYTHONPATH=. .venv/bin/python -m pytest scripts/test_search_analyzer.py -q`를 실행한다. 신규 모듈 부재 또는 구현된 계약 차이로 실패하는지 확인한다.
- [ ] `compare()`와 `search_compare_v1.md`를 추가한다. 기존 BAZE URL·인증·응답 내용 추출을 재사용하고 Chat Completions 구조화 JSON을 요청한다. 검색 입력과 후보 ID를 텍스트로 명시한 뒤 해당 이미지 파트를 붙인다. 후보 설명은 사용자 입력 데이터로 표시하고 파일 경로·추가 사진·정답표는 빼고 전송한다. 검색에서는 Gemini 비교를 한 번 요청하며 429/503 뒤 재시도하지 않는다. `baze_analyzer.py`의 기본값은 Flash로 맞춘다. 등록·검색의 오류 응답과 로그에는 요청/응답 원문 대신 HTTP 상태나 정제한 오류 유형을 남긴다. 응답에 모델 ID가 있으면 요청 모델 ID와 구분해 기록한다. 현재 등록 응답 형태·스키마, 기종 미확인, 이어폰 브랜드 수동 입력을 유지한다.
- [ ] 같은 pytest 명령을 다시 돌려 통과를 확인한다. 모델별 모의 요청에서 결과 순서와 `match_reasons`의 빈 배열이 보존되는지 검사한다. API 담당에게 예외 종류와 모의 성공 JSON을 전달한다.
- [ ] `git add backend/search_analyzer.py backend/baze_analyzer.py backend/prompts/search_compare_v1.md backend/scripts/test_search_analyzer.py` 후 `git commit -m "feat: 팩트챗 Gemini 검색 비교 연결"`.

### 작업 3 — 정상·수동 등록과 백그라운드 임베딩 · 권기백 / Claude Code

**Files:** 검증 `backend/main.py`의 `register_item`, `analyze_registered_item`, `_store_search_embedding`, `_analysis_worker`, `backend/models.py`, `backend/migrations.py`; 수정이 필요한 경우 `backend/main.py`의 `apply_analysis`, `backend/tests/test_search_api.py`, `docs/API.md`.

**Interfaces:** `POST /items` multipart에서 등록 사진, `form_answers`, 선택 `analysis_id`·`defer_analysis=true`. 수동 등록은 `id`·`registered`를 즉시 반환한다. 일반 등록은 기존 `analyzing` 및 비동기 처리 상태를 사용한다. 같은 사진 묶음의 유효한 분석은 재사용한다. 등록 이후 성공한 대표 사진 벡터는 `image_embedding_gemini`, 모델·차원 ID는 `image_embedding_model`에 있다. 수동 등록·일반 등록 모두 저장 후 작업에서 임베딩을 한 번 시도한다.

- [ ] 기존 `test_defer_analysis_registers_immediately_without_analysis_call`, `test_normal_registration_analyzes_then_embeds`, `test_embedding_failure_leaves_null_and_keeps_registration`을 읽고 임시 DB·가짜 Gateway fixture를 사용한다. 수동 등록 직후 `assert item["status"] == "registered"`, 모의 워커 실행 전 임베딩 0회, 실행 후 `assert client.analysis_calls == []` 및 `assert client.embedder.calls == 1`을 확인한다. 실패한 수동 등록 임베딩은 추가 재시도 없이 벡터만 비어 있고 같은 ID로 상세·목록·검색의 보완 후보에 포함되는지 확인한다.
- [ ] `test_category_override_drops_cached_model`을 같은 테스트 파일에 추가한다. 스마트폰으로 분석한 동일 사진을 `category="이어폰"`, `brand="삼성"`으로 등록하고 최종 품목·사람 브랜드, `device_model is None`, `device_model_candidates == []`, `has_card_wallet is None`을 확인한다. 분석 캐시 재호출은 0회, 배경 임베딩은 1회다.
- [ ] `backend/`에서 `.venv/bin/python -m pytest tests/test_search_api.py -q -k 'defer or registration or embedding_failure or category_override'`를 실행한다. 기준에 맞는 케이스는 통과 상태로 남기고, 누락된 품목 수정·실패 케이스만 재현한다.
- [ ] 재현된 문제만 수정한다. 최종 품목과 AI 품목이 다르면 캐시의 다른 품목 기종·브랜드·전용 필드를 적용하지 않는다. 등록 요청에서 이미 커밋한 DB·사진과 백그라운드 임베딩의 결과는 독립적으로 취급한다. `baze`·`mock` 시작 시 전체 백필을 실행하지 않는다. 기존 `analyzing` 레코드의 등록 작업 재개와 SQLite v8·사진 경로는 유지한다.
- [ ] 같은 focused pytest와 `tests/test_check_form.py`, `tests/test_item_list.py`를 다시 실행한다. 시작 스모크에서 로컬 모델 로딩과 전체 백필이 없는지 확인한다.
- [ ] 변경이 있으면 `docs/API.md`와 맞추고 관련 파일만 커밋한다. 기준 동작이 이미 맞으면 테스트 결과를 작업 9에 넘긴다.

### 작업 4 — 사진 임베딩 선별·Gemini 비교 연결 · 권기백 / Claude Code

**Files:** `backend/main.py`의 `_gateway_search`·`_gateway_error`, `backend/search_candidates.py`, `backend/search_adapter.py`, 필요 시 `backend/gemini_embedding.py`의 오류 처리, `backend/.env.example`, `backend/tests/test_search_api.py`, `backend/tests/test_search_candidates.py`, `backend/tests/test_search_adapter.py`, `backend/tests/test_gemini_embedding.py`, `docs/API.md`.

**Interfaces:** `gemini_embedding.make_embedder(mode)`의 `model_id`, `embed_images(images) -> list[list[float]]`와 `search_adapter.compare(mode, query: SearchQuery, candidates: list[SearchCandidate]) -> list[dict]`를 연결한다. HTTP는 기존 `docs/API.md`를 유지한다. 소비 필드는 `results[].id`, `rank`, `match_reasons`, `filter_check`, `total_candidates`, `evaluated_count`다. `results[].selection_source`, `embedding_model`, `selection.by_embedding`·`by_order`, `timings.embedding_ms`·`compare_ms`·`total_ms`는 진단에 쓴다. 구형 점수는 전환 기간 `null`이다. 설정 오류 503, 임베딩·비교 실패 또는 출력 검증 오류 502, 검색 성공 0건 200이다.

- [ ] 기존 사진·자연어·오류 테스트를 먼저 실행한다. `backend/`에서 `.venv/bin/python -m pytest tests/test_search_api.py tests/test_search_candidates.py tests/test_search_adapter.py tests/test_gemini_embedding.py -q`. 기존 `test_image_search_ranks_by_embedding_then_fills_with_spec_order`, `test_text_search_uses_spec_order_and_no_embedding`, `test_query_embedding_failure_is_502`, `test_zero_candidates_is_200_without_ai_calls`는 기준으로 보존한다.
- [ ] `test_photo_search_caps_hybrid_shortlist`를 `test_search_api.py`에 보강한다. 등록 후보 A~L을 순서대로 둔다. D는 코사인 1.0의 벡터를 갖지만 대표 파일이 손상됐다. C는 코사인 0.8의 정상 호환 벡터다. E·F의 위치는 중앙도서관, 시각은 14:10으로 같고 F의 ID가 더 크다. F는 다른 모델의 벡터, E는 벡터 없음이다. 나머지는 다른 위치, 11:00, 같은 등록 시각, 벡터 없음이다. 중앙도서관 14:00 검색에서 가짜 비교기가 전달 순서를 뒤집어 반환하게 한다.

  ```python
  assert query_embedding_calls == 1 and len(compare_calls) == 1
  assert sent_ids == [C, F, E, L, K, J, I, H, G, B]
  assert body["evaluated_count"] == 10 and body["total_candidates"] == 12
  assert body["selection"] == {"by_embedding": 1, "by_order": 9}
  assert [result["id"] for result in body["results"]] == [B, G, H, I, J]
  ```

- [ ] `test_image_search_skips_query_embedding_without_compatible_vectors`를 추가한다. 현재 모델과 다른 벡터, JSON 손상, 길이 불일치, 비수치·비유한 값만 있는 경우 `query_embedding_calls == 0`, 읽을 수 있는 사진을 명세 순서로 비교 1회, `selection.by_embedding == 0`, `timings`에 `embedding_ms` 없음이 기대다. 사진이 없는 설명 후보는 그대로 전달한다. 빈 후보·필터만 검색에는 두 Gateway 호출이 모두 0회이며, 질의 임베딩 오류에서 비교를 시작하지 않고 502/503을 반환한다. 기존 ID 검증과 오류 테스트에 가짜 원문이 공개 `detail`에 없는 조건을 더한다.
- [ ] 첫 pytest 명령을 다시 실행해 실제 회귀를 확인한다. 필요한 부분만 수정한다. 기존 `found`·`analysis_failed` 제외와 체크 폼 규칙을 유지한다. `stored_embedding()`은 `model@dimensions`에 맞는 수치 벡터만 인정한다. 사진은 `image_search_order()`에서 코사인 내림차순, 동점은 `spec_order()`다. `take_readable()`로 손상 사진을 건너뛰고, 빈 자리는 모델 불일치·누락 후보에서 장소 부분 일치 → 시각 근접 → `created_at DESC, id DESC`로 채운다. 자연어와 필터만 검색은 `spec_order()`를 사용한다. `total_candidates`는 이미지 가용성과 상한 적용 전 필터 통과 수다. `evaluated_count`는 실제 비교 전송 수다. Gemini 반환 ID만 DB와 결합하고 5건까지 돌려준다. `embedding_model`의 값만으로 호출 여부를 단정하지 말고 `timings.embedding_ms`와 `selection`을 확인한다.
- [ ] 기존 `/embeddings` 입력의 `image_url` 객체와 1024px JPEG 전처리를 유지한다. 게이트웨이 응답 개수·256차원·사진당 `prompt_tokens` 상한 1,000 검증의 기존 테스트를 재실행한다. 현재 모델이 403이거나 검증에 실패하면 상태를 기록하며 외부 원문과 키를 노출하지 않는다. 질의 임베딩 실패를 임의의 빈 검색 결과나 조용한 모델 전환으로 처리하지 않는다.
- [ ] 작업 2가 아직 없으면 `search_adapter.DEFAULT_MODE="mock"`을 유지한다. 작업 2 병합 후 실제 `compare()` import와 BAZE 스모크를 확인하고 `DEFAULT_MODE="baze"`로 바꾼다. `.env.example`은 개발용 명시 `mock` 프로필로 두고, 실호출 서버는 두 모드에 `baze`를 직접 지정한다. `tests/test_search_adapter.py`의 전환 테스트와 `docs/API.md`의 기본값 설명을 같은 커밋에서 갱신한다. 사용자가 이미 설정한 `.env`는 코드 기본값보다 우선한다. 레거시 `local`은 기존 선택지로만 보존하고 시연에서 선택하지 않는다.
- [ ] `.venv/bin/python -m pytest tests -q`와 작업 2의 별도 테스트를 실행한다. `GET /`에서 사용 모드를 확인하고 사진·설명·장애 구분 결과를 남긴다. 변경 파일만 스테이징하고 `git commit -m "feat: 사진 임베딩 후보와 Gemini 비교 연결"`을 실행한다.

### 작업 5 — 등록 사진과 수동 저장 UI · 김승보 / Codex

**Files:** 수정 `frontend/src/App.jsx`의 `RegisterView`, `RegisteredItemStatus`, 필요 시 `frontend/src/styles.css`.

**Interfaces:** `GET /form-schema`, `POST /items/analyze` 응답 `analysis_id`, `check_form`, `photo_hint`; 작업 3의 `POST /items` 입력 `defer_analysis`, 응답 `id`, `status`.

- [ ] 브라우저 테스트 입력을 정한다. 스마트폰 사진 1·2·5·6장, 촬영 가이드 3품목, 분석 요청 지연 중 사진 교체, 분석 실패 502 뒤 수동 등록. Network에서 `1장 → 분석/등록 요청 0`, `2장 → image 1 + extra_images 1`, `6장 → 등록/분석에는 5장 이하와 안내`, `수동 제출 → POST /items 1회 + defer_analysis=true`를 확인한다. 늦은 응답의 `analysis_id`가 새 사진 제출에 붙으면 실패다.
- [ ] 기존 앱과 mock 응답으로 위 브라우저 테스트를 먼저 실행해 1장 허용이나 수동 분기 누락을 재현한다. 서버 장애·지연은 로컬 모의 응답으로 만든다.
- [ ] `MAX_REGISTER_IMAGES=5`와 기존 미리보기를 사용한다. 두 기본각이 준비됐을 때 분석과 등록을 열고 세 품목 촬영 안내를 붙인다. 사진 집합의 요청 식별자를 확인해 늦은 응답을 적용하지 않는다. 품목 수정 시 이전 전용 값을 비우고 사람 값을 보존한다. 수동 저장은 사용자가 선택했을 때만 `defer_analysis=true`로 보내고, 진행 중 분석 응답을 취소하거나 무시한다. 서버가 실제 `id`를 준 뒤 성공을 표시한다.
- [ ] `frontend/`에서 `npm run build`를 실행하고 같은 브라우저 입력으로 기대 Network와 화면 동작을 확인한다. 분석 오류 뒤 사진과 폼이 유지되는지 포함한다.
- [ ] `git add frontend/src/App.jsx`와 실제 변경한 스타일 파일만 스테이징하고 `git commit -m "feat: 기본 2장 가이드와 수동 등록"`.

### 작업 6 — 사진·자연어 결과 화면 · 김승보 / Codex

**Files:** 수정 `frontend/src/App.jsx`의 `SearchView`, `CandidateCard`, `MatchDashboard`; 필요 시 `frontend/src/styles.css`.

**Interfaces:** `POST /search`는 사진 `image` 또는 자연어 `description` 및 `top_k=5`. `results[]` 순서, `match_reasons: string[]`, `filter_check`, `total_candidates`, `evaluated_count`는 작업 4 결과다. 옛 응답에 `match_reasons`와 `evaluated_count`가 빠져도 화면은 열린다. `selection`, `selection_source`, `embedding_model`, `timings`는 진단용이며 카드 정렬·본문에는 사용하지 않는다.

- [ ] 브라우저에서 `results` ID 순서 `[12, 9]`, `total_candidates=12`, `evaluated_count=10`, 두 번째 후보의 근거 `[]`를 사용한다. 12는 `selection_source="order"`, 9는 `"embedding"`으로 둔다. 12가 첫 카드, 화면에 후보 평가 10건, 근거가 있는 카드에만 근거 문구, 백분율 0개를 확인한다. 200 빈 결과와 임베딩/비교 502를 구분한다.
- [ ] 기존 화면에 모의 응답을 넣고 기존 백분율·근거 누락을 재현한다. 사진 단독과 설명 단독 FormData를 Network에서 각각 확인한다.
- [ ] 기존 카드·상세를 `results` 순서와 `match_reasons`로 연결하고 점수·게이지 의존을 제거한다. `filter_check`는 기존 미확인 표기를 재사용한다. 사진·자연어 검색에서 `evaluated_count < total_candidates`일 때 평가 건수를 표시한다. 사진과 설명 없이 필터만 쓴 경우에는 일반 목록으로 표시한다. 기존 상세에서 사진·외형·장소·습득 일시와 최종 판단 안내를 유지한다.
- [ ] `npm run build` 후 같은 모의 사례, 사진·자연어 실제 FindYU mock API, 빈 결과와 오류를 확인한다. 외부 게이트웨이 요청이 브라우저에서 직접 발생하지 않는지 확인한다.
- [ ] `git add frontend/src/App.jsx`와 실제 변경한 스타일 파일만 스테이징하고 `git commit -m "feat: 검색 후보 순위와 비교 근거 표시"`.

### 작업 7 — 통합 Dashboard 모듈 · 이수형 / Codex

**Files:** 생성 `frontend/src/dashboard/FoundItemsDashboard.jsx`, 필요 시 같은 폴더 `dashboard.css`.

**Interfaces:** `export default function FoundItemsDashboard({ apiUrl, assetUrl })`. 두 함수는 각각 기존 백엔드 URL과 이미지 URL을 만든다. `GET /items?item_type=found&sort=newest&page=1&page_size=20`, `GET /items/locations?item_type=found`, `GET /items/{id}`를 사용한다. 목록은 `items`, `total`, `page`, `has_next`를 소비한다.

- [ ] 브라우저 회귀로 `이어폰 + 중앙도서관` 요청에 `category`, `location`, `page=1`이 함께 붙고, 다음 페이지가 `page=2`를 보낸다는 기대를 적는다. 빠르게 두 필터를 바꾸고 두 번째 요청을 먼저 응답시킨 뒤 화면에 두 번째 선택 결과만 남아야 한다. 한 장 사진·이미지 URL 누락·빈 응답도 확인한다.
- [ ] 기존 백엔드 목록 API 또는 같은 형식의 가짜 응답으로 기대 URL·응답을 확보한다. 홈 연결 전에는 Dashboard 소유 폴더에서 Vite로 제공되는 임시 테스트 HTML에 컴포넌트를 렌더링해 검사하고, 홈 통합은 작업 8에서 확인한다.
- [ ] 위 시그니처로 최신순 카드·장소/품목 필터·이전/다음·상세 view를 만든다. 뒤로 가면 필터·페이지를 보존한다. 필터·페이지 요청의 취소 또는 요청 순서 확인으로 옛 응답을 무시한다. 서버는 기본 상태 필터 없이 호출하고, 표시 날짜는 습득 일시와 등록 일시를 구분한다.
- [ ] 테스트 HTML 또는 연결된 앱에서 필터·페이지·상세·빈 결과·오류를 확인한다. 임시 테스트 HTML을 커밋에서 제외하고 김승보에게 파일·export·props를 전달한다.
- [ ] `git add frontend/src/dashboard/FoundItemsDashboard.jsx`와 실제 추가한 스타일만 스테이징하고 `git commit -m "feat: 습득물 통합 Dashboard"`.

### 작업 8 — 홈 연결과 빌드 · 김승보 / Codex

**Files:** 수정 `frontend/src/App.jsx`의 홈 렌더링.

**Interfaces:** 작업 7의 `FoundItemsDashboard`, 기존 `apiUrl(path)`·`assetUrl(path)`를 제공한다. 홈은 **분실물 찾기**, **습득물 등록** 뒤에 목록을 배치한다.

- [ ] 홈에 두 버튼과 Dashboard가 보이고, 등록 뒤 홈 복귀 시 최신 목록에 같은 `id`가 표시되어야 한다는 브라우저 검증을 작성한다.
- [ ] 작업 7 병합 후 기존 홈에서 목록이 보이지 않는 것을 확인한다.
- [ ] `import FoundItemsDashboard from "./dashboard/FoundItemsDashboard"`와 `<FoundItemsDashboard apiUrl={apiUrl} assetUrl={assetUrl} />`를 홈에 추가한다.
- [ ] `npm run build`로 모듈 import를 확인하고 실제 API에서 홈 → 등록 → 홈과 상세를 재현한다.
- [ ] `git add frontend/src/App.jsx` 및 `git commit -m "feat: 홈에 통합 Dashboard 연결"`.

### 작업 9 — 백필·모델 전환·통합 시연 · 최인구·권기백 / 전원

**Files:** 백필 실행 `backend/tools/backfill_gemini_embeddings.py`, 기록 `docs/HANDOFF.md`와 기존 `demo/` 안내. DB·사진·녹화 원본은 팀이 정한 로컬 또는 승인된 채널에 보관한다.

**Interfaces:** 한 통합 SHA 및 같은 `FINDYU_DB_PATH`·`FINDYU_UPLOAD_DIR` 시연 복사본. Flash·Argon 설정은 등록·검색 모드 `baze`와 `FINDYU_BAZE_MODEL`을 사용한다. `gemini-embedding-2@256`과 전처리를 유지하면 Flash에서 만든 벡터를 Argon 비교에서도 재사용한다. 기록은 `시험 ID / SHA / 비교 모델·임베딩 모델 / 요청 종류 / 물품 ID / embedding_ms·compare_ms·total_ms / 결과`다. 값이 없는 단계는 미호출로 기록한다.

- [ ] `backend/`에서 `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`로 준비하고 `.venv/bin/python -m pytest tests -q`를 실행한다. AI 테스트는 `PYTHONPATH=. .venv/bin/python -m pytest scripts/test_search_analyzer.py -q`로 병행한다. `frontend/`에서 `npm ci`와 `npm run build`를 실행한다. 통과 수 또는 재현되는 실패를 남긴다.
- [ ] 등록·검색 `mock`으로 E2E-01~04를 실행한다. `backend/`에서 `.venv/bin/uvicorn main:app --port 8000`, `frontend/`에서 `npm run dev`를 사용한다. 등록 수정값·ID, 수동 저장과 상세, 사진·설명 각각의 순위, 필터·페이지·상세를 확인한다. 시연용 문장·장소·등록 및 질의 사진을 고정한다.
- [ ] 권기백은 서버와 동일한 DB·사진 복사본, 동일한 모델·차원 설정에서 시연용 백필을 먼저 미리 확인한다. 다음 명령은 `backend/` 기준이다. DB 구조가 아직 v8이 아니면 운영 원본 대신 시연 복사본에서 먼저 적용한다.

  ```bash
  FINDYU_SEARCH_ANALYZER_MODE=baze .venv/bin/python tools/backfill_gemini_embeddings.py --dry-run --batch 5
  ```

- [ ] 출력의 DB 경로·`gemini-embedding-2@256`·대상/대표 사진 누락·예상 요청 수를 확인한다. PM이 시연 호출 범위를 확인한 후 해당 복사본에서 `FINDYU_SEARCH_ANALYZER_MODE=baze .venv/bin/python tools/backfill_gemini_embeddings.py --batch 5`를 실행하고 도구의 확인 프롬프트를 따른다. 기본 배치는 5장, 허용 1~10장이다. 일부 사진·배치가 실패하면 ID와 사유만 적고 해당 물품은 벡터 없는 보완 후보로 둔다. 같은 설정에서 다시 `--dry-run`하여 대상이 없거나 미완료 건만 남는지 확인한다. 서버 시작 때 백필이 자동 실행되는 경로를 추가하지 않는다.
- [ ] Flash로 세 품목 등록 분석, 모델이 일치하는 벡터가 준비된 사진 검색 1건, 자연어 검색 1건을 실제 확인한다. 사진 검색에서 `selection.by_embedding > 0`, `evaluated_count <= 10`, `embedding_ms`와 `compare_ms`를 함께 기록한다. 자연어 검색에서는 `by_embedding == 0`, `embedding_ms`가 없음을 확인한다. 임베딩이 없는 사진 사례는 `order` 보완으로 별도 기록한다.
- [ ] `FINDYU_BAZE_MODEL=gemini-4-argon`으로 서버를 재시작한다. 같은 DB에서 등록 분석 1건과 사진 검색 1건으로 E2E-05를 확인한다. `embedding_model`·`selection`을 확인하며 비교 모델 변경만으로 벡터를 다시 생성하지 않는다. 실제 응답 모델 ID가 확인되면 설정값과 함께 적는다. 429/503·권한 부족은 실패 환경과 HTTP 상태를 기록하고, 실사용 권한·검증이 막혔으면 미확인으로 남긴다.
- [ ] 사전 등록한 흐름의 녹화를 만든다. 실시간 Gateway 장애를 가정해 목록·상세와 수동 등록이 열리는지 확인한다. 검색 비교가 중단되면 같은 SHA·자료의 녹화를 사용한다. DB·사진 재현 방법, 발표 수치의 시험 ID와 출처를 적는다.
- [ ] `docs/HANDOFF.md`에 빌드·테스트·권한·시연 결과와 실제 사용 SHA를 적는다. `git diff --check` 후 문서만 커밋한다.

## 요구사항과 검증 위치

| 인수 기준 | 구현 작업 | 확인 결과 |
|---|---|---|
| E2E-01 2장부터 분석·등록, 수정, 5장 제한 | 2·3·5 | UI Network, 상세 응답, 세 품목 샘플 |
| E2E-02 수동 저장, 등록 분석 0회, 검색·목록 포함 | 3·4·5 | 실제 `id`, 독립된 백그라운드 임베딩 실패 확인 |
| E2E-03 사진·자연어, 순위·근거, 0건/오류 | 2·4·6·9 | 사진 임베딩 선별과 보완, 자연어 임베딩 0회, 상한과 오류 문구 |
| E2E-04 최신순 목록, 복합 필터, 상세·재조회 | 7·8 | 홈과 상세 실제 API 확인 |
| E2E-05 Flash→Argon | 2·9 | 모델별 스모크 결과, 동일 임베딩 재사용, 권한 또는 오류 상태 |
