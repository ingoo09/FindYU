# FindYU 해커톤 역할별 시작 프롬프트

**최신 `main`의 FindYU 작업 사본을 열고**, 아래에서 자기 역할의 코드 블록 하나를 복사해 첫 메시지로 보낸다. 문서가 작업 사본에 있으면 프롬프트에 적힌 경로를 에이전트가 읽을 수 있다. 별도로 첨부한다면 [README 변경표](README.md), [공통 명세](00_공통.md), [5시간 실행 계획](plans/2026-11-25-findyu-hackathon.md), 자기 역할 명세 1개를 전달한다.

| 역할 | 도구 | 역할 명세 | 실행 계획 |
|---|---|---|---|
| 최인구 · PM·통합 | Codex | [01_PM_통합.md](01_PM_통합.md) | 작업 1·9 |
| 최준서 · AI | Codex | [02_AI.md](02_AI.md) | 작업 2 |
| 권기백 · 백엔드·DB | Claude Code | [03_백엔드_DB.md](03_백엔드_DB.md) | 작업 3·4, 작업 9의 백필 |
| 김승보 · 프론트엔드 | Codex | [04_프론트엔드.md](04_프론트엔드.md) | 작업 5·6·8 |
| 이수형 · Dashboard | Codex | [05_Dashboard.md](05_Dashboard.md) | 작업 7 |

[팀원 준비·전달 체크리스트](plans/2026-11-25-findyu-team-inputs.md)는 사람이 확인한다. FactChat 호출자가 키를 자기 서버의 `backend/.env`에 직접 설정한다. 프롬프트에는 **설정됨 / 미설정**만 적는다. 실호출 준비가 막히면 `mock`으로 맡은 작업을 먼저 검증한다.

## 최인구 · PM·통합 · Codex

```text
내 역할은 최인구 PM·통합이다. FindYU의 5시간 해커톤 구현을 시작해줘.

저장소 AGENTS.md, docs/spec/README.md의 변경표, docs/spec/00_공통.md,
docs/spec/01_PM_통합.md, docs/spec/plans/2026-11-25-findyu-hackathon.md를 읽고
요청·응답은 최신 docs/API.md를 기준으로 확인해줘. 최신 main의 SHA와 현재 브랜치를 확인하고,
이미 병합된 기능을 각 역할에 중복 배정하지 말아줘.

작업 1과 9를 맡아줘. 착수 후 20분 안에 역할별 브랜치·API 계약·시연 환경을 정리해줘.
AI compare 어댑터 → 백엔드 실호출·검색 모드 전환 → 프론트 API 검증 순서와,
Dashboard 모듈 → 프론트 홈 연결 순서를 관리해줘. 백엔드와 시연 복사본의 백필 대상·호출 수를 공유하고,
T+4:00에 기능을 동결한 뒤 E2E-01~05, 모델별 확인 결과, 시연 SHA, 녹화 위치를 정리해줘.

첫 답변에는 현재 상태와 각 담당자가 지금 시작할 작업을, 마지막에는 실제 확인 결과와 남은 항목을 한국어로 적어줘.
```

## 최준서 · AI · Codex

```text
내 역할은 최준서 AI다. FindYU의 실행 계획 작업 2를 시작해줘.

저장소 AGENTS.md, docs/spec/README.md의 변경표, docs/spec/00_공통.md,
docs/spec/02_AI.md, docs/spec/plans/2026-11-25-findyu-hackathon.md와 최신 docs/API.md를 읽어줘.
작업 브랜치와 기준 SHA를 확인하고 AI 소유 파일에서 작업해줘.

backend/search_analyzer.py의 compare(query, candidates)를 구현하거나 이미 있으면 계약을 검증해줘.
백엔드가 고른 최대 10건을 받아 후보 ID와 match_reasons를 구조화 JSON으로 한 번 비교해줘.
사진 임베딩과 후보 선별은 백엔드가 수행한다. 기존 등록 분석과 FactChat 설정을 재사용하고,
개발은 gemini-3.8-flash, 실사용 검증은 gemini-4-argon으로 해줘. 내 키 상태는 [설정됨 / 미설정]이다.

실행한 테스트, 확인한 모델, 정상·오류 응답 예시와 백엔드 인수 사항을 한국어로 정리해줘.
```

## 권기백 · 백엔드·DB · Claude Code

```text
내 역할은 권기백 백엔드·DB다. FindYU의 실행 계획 작업 3·4와 작업 9의 백필을 맡아줘.

저장소 CLAUDE.md와 AGENTS.md, docs/spec/README.md의 변경표, docs/spec/00_공통.md,
docs/spec/03_백엔드_DB.md, docs/spec/plans/2026-11-25-findyu-hackathon.md와 최신 docs/API.md를 읽어줘.
작업 브랜치와 기준 SHA를 확인하고 백엔드 소유 파일에서 작업해줘.

수동 등록, SQLite v8, 사진 임베딩 선별, 목록·상세 API를 재사용해줘. 사진은 gemini-embedding-2@256 상위와
기존 순서 보완으로 최대 10건을 보내고, 자연어는 기존 선별 순서를 써줘. AI 어댑터가 병합되면 실호출을
확인한 뒤 검색 기본값을 mock에서 baze로 변경하고 docs/API.md를 같은 변경에 맞춰줘.
백필은 시연 DB·사진 복사본에서 --dry-run으로 대상과 호출 수부터 확인해줘. 내 키 상태는 [설정됨 / 미설정]이다.

실행한 테스트, 변경한 계약, 프론트·PM 전달 사항과 아직 확인하지 못한 항목을 한국어로 정리해줘.
```

## 김승보 · 프론트엔드 · Codex

```text
내 역할은 김승보 프론트엔드다. FindYU의 실행 계획 작업 5·6·8을 맡아줘.

저장소 AGENTS.md, docs/spec/README.md의 변경표, docs/spec/00_공통.md,
docs/spec/04_프론트엔드.md, docs/spec/plans/2026-11-25-findyu-hackathon.md와 최신 docs/API.md를 읽어줘.
작업 브랜치와 기준 SHA를 확인하고 Dashboard 폴더 외 프론트 소유 파일에서 작업해줘.

기존 화면에 기본 사진 2장·보완 최대 3장 검사, 분석 실패 시 defer_analysis=true 수동 등록을 연결해줘.
검색 결과는 API 배열 순서와 match_reasons를 보여주고, 임베딩 선별 정보로 다시 정렬하지 말아줘.
등록·검색을 mock으로 먼저 검증하고 Dashboard 모듈 병합 뒤 App.jsx의 홈에 연결해줘.

빌드·브라우저 검증 결과와 Dashboard·PM 인수 사항을 한국어로 정리해줘.
```

## 이수형 · Dashboard · Codex

```text
내 역할은 이수형 Dashboard다. FindYU의 실행 계획 작업 7을 시작해줘.

저장소 AGENTS.md, docs/spec/README.md의 변경표, docs/spec/00_공통.md,
docs/spec/05_Dashboard.md, docs/spec/plans/2026-11-25-findyu-hackathon.md와 최신 docs/API.md를 읽어줘.
작업 브랜치와 기준 SHA를 확인하고 frontend/src/dashboard/ 안에서 작업해줘.

FoundItemsDashboard를 기본 export하고 apiUrl·assetUrl을 props로 받아줘.
기존 API로 습득물 최신순, 장소·품목 복합 필터, 페이지 이동, 상세 보기를 구현해줘.
컴포넌트 경로와 props를 김승보에게 전달하고 App.jsx의 홈 연결은 프론트 담당자에게 맡겨줘.

목록·필터·상세 확인 결과와 인수 항목을 한국어로 정리해줘.
```
