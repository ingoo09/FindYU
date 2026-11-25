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

- [ ] **목록 API 필터·페이지**: `GET /items`가 지금은 전체 물품을 한 번에 돌려준다. 품목·장소·상태 필터와 페이지 나누기 추가
- [ ] **검색 점수를 `similarity_score`로 변경**: 지금의 `matching_score`/`similarity` 이름을 바꾸고, 코사인 값을 `(x + 1) / 2`로 바꾸는 변환(`backend/ai_retrieval.py`의 `cosine_similarity_01`)을 없앤다. 이 변환 때문에 관련 없는 물품도 60%대 점수가 나온다
- [ ] **API 실패 시 `analysis_pending`**: 등록 분석 API가 429/503 등으로 실패하면 `analysis_failed` 대신 `analysis_pending`으로 두고 나중에 다시 분석한다. 지금은 `analysis_failed`가 되어 검색에서 빠지고 다시 분석되지도 않는다

## 4. 진행 상황 기록

- 진행 상황과 남은 작업은 `docs/HANDOFF.md`에 갱신한다.
- 위 3절의 할 일을 끝내면 `docs/HANDOFF.md`에 완료로 적는다. 이 파일(`CLAUDE.md`)은 PM만 고치므로, 목록에서 빼 달라는 요청을 `docs/REQUESTS.md`에 남긴다.
