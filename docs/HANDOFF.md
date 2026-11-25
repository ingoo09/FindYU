# 인수인계 — feature/phone-wallet (2026-11-16 작성, 2026-11-25 갱신)

대상 물품을 **스마트폰·이어폰·지갑**으로 좁히면서 백엔드·DB, 등록 분석, 등록·검색 화면을 바꾼 작업의 인수인계 문서.
브랜치: `feature/phone-wallet` (`demo/midterm`에서 분기). 2026-11-25 push함. PR은 아직 만들지 않음.

---

## 1. 빠른 시작

```bash
cd backend
cp .env.example .env          # BAZE_API_KEY 입력 (기본 baze 모드, 모델은 비우면 gemini-3.5-flash)
.venv/bin/uvicorn main:app    # 첫 실행 시 findyu.db 자동 마이그레이션(v1~v7)
.venv/bin/python -m pytest tests   # 단위 테스트 179개 (API 키 불필요)

cd ../frontend && npm install && npm run dev   # http://localhost:5173 (백엔드 8000으로 프록시)
```

- 등록 분석 모드: `FINDYU_REGISTRATION_ANALYZER_MODE=baze(기본) | gemini | mock | vlm`
  - `baze`: 학교 팩트챗(마인드로직 BAZE API Gateway, OpenAI 호환)으로 Gemini 호출 (`baze_analyzer.py`). 모델은 `FINDYU_BAZE_MODEL`, 상태는 `GET /`의 `registration_baze`
  - `gemini`: Gemini API 직접 호출 (`gemini_analyzer.py`, 무료 등급 하루 20회). 모델은 `FINDYU_GEMINI_MODEL`
  - 두 모드는 프롬프트(v1.3)·응답 스키마·정규화·DB 저장 방식이 같다
- **주의: 셸이나 `backend/.env`에 `FINDYU_REGISTRATION_ANALYZER_MODE`가 있으면 기본값(baze)보다 우선한다.** 예전 `.env`를 복사해 쓰면 gemini 모드로 돈다
- API 키가 없어도 서버는 뜬다. 분석 요청만 503과 함께 "…환경변수가 없습니다: BAZE_API_KEY" 메시지로 실패한다
- 등록·검색 체크 폼 API: `docs/API.md`
- `backend/.venv`에 추가로 설치한 패키지: `langgraph`, `accelerate`, `pytest`, `google-genai`, `python-dotenv` (`requirements.txt`에 반영됨). baze 모드는 기존 `httpx`만 쓴다

### 커밋하지 않은 것 (의도적)

| 대상 | 이유 |
|---|---|
| `backend/findyu.db`의 변경분 | 서버 시작 시 자동 마이그레이션으로 처리. 저장소에는 원본(v0)만 있음 |
| `backend/.env` | API 키 (`.gitignore`) |
| `test_photos/` | 테스트 사진 (`.git/info/exclude`) |

---

## 2. 한 작업

### 2-1. 2026-11-25

| 영역 | 내용 |
|---|---|
| BAZE 게이트웨이 | `baze_analyzer.py`: `/chat/completions` + `response_format=json_schema`. 이미지 입력·enum 제약이 실제로 동작하는 것을 확인했고, 응답은 백엔드에서 pydantic으로 다시 검증. 408/429/5xx·네트워크 오류는 최대 3회 재시도. **기본 모드를 baze로 변경** |
| 측정 스크립트 | `compare_models.py --resume <json>`(성공분 재사용), `--retry-failed`(일시적 실패분 재측정), 결과에 측정 경로(서버 모드·모델) 기록 |
| 반복 측정 | baze로 3.5-flash·3.8-flash 조합당 3회(v1.2), 3.5-flash 조합당 3회(v1.3) → 3절 |
| 품목 "이어폰" | 품명 스마트폰/이어폰/지갑/기타. 헤드폰은 기타, "에어팟 케이스"는 이어폰. 프롬프트 v1.3 |
| DB v7 | `has_card_wallet`, `earphone_components`, `wallet_closure`, `field_sources`(항목별 human/ai), `analysis_model`. 기존 "기타" 중 설명·브랜드에 이어폰 단어가 있으면 "이어폰"으로 바꿈 (로컬 DB는 #6·#7·#8) |
| 체크 폼 API | `check_form.py`. `GET /form-schema`, 분석 응답에 `check_form`(항목별 AI 값·needs_check·사유)·`photo_hint`·`analysis_id`, `POST /items`의 `form_answers`(사람 값 우선)·`analysis_id`(분석 재사용), `POST /search`의 `category`·`filters` |
| 프론트 | 등록: 사진 선택 후 자동 분석 → AI 값 미리 선택, needs_check 항목은 "확인해주세요"로 강조, 사진 추가 안내. 검색: 같은 체크 폼을 필터로 사용, 후보에 "확인 필요" 항목 표시. 기존 자유 입력(종류·색상·브랜드)은 없앰 |
| 문서 | `docs/API.md`(체크 폼 API와 실제 응답 예시), `docs/model_comparison.md`(반복 측정·회귀 측정) |

확인한 것 (2026-11-25)
- 테스트 179개 통과
- baze 모드 서버에서 등록 1건(분석 → `analysis_id`로 등록 → `registered`, `analysis_model=baze:gemini-3.5-flash/v1.3`)과 검색 1건(품목·브랜드·케이스 필터로 8건 → 1건)이 동작함. 확인 뒤 테스트 물품·업로드 파일은 지우고 DB를 되돌림
- **프론트 화면은 브라우저로 확인하지 못했다** (빌드만 확인). 등록 화면의 강조 표시와 AI 값 미리 선택을 직접 확인할 것

```
230186e feat: 팩트챗(BAZE) 게이트웨이 등록 분석 모드 추가 및 기본 모드로 지정
4a8be57 chore: 모델 비교 스크립트에 --resume과 실패분 재측정 추가
4b58a7a docs: BAZE 게이트웨이로 3.5-flash·3.8-flash 조합당 3회 측정 결과 (프롬프트 v1.2)
0768043 feat: 품목 '이어폰'과 체크 폼 항목 추가 (DB v7, 프롬프트 v1.3)
ca1ba40 feat: 품목별 체크 폼 API (form-schema, needs_check, 사람 값 우선 저장, 검색 필터)
c524be1 feat: 등록·검색 화면에 품목별 체크 폼 추가
7232b63 docs: 체크 폼 API 문서와 프롬프트 v1.3 회귀 측정 결과
(+ 이 문서 커밋)
```

### 2-2. 2026-11-16


| 영역 | 내용 |
|---|---|
| 경로 | DB `image_path`를 `uploads/<파일명>`으로 통일. 윈도우 역슬래시 경로도 읽힘. DB·업로드 경로를 실행 위치와 무관하게 고정 |
| DB 필드 | `device_model`, `device_model_candidates`(JSON), `identification_level`, `has_case`, `wallet_type`, `material`, `verification_needed`(JSON), `manufacturer`, 항목별 확신도 4개(`*_confidence`, 높음 0.9 / 보통 0.6 / 낮음 0.3) |
| 마이그레이션 | `migrations.py`: `PRAGMA user_version` 기반 v1~v6(11-25에 v7 추가), 단계별 트랜잭션, 실행 전 `findyu.db.bak-<시각>` 백업 |
| 라벨 | 품명 스마트폰/지갑/기타(11-25에 이어폰 추가), 색상 17개, 소재 목록 (`labels.py`). 기존 데이터도 변환 |
| Gemini 분석 | `gemini_analyzer.py`: response schema로 구조화 출력, 사진 1~5장, 429/5xx는 SDK 재시도 |
| 프롬프트 | `prompts/identify_item_v1.0.md`(팀 원본), `v1.1`(항목·형식 변경), `v1.2`, **`v1.3`(11-25부터 사용)** |
| 식별수준 | **백엔드가 결정**: `generation_evidence`(세대 구분 특징 + 사진 번호)가 있으면 확인, 없으면 추정, 기종이 없거나 품명 확신도가 낮으면 미확인. 보내지 않은 사진 번호를 댄 근거는 버림 |
| 여러 장 등록 | `item_images` 테이블(position 0 = 대표). `POST /items`에 `extra_images` 추가. 검색은 `items.image_path`(대표 사진) 기준 그대로 |
| 프론트 | 등록 화면에서 최대 5장 선택, 대표 사진 지정·삭제 |
| EXIF 회전 | 검색 임베딩·검색어 사진·등록 분석 모두 회전 반영. 기존 임베딩 3건(#2, #6, #7)은 v6에서 비운 뒤 서버 시작 시 재계산 |
| 외래키 | 연결마다 `PRAGMA foreign_keys=ON` → 물품 삭제 시 `item_images` 연쇄 삭제 |
| 측정 | `docs/model_comparison.md`, `docs/measurements/`, `backend/scripts/compare_models.py` |

### 커밋 목록 (오래된 순)

```
45ad1ea fix: 이미지 경로를 OS와 무관하게 저장·조회
21e5e32 feat: 휴대폰·지갑 전용 DB 필드와 자동 마이그레이션 추가
c60d0e3 feat: 품명·색상·소재 라벨 통일 및 기존 데이터 변환
c3acb26 feat: Gemini 기반 등록 분석 추가 (프롬프트 v1.1)
e2f43fb fix: 등록 분석 사진에 EXIF 회전 정보 반영
c329eac feat: 습득물 등록 시 사진 여러 장 저장 (item_images)
8111145 feat: 습득물 등록 화면에서 사진 여러 장 선택
b5629c4 docs: Gemini 3.5-flash / 3.8-flash 기종 판별 비교 결과
c58b969 feat: Gemini 기본 모델을 gemini-3.5-flash로 지정
4bcae7f feat: 식별수준 '확인' 기준을 세대 구분 특징으로 구체화
a134f5a fix: 검색 임베딩에도 EXIF 회전 반영 및 기존 임베딩 재계산
701838a feat: SQLite 외래키 활성화로 item_images 연쇄 삭제
190dde3 docs: 식별수준 기준 개정 후 gemini-3.5-flash 재측정 결과 추가
cb98b33 chore: 프론트엔드 package-lock.json 추가
feaca87 feat: 식별수준을 백엔드가 세대 구분 근거로 결정 (프롬프트 v1.2)
b85bfee chore: 모델 비교 스크립트에 반복 측정과 할당량 초과 시 중단 추가
8aa7129 docs: gemini-3.5-flash 프롬프트 v1.2 반복 측정 부분 결과 보관
bbd5ef1 docs: feature/phone-wallet 인수인계 문서 추가
d1f3595 docs: 앞선 모델 비교 측정 원본 3건 보관
```

---

## 3. 측정 현황

자세한 내용은 `docs/model_comparison.md`. 원본은 `docs/measurements/`.

| 측정 | 경로 | 프롬프트 | 결과 |
|---|---|---|---|
| 3.5 vs 3.8, 6개 조합 × 1회 | gemini 직접 | v1.1 | 3.8은 측면(액션 버튼) 판별이 좋았지만 느리고 504/429가 잦음 → 기본 모델 3.5-flash |
| 3.5 재측정 × 1회 | gemini 직접 | v1.1 개정 | 식별수준 6건 모두 "추정" → v1.2에서 백엔드가 결정하도록 변경 |
| 3.5 × 3회 (부분) | gemini 직접 | v1.2 | 4회 시도 후 429로 중단 (성공 2건은 아래 측정에 재사용) |
| **3.5 vs 3.8, 6개 조합 × 3회** | baze | v1.2 | 정답 3.5 **6/18**, 3.8 5/18. 오답 3 vs 5. 3.5의 "확인"은 오답 0/6. 평균 9.9s vs 24.1s. 오류 0 → **기본 모델 3.5-flash 유지** |
| **3.5 × 3회 (회귀 확인)** | baze | **v1.3** | 정답 **4/18**(v1.2 6/18), 측면 사진이 있는 조합 1/6(v1.2 3/6), "확인 + 오답" 1건 새로 나옴. 표본이 작아 편차인지 프롬프트 영향인지 미확정 |

공통 관찰
- 후면·전면 사진만으로는 15 Pro 세대를 한 번도 확정하지 못했다 (모두 "iPhone Pro 시리즈"). 측면 액션 버튼이 보일 때만 정답이 나온다 → 등록 화면 photo_hint가 측면 사진을 먼저 안내함
- iPhone 12 후면만은 3.5-flash가 매번 11로 답함 (정답은 대안후보에 있음)
- "iPhone Pro 시리즈"인데 Dynamic Island를 근거로 "확인"이 되는 경우가 있음 (4-7 참고)

---

## 4. 남은 작업

### 4-0. 게이트웨이 검색·수동 등록 — 2026-11-25 진행 중 (`feature/backend-gemini-search`)
해커톤 구현명세(백엔드 B1·B2) 기준. 자세한 계약은 `docs/API.md` "게이트웨이 검색", "수동 등록".
- **완료 (mock·테스트로 확인)**
  - `POST /items`의 `defer_analysis=true`: 등록 분석 호출 0회, 바로 `registered`
  - 등록 후 백그라운드에서 사진 임베딩(`gemini-embedding-2`, 256차원) 1회 시도, 실패하면 비워 둠. DB v8 `image_embedding_gemini`·`image_embedding_model` (기존 DINOv2 `embedding`과 분리)
  - 사진은 `image_url` 객체로 보내고 장당 토큰 1,000 초과면 오류 (글자로 처리되는 경우 방지)
  - `/search`(baze·mock): 체크 폼 필터 → 비교 후보 최대 10건(사진: 임베딩 상위 + 남은 자리 명세 순서 / 자연어: 명세 순서) → 검색 어댑터 1회 → ID 검증 → Top-5. 구형 점수 필드는 `null`, `rank`·`match_reasons`·`evaluated_count` 추가
  - baze·mock에서는 서버 시작·등록·검색에 로컬 모델(DINOv2·SigLIP2·Qwen)을 불러오지 않음. 기존 방식은 `FINDYU_SEARCH_ANALYZER_MODE=local`로 남김
  - 수동 백필 `backend/tools/backfill_gemini_embeddings.py` (호출 수를 보여주고 확인받은 뒤 실행, 서버 시작 시 자동 실행 안 함)
  - 테스트가 실제 DB를 쓰지 않도록 `FINDYU_DB_PATH`·`FINDYU_UPLOAD_DIR` 추가 (`tests/conftest.py`)
- **검색 모드 기본값은 `mock`** (`search_adapter.DEFAULT_MODE`). AI의 `search_analyzer.py`가 병합되면 `baze`로 바꾼다. 기존 `.env`를 쓰는 팀원이 병합 후 검색 503을 겪지 않게 하기 위함
- **실제 게이트웨이 확인 (2026-11-25, 호출 5회, 등록 분석 gemini-3.5-flash)**
  | 확인 | 결과 |
  |---|---|
  | 일반 등록 15 Pro (후면+측면) | 등록 → 분석·임베딩 완료 9.9초, 256차원 저장 |
  | 일반 등록 iPhone 12 (후면+전면) | 등록 → 분석·임베딩 완료 9.9초, 256차원 저장 |
  | 사진 검색 (15 Pro 측면 side1) 검색 사진 임베딩 | 1.9초. 후보 9건 중 임베딩 있는 2건: 15 Pro 0.909 > iPhone 12 0.700, 나머지 7건은 명세 순서(최신순)로 채움 |
  - 비교 단계는 `search_analyzer.py`가 없어 측정하지 못했다. **사진 검색 1회 전체 시간(임베딩 + 비교)은 어댑터 병합 후 측정 필요**
  - 기존 물품 7건은 사진 임베딩이 없다 → 필요하면 백필 도구 (`FINDYU_SEARCH_ANALYZER_MODE=baze`로 실행, 7건 = 게이트웨이 2회)
- **남은 것**
  - AI 담당의 `backend/search_analyzer.py` (함수 형태는 `docs/REQUESTS.md` 2026-11-25 요청). 병합되면 검색 기본값을 `baze`로
  - 실제 게이트웨이 확인: 사진 검색 전체 응답 시간(임베딩 + 비교), 자연어 검색, Argon 전환 (E2E-05)
  - 프론트: 점수 % 대신 순위·`match_reasons`, 분석 실패 시 `defer_analysis` (`docs/REQUESTS.md`)
- **공통 명세와 다른 점 (팀 결정)**: 사진 검색 후보를 명세 순서가 아니라 사진 임베딩 상위 10건으로 먼저 고른다
- 중단: `analysis_pending` 재시도는 명세 변경으로 중단. 로컬 브랜치 `feature/backend-analysis-pending`에만 커밋(push·PR 안 함)

### 4-1. 이어폰
- **실제 이어폰 사진으로 측정한 적이 없다.** 프롬프트 v1.3의 이어폰 분류·구성·보호커버 판단, 체크 폼 AI 값이 맞는지 확인 필요. 에어팟·버즈 사진(케이스 닫힘/열림, 커버 유무)을 `test_photos`에 추가하고 `compare_models.py`의 `COMBOS`에 조합을 넣을 것
- 이어폰 기종(예: AirPods Pro 2, Galaxy Buds2 Pro)을 체크 폼에 둘지 정해야 한다. 지금은 AI가 `device_model`을 채울 수는 있지만 이어폰 폼에는 기종 항목이 없다
- 이어폰의 세대 구분 특징(Step 4 같은 목록)이 없다
- v7 재분류는 설명·브랜드에 이어폰 단어가 있는 물품만 옮긴다. 로컬 DB #1(설명 "토끼 그림", 원래 품명 "이어폰 케이스")처럼 단서가 사라진 물품은 "기타"로 남는다

### 4-2. 체크 폼
- **v1.3 회귀:** 조합당 5회 이상으로 v1.2와 v1.3을 다시 비교할 것 (baze는 하루 한도 걱정이 없음). 차이가 유지되면 품목을 먼저 분류하고 품목별 프롬프트로 다시 부르는 방식, 또는 Step 4를 앞으로 옮기는 방식을 검토
- **프론트 화면 확인:** 2-1 참고. 특히 품목을 AI와 다르게 바꿨을 때 항목이 바뀌는지, 사진을 바꾸면 다시 분석되는지
- `analysis_id` 보관은 서버 메모리(1시간)다. 서버를 여러 개 띄우거나 재시작하면 등록 후 다시 분석한다 (AI 호출이 한 번 더 듦). 이때 사람이 고른 항목이 있고 품목을 직접 고르지 않았으면 400("품목을 선택해 주세요")이 난다
- "모르겠음"은 "답하지 않음"으로 처리한다. 습득자가 AI 값을 일부러 "모르겠음"으로 바꿔도 AI 값이 저장된다. 이 동작이 맞는지 팀에서 확인할 것
- 검색 필터는 습득물 쪽 값을 모르면 빼지 않는다. AI가 틀린 값(예: 색상)을 넣은 습득물은 필터에서 빠질 수 있다. needs_check였던 항목은 필터를 느슨하게 적용할지 검토
- `needs_check` 기준은 확신도·대안후보·null 여부만 본다. 케이스·카드지갑·구성 등은 확신도가 없어서 AI가 값을 냈으면 항상 false다
- 기종 필터는 문자열 비교다 (띄어쓰기·대소문자만 무시). "아이폰 15 프로" 같은 한글 입력은 일치하지 않는다

### 4-3. 목록 API (`GET /items`) — 2026-11-25 완료 (`feature/backend-list-api`)
- `GET /items`: `item_type`·`category`·`location`(부분 일치)·`status` 필터, `page`·`page_size`(기본 20, 최대 100), `sort`(newest/oldest). 응답이 배열에서 `{items, total, page, page_size, total_pages, has_next, sort, filters}` 객체로 바뀜
- `GET /items/locations`: 장소 필터 선택지(장소별 물품 수)
- 코드 `backend/item_list.py`, 테스트 `backend/tests/test_item_list.py`, 문서 `docs/API.md`
- 남은 것: 체크 폼 항목(색상·브랜드 등)으로 거르는 필터는 목록에 아직 없음 (`check_form.match_filters` 재사용 가능), 날짜 범위 필터 없음
- 프론트에는 아직 목록 화면이 없다. 대시보드 담당(`frontend/src/dashboard/`)이 이 API로 만든다

### 4-4. 점수 표시 수정 — 백엔드 2026-11-25 완료 (`feature/backend-similarity-score`), 프론트 남음
- 검색 결과 최종 점수를 `similarity_score`로 바꿈. `matching_score`·`similarity`는 같은 값의 이전 이름으로 남겨 둠 (프론트 전환 후 제거)
- `(cos + 1) / 2` 변환을 없애고 코사인 값을 그대로 씀 (`ai_retrieval.cosine_score`, 음수는 0). 로컬 데이터 7건 측정: 휴대폰 측면 사진으로 검색했을 때 관련 없는 물품 이미지 점수 0.49~0.67 → 0~0.35. SigLIP2 텍스트 점수는 0.03~0.15로 원래 작음
- 이미지·텍스트 사이 비중과 순위는 그대로지만, 장소·시간을 함께 입력하면 그 영향이 예전보다 커진다. 가중치(0.45/0.25/0.20/0.10)를 다시 정하려면 정답이 있는 검색 측정이 필요
- `POST /compare`의 `is_same_item`은 같은 기준 유지 (예전 0.8 = 코사인 0.6)
- **남은 것 (프론트)**: 후보 카드·대시보드가 아직 `matching_score`를 "%"로 보여준다. `similarity_score`로 바꾸고 순위나 높음/보통/낮음으로 표시 (`docs/REQUESTS.md`). 높음/보통/낮음 구간은 측정 필요

### 4-5. 503/429 대비 — 해커톤 명세에서는 재처리 큐 없이 수동 등록(`defer_analysis`)으로 대응 (4-0)
현재 동작:
- gemini 모드는 SDK가, baze 모드는 `baze_analyzer`가 429/5xx를 최대 3회 재시도 (`HttpRetryOptions`, 초기 2초, 최대 10초)
- 재시도 후에도 실패하면, 등록 분석 작업은 해당 습득물을 `analysis_failed`로 만듦 → **검색 대상에서 빠지고 자동으로 다시 분석되지도 않음**
- `/items/analyze`는 502를 반환

필요한 것:
- 하루 할당량 초과(429, "per day")는 재시도해도 소용없다. 이 경우 `analysis_failed` 대신 "분석 대기" 상태로 두고 나중에 다시 큐에 넣기
- 503(수요 과다)은 몇 분 뒤 재시도하면 될 가능성이 높으므로 지연 재시도 큐를 둘지 검토
- 분석에 실패해도 검색에서 빠지지 않게 할지 검토 (지금은 `status != analysis_failed`로 거름)
- 대체 분석기로 넘길지 검토 (`vlm` 모드 또는 아래 Azure 경로)

### 4-6. Azure 대체 경로 — 세부 사항 미정, 팀 논의 필요
- Gemini 장애나 할당량 소진 시 쓸 대체 분석 경로로 거론됨. 어떤 Azure 서비스와 모델을 쓸지는 정해지지 않았다.
- 붙일 위치: `main.py`의 `extract_item_info()`가 모드별로 분기한다 (`mock` / `vlm` / `gemini` / `baze`). `gemini_analyzer.py`와 같은 형태의 분석기 모듈을 추가하고 `EMPTY_ANALYSIS`와 같은 키를 반환하면 등록·저장 흐름은 그대로 쓸 수 있다.
- 프롬프트 v1.3과 응답 스키마(`IdentifyItemResult`)를 그대로 재사용할 수 있는지, 그리고 식별수준을 같은 기준으로 판단할 수 있는지 확인이 필요하다.

### 4-7. 하이브리드 검색 — 세부 사항 미정, 팀 논의 필요
- 현재 `/search`는 DINOv2(이미지) + SigLIP2(텍스트→이미지) 임베딩 점수에 장소·시간 점수를 가중합한다 (0.45 / 0.25 / 0.20 / 0.10).
- 2026-11-25부터 구조화 필드는 **체크 폼 필터(제외 조건)**로만 쓰인다 (`POST /search`의 `category`·`filters`). 순위 점수에는 아직 반영되지 않는다.
- 하이브리드 검색으로 검토할 것: 품명이나 기종 일치로 후보 필터링·가점, 식별수준과 확신도를 가중치에 반영, 검색어 파서(`ai_query_parser.py`) 결과를 구조화 필드와 맞추기
- 검색 임베딩은 여전히 대표 사진 1장 기준이다. 추가 사진(`item_images`)을 검색에도 쓸지 함께 정할 것

### 4-8. 식별수준 규칙 보완 (측정에서 나온 것)
- 기종이 "… 시리즈"(제품군)인데 근거가 있으면 "확인"이 된다 → 제품군이면 "추정"으로 둘지
- 근거 특징이 Step 4 목록(액션 버튼, 카메라 컨트롤, Dynamic Island, 평평한 측면)에 해당할 때만 "확인"으로 인정할지 (3.8-flash와 v1.3에서 목록에 없는 특징을 근거로 대고 틀린 경우가 있었음)

### 4-9. 기타 남은 것
- `generation_evidence`(세대 구분 근거)는 `/items/analyze` 응답에만 있고 **DB에는 저장하지 않는다.** 등록된 물품이 왜 "확인"인지 나중에 보려면 저장이 필요하다.
- `evidence`(식별근거)와 `same_item`(동일물품여부)도 DB에 저장하지 않는다.
- 1번 물품의 임베딩은 512차원이라 현재 모델(384차원)과 맞지 않는다. 검색할 때마다 파일에서 다시 계산한다 (오래된 데이터로 보임).
- 프론트는 식별수준·확신도를 아직 표시하지 않는다 (체크 폼 항목은 표시함).
- 물품 삭제 API는 없다. 외래키 연쇄 삭제는 준비됨. 삭제 기능을 만들 때 업로드 파일도 함께 지워야 한다.

---

## 5. API 할당량 상황

- **2026-11-25부터 기본 경로는 baze(팩트챗 게이트웨이)다.** 이날 측정 52회를 포함해 60회 남짓 호출하는 동안 한도 초과·5xx는 없었다. 게이트웨이의 사용량 한도는 확인하지 못했다
- 아래는 Gemini API 직접 호출(gemini 모드) 기준

- **Gemini 무료 등급: 하루 20회** (`generate_content_free_tier_requests`). 2026-11-16 측정 중 소진됨
- 비교 측정(조합 6개 × 3회 = 18회)만으로 하루 한도를 거의 다 쓴다
- **유료 등급 전환 여부: 팀 결정 대기.** 측정 확대나 실제 운영을 하려면 필요하다
- 할당량 오류 메시지에 요청한 모델(`gemini-3.5-flash`)이 아니라 `model: gemini-3.6-flash`로 표시됐다. 내부에서 다른 모델로 처리되는지는 확인하지 못했다. 응답 품질 비교에 영향이 있을 수 있으니 AI Studio에서 확인할 것
- 측정 시점 기준 모델 상태
  - `gemini-2.5-flash`: 신규 사용자 사용 불가 (404)
  - `gemini-3.8-flash`: 간단한 요청도 504가 잦고 느림 (평균 약 91초)
  - `gemini-3.5-flash`: 정상 (요청당 8~56초로 시점마다 편차가 큼, 가끔 503)

---

## 6. 팀에서 확인할 것

1. **세대 구분 특징 목록** (`prompts/identify_item_v1.3.md` Step 4, v1.2와 같음). 아래는 작업자 지식으로 작성했으므로 사실 확인이 필요하다.
   - 측면 액션 버튼: iPhone 15 Pro·Pro Max, iPhone 16 시리즈 이후
   - 측면 하단 카메라 컨트롤 버튼: iPhone 16 시리즈 이후
   - 전면 Dynamic Island: iPhone 14 Pro 이후, iPhone 15 이후
   - 평평한 측면 프레임: iPhone 12 이후
   - 갤럭시 등 다른 제조사의 세대 구분 특징은 아직 없음
2. **카메라 컨트롤 버튼의 16e 예외 여부.** 확실하지 않아서 프롬프트에 적지 않았다. 확인되면 Step 4에 추가할 것 (테스트 `test_prompt_has_generation_feature_rules`가 지금은 "16e"가 프롬프트에 없는지 검사하므로 함께 수정)
3. **유료 등급 전환 여부** (5번 참고)
4. **Gemini로 사진이 전송되는 것에 대한 개인정보 검토.** 무료 등급에서는 입력이 학습에 쓰일 수 있다. baze 게이트웨이(학교 팩트챗)를 거칠 때의 데이터 처리 방침도 확인할 것. 프롬프트에 "개인정보를 출력하지 말라"는 규칙은 있지만 사진 자체는 전송된다.
5. **`findyu.db`를 계속 git으로 관리할지.** 지금은 원본(v0)이 커밋돼 있고 각자 자동 마이그레이션한다.
6. **체크 폼 항목 구성.** 지갑은 요청된 3개(종류·소재·색상)에 4~6개 기준을 맞추려고 "여밈 방식"을 추가했다. 휴대폰 브랜드 선택지는 애플/삼성/기타뿐이다
7. **"모르겠음" 처리 방식** (4-2 참고)
