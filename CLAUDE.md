@AGENTS.md

# CLAUDE.md — 백엔드·DB (Claude Code)

> 공통 규칙은 위에서 불러온 `AGENTS.md`를 따른다. 이 파일은 Claude Code 사용자에게만 적용되는 내용이다.

## 1. 사용자와 역할

- 이 저장소에서 Claude Code를 쓰는 사람은 **권기백(백엔드·DB)**이다.
- 첫 메시지에 역할 지정이 없으면 **백엔드·DB 역할로 작업한다.** (`AGENTS.md` 0절의 역할 질문은 생략)
- 수정 가능 경로
  - `backend/` 전체. **단 `backend/prompts/`, `backend/*_analyzer.py`, `backend/scripts/`는 AI 담당**이므로 수정하지 않는다
  - `docs/API.md`
- 사용자는 코드를 직접 쓰지 않고 **설계 이해와 리뷰**에 집중한다. 작업이 끝나면 무엇을 왜 바꿨는지 리뷰하기 쉽게 설명한다.
  - 바꾼 파일별로 무엇을 바꿨는지, 왜 그렇게 설계했는지
  - 다른 방법이 있었다면 왜 이 방법을 골랐는지
  - 리뷰할 때 특히 봐야 할 부분과 확인하지 못한 것

## 2. 백엔드 작업 원칙

1. **API를 바꾸면 같은 커밋에서 `docs/API.md`를 고친다.** 요청·응답 예시 JSON을 넣는다.
2. **필드 이름과 선택지는 `backend/labels.py`가 기준이다.** 바꾸면 `backend/tests/test_labels.py`도 고친다.
3. **DB 구조를 바꾸면 `backend/migrations.py`에 새 버전을 추가한다.** 저장소의 원본 `findyu.db`로 기존 데이터가 깨지지 않는지 확인한다.
4. **기능을 추가하면 `backend/tests/`에 테스트를 추가**하고 `.venv/bin/python -m pytest tests` 통과를 확인한다.
5. **다른 담당 영역에 영향이 있으면 직접 고치지 않고** `docs/REQUESTS.md`에 요청을 남긴다 (`AGENTS.md` 4절 형식).

## 3. 남은 할 일

완료:
- `GET /items` 목록·필터·페이지네이션, `/items/locations`
- `GET /form-schema`, 분석 응답 `needs_check`·`photo_hint`
- 검색 필터(`filters`·`filter_check`), `similarity_score` 전환
- 이어폰 품목·마이그레이션
- `defer_analysis` 수동 등록, 사진 임베딩(DB v8), 게이트웨이 검색 연결 (PR #12)
- `analysis_pending`: 명세 변경으로 중단, `defer_analysis`로 대체

남은 일 (우선순위 순):
1) AI의 `search_analyzer.py` 병합 후 검색 기본값 `baze` 전환, 테스트 수정, 사진 검색 전체 시간 측정
2) 시연 데이터 등록 후 backfill 도구로 임베딩 채우기 (`--dry-run` 먼저)
3) `docs/REQUESTS.md` 백엔드 요청 처리

## 4. 진행 상황 기록

- 진행 상황과 남은 작업은 `docs/HANDOFF.md`에 갱신한다.
- 위 3절의 할 일을 끝내면 `docs/HANDOFF.md`에 완료로 적는다. 이 파일(`CLAUDE.md`)은 PM만 고치므로, 목록에서 빼 달라는 요청을 `docs/REQUESTS.md`에 남긴다.
