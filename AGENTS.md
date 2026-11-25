# FindYU — AI 에이전트 공통 작업 규칙

> 이 파일은 팀원 5명의 코딩 에이전트(Codex 4명, Claude Code 1명)가 **공통으로 읽는 규칙**이다.
> Codex는 `AGENTS.md`를, Claude Code는 `CLAUDE.md`(이 파일을 불러옴)를 읽는다.
> 이 파일을 고칠 수 있는 사람은 PM(최인구)뿐이다. 에이전트는 이 파일을 수정하지 않는다.

---

## 0. 세션을 시작하면 가장 먼저 할 일

1. 사용자의 첫 메시지에서 **담당 역할**을 확인한다. (예: `역할: 프론트엔드`)
   - 역할이 없으면 작업하기 전에 "어느 역할로 작업할까요? (PM / AI / 백엔드 / 프론트엔드 / 대시보드)"라고 먼저 묻는다.
2. 아래 **3. 역할별 담당 범위**에서 내 역할이 수정할 수 있는 경로를 확인한다.
3. `git status`와 `git branch --show-current`로 현재 브랜치를 확인한다. `main`이면 작업하지 말고 사용자에게 알린다. 작업 브랜치는 최신 `main`에서 만든다.
4. `docs/API.md`가 있으면 먼저 읽는다. 프론트·대시보드·AI는 이 문서를 기준으로 백엔드와 연결한다.
5. `docs/spec/00_공통.md`와 자기 역할 명세를 읽는다.

---

## 1. 프로젝트 요약

- **FindYU**: 영남대 캠퍼스 분실물·습득물 AI 매칭 웹 서비스
- **대상 품목**: 휴대폰 · 블루투스 이어폰 · 지갑 (3개만)
- **습득자**: 사진 2장 업로드 → AI가 품목별 체크 폼을 미리 채움 → 습득자는 틀린 것만 고침(애매한 항목은 "확인해주세요" 강조) → 장소·시간 입력 → 등록
- **분실자**: 사진 또는 자연어 + 같은 체크 폼 → 체크한 항목으로 거르고, 이미지 유사도로 순위 → Top-K 후보 → 본인이 최종 판단
- **통합 Dashboard**: 전체 습득물 최신순 목록, 장소·품목 필터, 상세 보기
- **해커톤**: 2026-11-29(일) 10:00~17:00, 발표 15:00경 시작(4분 + 질의응답 2분). **팀 내부 기능 동결 14:00**

### 품목별 규칙
| 품목 | 촬영 가이드(2장) | AI가 판단하는 것 | 사람이 정하는 것 |
|---|---|---|---|
| 휴대폰 | 후면 + 측면 | 제조사, 기종 후보, 식별수준, 색상, 케이스 유무, 카드지갑 부착 | 틀린 항목 수정 |
| 이어폰 | 케이스 닫힌 정면 + **이어버드를 꺼내 케이스 옆에 나란히 둔 사진** (꺼내기 어려우면 뚜껑 연 상태) | 색상, 구성(케이스+이어버드/케이스만/이어버드만), 보호커버, 이어팁·스티커 등 개인 특징 | **브랜드: 애플/삼성/기타/모르겠음** (기종·세대는 판별하지 않음) |
| 지갑 | 바깥면 + 펼친 면(카드·신분증 안 보이게) | 종류(장지갑/반지갑/카드지갑), 소재, 색상, 여밈 방식(지퍼/똑딱이/없음) | 틀린 항목 수정 |

---

## 2. 기술 구성과 실행 방법

| 영역 | 기술 | 위치 |
|---|---|---|
| Backend | Python, FastAPI, SQLAlchemy, SQLite | `backend/` |
| 등록 분석 AI | 학교 BAZE API(OpenAI 호환) → Gemini 계열 (개발 `gemini-3.8-flash` / 실사용 `gemini-4-argon`) | `backend/*_analyzer.py`, `backend/prompts/` |
| 검색 AI | BAZE 임베딩(`gemini-embedding-2`) 1차 선별 + Gemini 비교(순위·근거) | `backend/gemini_embedding.py`, `backend/search_candidates.py`, `backend/search_adapter.py`, `backend/search_analyzer.py` |
| 로컬 검색 | DINOv2·SigLIP2 (`FINDYU_SEARCH_ANALYZER_MODE=local` 비상용) | `backend/ai_retrieval.py`, `backend/search_graph.py`, `backend/ai_query_parser.py` |
| Frontend | React 18 + Vite | `frontend/` |

```bash
# 백엔드
cd backend
cp .env.example .env            # 각자 팩트챗에서 발급받은 BAZE 키를 넣는다
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload     # http://localhost:8000/docs
.venv/bin/python -m pytest tests        # 테스트(API 키 없이 동작)

# 프론트엔드
cd frontend && npm install && npm run dev   # http://localhost:5173
```

- 등록 분석 모드: `FINDYU_REGISTRATION_ANALYZER_MODE` = `mock` | `vlm` | `gemini` | `baze`
- 검색 모드: `FINDYU_SEARCH_ANALYZER_MODE` = `mock` | `baze` | `local`
- **개발·테스트 중에는 `mock` 모드를 쓴다.** 코드와 `.env.example`의 기본값은 `baze`이므로, `backend/.env`에서 `FINDYU_REGISTRATION_ANALYZER_MODE=mock`으로 바꾼다. 실제 API는 기능 확인이 필요할 때만 호출한다.
- 검색어 해석(`FINDYU_QUERY_PARSER_MODE`)도 기본값 `llm`은 로컬 Qwen3 모델을 내려받아 실행한다. 가볍게 돌리려면 `mock`으로 둔다.
- `findyu.db`는 서버 시작 시 자동 마이그레이션된다. 직접 수정하지 않는다.

---

## 3. 역할별 담당 범위

**자기 담당 경로만 수정한다.** 다른 사람 경로를 고쳐야 하면 직접 고치지 말고 **4. 영역 밖 변경 요청** 절차를 따른다.

| 역할 | 담당자 | 에이전트 | 수정 가능한 경로 | 이번 해커톤 핵심 작업 |
|---|---|---|---|---|
| **PM·통합** | 최인구 | Codex | `docs/`(API.md 제외), `README.md`, `AGENTS.md`, `CLAUDE.md`, `demo/` | 통합 테스트, 시연 시나리오, 시연 데이터·정답표, 발표 자료, PR 병합 |
| **AI** | 최준서 | Codex | `backend/prompts/`, `backend/*_analyzer.py`, `backend/scripts/`, `docs/model_comparison.md`, `docs/measurements/` | 프롬프트 개선, 분석 결과 검증, 정답표 기반 성능 측정, 검색 비교 어댑터 `backend/search_analyzer.py` |
| **백엔드·DB** | 권기백 | **Claude Code** | `backend/` 전체(위 AI 경로 제외), `docs/API.md` | 목록 API 필터·페이지, 검색 점수 `similarity_score`로 변경, API 실패 시 `analysis_pending` |
| **프론트엔드** | 김승보 | Codex | `frontend/` (단, `frontend/src/dashboard/` 제외) | 등록·검색 화면, 품목별 체크 폼, 촬영 가이드, 결과 비교 화면 |
| **대시보드** | 이수형 | Codex | `frontend/src/dashboard/` | 전체 습득물 최신순 목록, 장소·품목 필터, 상세 페이지, 발표용 통계 |

### 경계가 겹치는 파일
| 파일 | 주인 | 규칙 |
|---|---|---|
| `backend/labels.py` | 백엔드 | 품목·색상·소재 목록의 **유일한 기준**. 프론트와 AI는 이 값을 그대로 쓴다 |
| `backend/main.py` | 백엔드 | AI가 분석기를 새로 붙일 때는 분석기 모듈만 만들고, `main.py` 연결은 백엔드에게 요청 |
| `frontend/src/App.jsx` | 프론트엔드 | 대시보드는 `frontend/src/dashboard/` 안에서만 만들고, `App.jsx`에 화면을 연결하는 한 줄은 프론트엔드에게 요청 |
| `docs/API.md` | 백엔드 | API의 **유일한 계약서**. 백엔드가 API를 바꾸면 같은 커밋에서 이 문서도 고친다 |

---

## 4. 영역 밖 변경 요청

다른 담당 경로를 고쳐야 할 때는 **직접 고치지 않는다.** 대신:

1. 무엇이, 왜 필요한지 3줄 이내로 정리해 사용자에게 보여준다.
2. 사용자가 해당 담당자에게 전달하거나, `docs/REQUESTS.md`에 아래 형식으로 한 줄 추가한다(이 파일은 누구나 추가만 가능).
   ```
   - [요청자→담당] 내용 / 이유 / 급함·보통
   ```
3. 그동안은 mock 데이터나 임시 값으로 내 작업을 계속한다.

---

## 5. Git 규칙

- 작업 브랜치: `feature/<역할>-<기능>` (예: `feature/frontend-checkform`, `feature/dashboard-list`)
- **시작 기준 브랜치: `main`.** 작업 시작 전 `git checkout main && git pull origin main` 후 작업 브랜치를 만든다
- **PR 대상: `main`.** 병합은 PM이 한다.
- **절대 하지 않는 것**
  - `main`에 직접 push
  - `git push --force`, `git reset --hard`로 남의 커밋 지우기
  - 남의 브랜치에 커밋
- 커밋은 기능 단위로 작게. 메시지 형식: `feat:`, `fix:`, `docs:`, `chore:` + 한국어 설명
- 다른 브랜치와 충돌하면 임의로 해결하지 말고, 충돌 파일과 양쪽 변경 내용을 사용자에게 보여준 뒤 결정을 받는다.

---

## 6. 절대 커밋하지 않는 것

| 대상 | 이유 |
|---|---|
| `backend/.env`, API 키 문자열 | 키 노출. 코드·로그·문서·커밋 메시지 어디에도 키를 적지 않는다 |
| `backend/findyu.db` 변경분 | 자동 마이그레이션으로 처리 |
| `backend/uploads/` 새 사진, `test_photos/` | 개인정보·용량 |
| `node_modules/`, `.venv/`, `findyu.db.bak-*` | 빌드·백업 산출물 |

커밋 전에 `git diff --staged`로 위 항목이 섞이지 않았는지 확인한다.

---

## 7. 제품 원칙 (모든 역할 공통)

1. **모르면 지어내지 않는다.** AI가 확실하지 않은 제조사·기종은 `null` 또는 "미확인"으로 둔다.
2. **점수를 확률처럼 보여주지 않는다.** 검색 결과는 순위와 `match_reasons`로 보여주고 점수를 %로 보여주지 않는다.
3. **최종 판단은 사람이 한다.** 소유권을 AI가 확정하지 않는다.
4. **사람이 고른 값이 AI 값보다 우선이다.**
5. **개인정보를 화면·응답·로그에 그대로 내보내지 않는다.** 전화번호, 학번, 이름, 카드번호, 기기 일련번호(이어폰 뚜껑 안쪽 등)는 출력하지 않는다.
6. **측정하지 않은 숫자는 쓰지 않는다.** 정확도·속도 등은 `docs/model_comparison.md`의 실측값만 인용하고, 없으면 "측정 필요"로 적는다.

---

## 8. API 사용 규칙

- 키는 각자 팩트챗에서 **본인 키를 발급**받아 `backend/.env`에만 둔다. 키를 서로 공유하지 않는다.
- 테스트는 `mock` 모드로. 실제 호출이 필요한 테스트는 한 번에 몇 건만 돌린다.
- 실제 사진 테스트에는 개인정보가 보이지 않는 사진만 쓴다.
- API가 429/503으로 실패하면 반복 재시도하지 말고, 실패를 사용자에게 알리고 다음 작업으로 넘어간다.

---

## 9. 해커톤 당일 운영

| 시각 | 할 일 |
|---|---|
| 10:00 | 각자 `main` 최신화 후 작업 브랜치 생성 |
| 12:00 | 1차 PR(동작하는 최소 기능) → PM 병합 → 전체 흐름 1회 테스트 |
| **14:00** | **기능 동결.** 이후로는 버그 수정과 시연 준비만 |
| 14:30 | 시연 리허설(사전 등록 데이터로), 녹화 영상 백업 |
| 15:00 | 발표 |

- 기능 동결 이후 에이전트에게 새 기능을 요청받으면 "기능 동결 시간 이후입니다"라고 알리고 사용자 확인을 받는다.
- 시연은 **미리 분석해 둔 물품**으로 하고, 실시간 등록은 1건만 보여준다(API 지연·실패 대비).

---

## 10. 답변 방식

- 한국어로 답한다. 결론을 먼저 말한다.
- 작업이 끝나면: 바꾼 파일, 실행·테스트 결과, 사용자가 확인할 점, 다른 담당자에게 전달할 내용을 짧게 정리한다.
- 확인하지 못한 내용은 "확인 필요"로 표시한다.
