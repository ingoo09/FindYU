# 인수인계 — feature/phone-wallet (2026-11-16)

대상 물품을 **스마트폰·지갑**으로 좁히면서 백엔드·DB와 등록 분석(Gemini)을 바꾼 작업의 인수인계 문서.
브랜치: `feature/phone-wallet` (`demo/midterm`에서 분기). **push하지 않은 상태.**

---

## 1. 빠른 시작

```bash
cd backend
cp .env.example .env          # GEMINI_API_KEY 입력 (모델은 비우면 gemini-3.5-flash)
.venv/bin/uvicorn main:app    # 첫 실행 시 findyu.db 자동 마이그레이션(v1~v6)
.venv/bin/python -m pytest tests   # 단위 테스트 (API 키 불필요)
```

- 등록 분석 모드: `FINDYU_REGISTRATION_ANALYZER_MODE=mock | vlm | gemini`
- Gemini 모델 변경: `FINDYU_GEMINI_MODEL=gemini-3.8-flash` 등
- API 키가 없어도 서버는 뜬다. 분석 요청만 503과 함께 "GEMINI_API_KEY가 없습니다" 메시지로 실패한다. 상태는 `GET /`의 `registration_gemini`에서 확인할 수 있다.
- `backend/.venv`에 이번에 추가로 설치한 패키지: `langgraph`, `accelerate`, `pytest`, `google-genai`, `python-dotenv` (`requirements.txt`에 반영됨)

### 커밋하지 않은 것 (의도적)

| 대상 | 이유 |
|---|---|
| `backend/findyu.db` | 서버 시작 시 자동 마이그레이션으로 처리. 원본(v0)에서 v1~v6이 적용되는 것을 깨끗한 clone으로 확인함 |
| `backend/.env` | API 키 (`.gitignore`) |
| `test_photos/` | 테스트 사진 (`.git/info/exclude`) |

---

## 2. 오늘 한 작업

| 영역 | 내용 |
|---|---|
| 경로 | DB `image_path`를 `uploads/<파일명>`으로 통일. 윈도우 역슬래시 경로도 읽힘. DB·업로드 경로를 실행 위치와 무관하게 고정 |
| DB 필드 | `device_model`, `device_model_candidates`(JSON), `identification_level`, `has_case`, `wallet_type`, `material`, `verification_needed`(JSON), `manufacturer`, 항목별 확신도 4개(`*_confidence`, 높음 0.9 / 보통 0.6 / 낮음 0.3) |
| 마이그레이션 | `migrations.py`: `PRAGMA user_version` 기반 v1~v6, 단계별 트랜잭션, 실행 전 `findyu.db.bak-<시각>` 백업 |
| 라벨 | 품명 스마트폰/지갑/기타, 색상 17개, 소재 목록 (`labels.py`). 기존 데이터도 변환 |
| Gemini 분석 | `gemini_analyzer.py`: response schema로 구조화 출력, 사진 1~5장, 429/5xx는 SDK 재시도 |
| 프롬프트 | `prompts/identify_item_v1.0.md`(팀 원본), `v1.1`(항목·형식 변경), **`v1.2`(현재 사용)** |
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
(+ 이 문서 커밋)
```

---

## 3. 측정 현황

| 측정 | 프롬프트 | 결과 |
|---|---|---|
| 3.5-flash vs 3.8-flash, 6개 조합 × 1회 | v1.1 | `docs/model_comparison.md` 앞부분. 3.8은 측면 사진(액션 버튼) 판별이 좋았지만 느리고 504/429가 잦음 → 기본 모델 3.5-flash |
| 3.5-flash 재측정, 6개 조합 × 1회 | v1.1 개정 | 같은 문서 "재측정" 절. 식별수준은 6건 모두 "추정"이라 정답·오답을 구분하지 못함 → v1.2에서 백엔드가 결정하도록 변경 |
| **3.5-flash, 6개 조합 × 3회** | **v1.2** | **18회 중 4회 시도 후 429로 중단.** 정상 응답 2건, 503 1건, 429 1건. 원본: `docs/measurements/2026-11-16_gemini-3.5-flash_prompt-v1.2_x3_partial.json` |

v1.2 부분 결과 2건 (판단 근거로는 부족):
- 15 Pro 후면만, 15 Pro 후면+측면 모두 "iPhone Pro 시리즈 / 추정 / 세대 구분 근거 없음"
- 추가확인필요사항이 의도대로 바뀜: "설정 메뉴 확인" 같은 일반 항목 대신 "측면 사진 없음 (액션 버튼 여부 확인 불가)"처럼 사진에서 실제로 부족한 것만 나옴
- 후면+측면에서 이번에는 "케이스 때문에 액션 버튼 구별 불가"라고 답함 (v1.1 측정에서는 같은 조합에서 액션 버튼을 찾아 정답을 맞힘) → 회차마다 결과가 달라지므로 반복 측정이 꼭 필요함

---

## 4. 남은 작업

### 4-1. 측정 이어하기 (`--resume`) — 미구현
- 지금 `compare_models.py`는 항상 처음부터 돈다. 이미 성공한 (회차, 조합)은 건너뛰고 실패·미측정분만 돌리는 `--resume <기존 결과 json>` 옵션이 필요하다.
- 503/504로 실패한 회차를 마지막에 다시 돌려 조합당 3회를 채우는 기능도 함께 넣을 것
- 완료 후 `docs/model_comparison.md`에 다음을 정리:
  - 조합별 정답률 (3회 중 몇 회)
  - 세대 구분 근거가 **있었을 때 / 없었을 때** 정답률
  - 식별수준(확인/추정/미확인)별 정답률
- 집계 기준: 기종이 정답과 정확히 일치할 때만 정답. "iPhone Pro 시리즈"처럼 제품군만 맞힌 경우는 따로 셈
- **하루 무료 한도 20회 안에 18회를 돌려야 하므로**, 측정하는 날에는 다른 Gemini 호출을 하지 말 것

### 4-2. 503/429 대비
현재 동작:
- SDK가 429/5xx를 최대 3회 재시도 (`HttpRetryOptions`, 초기 2초, 최대 10초)
- 재시도 후에도 실패하면, 등록 분석 작업은 해당 습득물을 `analysis_failed`로 만듦 → **검색 대상에서 빠지고 자동으로 다시 분석되지도 않음**
- `/items/analyze`는 502를 반환

필요한 것:
- 하루 할당량 초과(429, "per day")는 재시도해도 소용없다. 이 경우 `analysis_failed` 대신 "분석 대기" 상태로 두고 나중에 다시 큐에 넣기
- 503(수요 과다)은 몇 분 뒤 재시도하면 될 가능성이 높으므로 지연 재시도 큐를 둘지 검토
- 분석에 실패해도 검색에서 빠지지 않게 할지 검토 (지금은 `status != analysis_failed`로 거름)
- 대체 분석기로 넘길지 검토 (`vlm` 모드 또는 아래 Azure 경로)

### 4-3. Azure 대체 경로 — 세부 사항 미정, 팀 논의 필요
- Gemini 장애나 할당량 소진 시 쓸 대체 분석 경로로 거론됨. 어떤 Azure 서비스와 모델을 쓸지는 정해지지 않았다.
- 붙일 위치: `main.py`의 `extract_item_info()`가 모드별로 분기한다 (`mock` / `vlm` / `gemini`). `gemini_analyzer.py`와 같은 형태의 분석기 모듈을 추가하고 `EMPTY_ANALYSIS`와 같은 키를 반환하면 등록·저장 흐름은 그대로 쓸 수 있다.
- 프롬프트 v1.2와 응답 스키마(`IdentifyItemResult`)를 그대로 재사용할 수 있는지, 그리고 식별수준을 같은 기준으로 판단할 수 있는지 확인이 필요하다.

### 4-4. 하이브리드 검색 — 세부 사항 미정, 팀 논의 필요
- 현재 `/search`는 DINOv2(이미지) + SigLIP2(텍스트→이미지) 임베딩 점수에 장소·시간 점수를 가중합한다 (0.45 / 0.25 / 0.20 / 0.10).
- **이번에 추가한 구조화 필드(품명, 색상, 제조사, 기종, 케이스 유무, 지갑 종류, 소재)는 아직 검색 순위에 쓰이지 않는다.**
- 하이브리드 검색으로 검토할 것: 품명이나 기종 일치로 후보 필터링·가점, 식별수준과 확신도를 가중치에 반영, 검색어 파서(`ai_query_parser.py`) 결과를 구조화 필드와 맞추기
- 검색 임베딩은 여전히 대표 사진 1장 기준이다. 추가 사진(`item_images`)을 검색에도 쓸지 함께 정할 것

### 4-5. 기타 남은 것
- `generation_evidence`(세대 구분 근거)는 `/items/analyze` 응답에만 있고 **DB에는 저장하지 않는다.** 등록된 물품이 왜 "확인"인지 나중에 보려면 저장이 필요하다.
- `evidence`(식별근거)와 `same_item`(동일물품여부)도 DB에 저장하지 않는다.
- 1번 물품의 임베딩은 512차원이라 현재 모델(384차원)과 맞지 않는다. 검색할 때마다 파일에서 다시 계산한다 (오래된 데이터로 보임).
- 프론트는 새 필드(기종, 식별수준, 확신도 등)를 아직 표시하지 않는다. 품명·색상도 자유 입력이라 목록에 없는 색은 "미확인"으로 저장된다.
- 물품 삭제 API는 없다. 외래키 연쇄 삭제는 준비됨. 삭제 기능을 만들 때 업로드 파일도 함께 지워야 한다.

---

## 5. API 할당량 상황

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

1. **세대 구분 특징 목록** (`prompts/identify_item_v1.2.md` Step 4). 아래는 작업자 지식으로 작성했으므로 사실 확인이 필요하다.
   - 측면 액션 버튼: iPhone 15 Pro·Pro Max, iPhone 16 시리즈 이후
   - 측면 하단 카메라 컨트롤 버튼: iPhone 16 시리즈 이후
   - 전면 Dynamic Island: iPhone 14 Pro 이후, iPhone 15 이후
   - 평평한 측면 프레임: iPhone 12 이후
   - 갤럭시 등 다른 제조사의 세대 구분 특징은 아직 없음
2. **카메라 컨트롤 버튼의 16e 예외 여부.** 확실하지 않아서 프롬프트에 적지 않았다. 확인되면 Step 4에 추가할 것 (테스트 `test_prompt_has_generation_feature_rules`가 지금은 "16e"가 프롬프트에 없는지 검사하므로 함께 수정)
3. **유료 등급 전환 여부** (5번 참고)
4. **Gemini로 사진이 전송되는 것에 대한 개인정보 검토.** 무료 등급에서는 입력이 학습에 쓰일 수 있다. 프롬프트에 "개인정보를 출력하지 말라"는 규칙은 있지만 사진 자체는 전송된다.
5. **`findyu.db`를 계속 git으로 관리할지.** 지금은 원본(v0)이 커밋돼 있고 각자 자동 마이그레이션한다.
