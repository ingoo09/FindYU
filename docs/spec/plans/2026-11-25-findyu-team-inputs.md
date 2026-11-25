# FindYU 팀원 준비·전달 체크리스트

[5시간 구현 실행 계획](2026-11-25-findyu-hackathon.md) · [README 변경표](../README.md) · [공통 명세](../00_공통.md)

팀 채널에는 준비 상태·접근 결과·경로만 공유한다. **키 값은 본인 로컬 `backend/.env` 또는 권한 있는 실사용 서버의 비밀 변수에 직접 입력**한다. Codex·Claude Code 프롬프트, 채팅, PR, 프론트 환경변수에는 키를 붙이지 않는다. 기존 `.env`가 있으면 덮어쓰지 않는다.

각 에이전트에 README, `00_공통.md`, 자기 역할 명세, 실행 계획을 전달한다. 저장소의 `AGENTS.md`와 최신 `docs/API.md`도 읽게 한다. 백엔드 Claude Code는 저장소 `CLAUDE.md`를 함께 따른다.

| 담당 | 사람이 직접 준비·전달할 것 | 전달 대상 |
|---|---|---|
| 공통 · 전원 | [ ] GitHub 저장소 읽기·자기 브랜치 PR 권한, 로컬 작업 경로와 시작 SHA. [ ] 현장 네트워크 및 발표 전 기능 동결 시각 받기. 실제 호출이 없는 작업은 `mock`으로 시작 | PM |
| 최인구 · PM·통합 | [ ] 시연 PC·실사용 서버와 실행 책임자, 최종 발표/제출 방식. [ ] 시연 계정의 Flash·Argon·`gemini-embedding-2` 권한과 사용 가능한 크레딧. [ ] 사전 등록 물품·예상 ID·녹화 위치, 시연용 백필 요청 범위 | 전원. 비밀 변수는 실행 책임자가 서버에 직접 설정 |
| 최준서 · AI | [ ] 자신의 FactChat 키와 Flash·Argon 권한. [ ] 스마트폰·이어폰·지갑의 허락받은 사진 각 2장, 다른 각도 검색 사진과 자연어 입력, 정답 ID. [ ] 두 모델에서 최종 비교 모듈의 이미지·JSON 호출 확인 | 백엔드에 비교 함수·오류/응답 예시. PM에 모델 상태·측정 결과 |
| 권기백 · 백엔드·DB | [ ] 실호출할 경우 본인 FactChat 키와 `gemini-embedding-2` 접근. [ ] 쓰기 가능한 시연 SQLite·사진 복사본과 대표 사진 확인. [ ] `--dry-run`의 대상·예상 Gateway 호출 수, 백필 후 모델·차원·실패 ID. [ ] API 주소·정상/빈 결과/실패 예시 | 프론트·Dashboard에는 API와 예시, PM에는 백필·임베딩·비교 시간. 키·DB 원본은 공유 문서에 올리지 않는다 |
| 김승보 · 프론트엔드 | [ ] 백엔드 URL 또는 기본 `/api` 프록시 확인, 1·2·5·6장 검증용 로컬 이미지, 정상·실패 mock 사용 정보. [ ] 홈 연결 시 Dashboard 기본 export 경로·props 수신 | PM에 빌드 결과와 등록·검색 재현 절차. FactChat 키는 필요 없음 |
| 이수형 · Dashboard | [ ] 실제 목록·장소·상세 API 주소, 필터를 확인할 두 장소와 두 품목 이상, 알고 있는 상세 ID 및 구형 사진 1장 샘플. [ ] 홈 연결용 export·props 전달 | 프론트에 연결 경로, PM에 필터·상세 테스트 결과. FactChat 키는 필요 없음 |

## 환경에 넣을 값

| 용도 | 등록 / 검색 모드 | `FINDYU_BAZE_MODEL` | 사진 임베딩 | 키 |
|---|---|---|---|---|
| 로컬 UI·자동 테스트 | `mock` / `mock` | 실호출 없음 | 모의 벡터 | 불필요 |
| 개발·통합 실호출 | `baze` / `baze` | `gemini-3.8-flash` | `gemini-embedding-2@256` | 각 시험자 본인 키 |
| 실사용·최종 확인 | `baze` / `baze` | `gemini-4-argon` | `gemini-embedding-2@256` | 실사용 실행 책임자가 해당 서버에 설정 |

- 모드 변수는 `FINDYU_REGISTRATION_ANALYZER_MODE`, `FINDYU_SEARCH_ANALYZER_MODE`다. 키 이름은 `BAZE_API_KEY`다. Gateway 주소가 필요하면 `FINDYU_BAZE_BASE_URL=https://factchat-cloud.mindlogic.ai/v1/gateway`를 사용한다. [FactChat 개발자 화면](https://factchat.yu.ac.kr/dashboard/developers) · [영남대 인증 문서](https://docs.mindlogic.ai/docs/ynu-ac/api-gateway/getting-started/authentication)
- `GET /models/`로 Flash/Argon을, `GET /models/?type=embedding`으로 사진 임베딩 접근을 확인한다. 허락받은 사진으로 구조화 JSON과 사진 벡터 256개를 소량 검증한다. 결과는 `모델 ID / 권한 / 기능 성공 / HTTP 상태`만 기록한다. [영남대 모델 목록](https://docs.mindlogic.ai/docs/ynu-ac/api-gateway/getting-started/models) · [임베딩 API](https://docs.mindlogic.ai/docs/ynu-ac/api-gateway/reference/embeddings)
- 백필과 실사용 서버의 `FINDYU_DB_PATH`·`FINDYU_UPLOAD_DIR`이 같은 시연 사본을 가리키고, `FINDYU_EMBEDDING_MODEL=gemini-embedding-2`·`FINDYU_EMBEDDING_DIMENSIONS=256`이 일치하는지 확인한다. `mock` 벡터는 실호출 데이터에 그대로 사용하지 않는다. 백필 전에 대상과 호출 수를 먼저 확인한다.

첫 공유 메시지는 `역할 / 시작 SHA / 키 설정 여부(값 제외) / 모델 권한 / 자료 경로 / 막힌 항목` 정도면 충분하다.
