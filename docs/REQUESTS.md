- [백엔드→PM] CLAUDE.md 3절 '목록 API 필터·페이지' 완료 표시 / `feature/backend-list-api`에서 구현 (docs/API.md 참고) / 보통
- [백엔드→프론트엔드] 검색 결과 점수를 `matching_score` 대신 `similarity_score`로 읽고, "%" 표시(scoreLabel)를 순위 또는 높음/보통/낮음으로 바꿔 주세요 / AGENTS.md 7-2, 점수는 확률이 아님. `matching_score`는 전환 후 백엔드에서 제거 (docs/API.md "검색 점수") / 급함
- [백엔드→PM] CLAUDE.md 3절 '검색 점수를 similarity_score로 변경' 완료 표시 / `feature/backend-similarity-score`에서 구현 / 보통
- [백엔드→AI] (2026-11-25) 검색 비교 어댑터 `backend/search_analyzer.py`에 `compare(query: dict, candidates: list[dict]) -> dict`를 만들어 주세요 / `/search`(baze 모드)가 후보를 최대 10건으로 좁혀 이 함수를 한 번 부르고, 결과 ID를 검증해 DB와 붙입니다. 지금은 파일이 없어 baze 검색이 503이고 mock으로만 동작 (`backend/search_adapter.py` 주석, docs/API.md "게이트웨이 검색") / 급함
  - 입력 `query`: `{"kind": "image"|"text", "text": str|None, "image_jpeg": bytes|None, "location": str|None, "occurred_at": "YYYY-MM-DDTHH:MM"|None}`
  - 입력 `candidates` (최대 10건, 순서는 백엔드가 고른 순서): `[{"id": int, "category": str|None, "description": str|None, "form_values": dict, "location": str|None, "occurred_at": str|None, "image_jpeg": bytes|None}]`
  - `image_jpeg`는 긴 변 1024px JPEG 바이트 (EXIF 회전 반영·메타데이터 제거, `gemini_analyzer.encode_image`와 같음). 게이트웨이에는 `{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}`로 보내면 됩니다. 파일 경로·URL은 주지 않습니다
  - 출력: `{"results": [{"id": int, "match_reasons": [str, ...]}, ...]}` 배열 순서 = 순위. 보낸 후보 ID만, 중복 없이. 관련 없는 후보는 빼도 됨. `match_reasons`는 짧은 관찰 근거 최대 3개(넘으면 백엔드가 자름), 없으면 `[]`. 점수는 넣지 않음
  - 오류: 게이트웨이 호출·응답 스키마 실패는 `gemini_analyzer.AnalyzerError`(→ API 502), 키·설정 문제는 `AnalyzerConfigError`(→ 503)로 올려 주세요. 재시도 여부는 AI 쪽에서 정하되 응답 시간에 주의 (`timings.compare_ms`로 측정)
  - 입력 예시 (사진 검색, 바이트는 `<JPEG bytes>`로 표기):
    `query = {"kind": "image", "text": null, "image_jpeg": <JPEG bytes>, "location": "IT관", "occurred_at": "2026-11-29T11:30"}`
    `candidates = [{"id": 12, "category": "이어폰", "description": "흰색 충전 케이스 · 투명 실리콘 커버", "form_values": {"category": "이어폰", "brand": "애플", "color": "흰색", "earphone_components": "케이스+이어버드", "has_cover": "있음"}, "location": "IT관(E21)", "occurred_at": "2026-11-29T10:50", "image_jpeg": <JPEG bytes>}, {"id": 7, "category": "이어폰", "description": "흰색 케이스", "form_values": {"category": "이어폰", "brand": "모르겠음", "color": "흰색", "earphone_components": "케이스만", "has_cover": "모르겠음"}, "location": "중앙도서관", "occurred_at": null, "image_jpeg": null}]`
  - 출력 예시: `{"results": [{"id": 12, "match_reasons": ["흰색 충전 케이스 형태가 유사함", "투명 커버가 보임"]}, {"id": 7, "match_reasons": []}]}`
  - 빈 결과 예시: `{"results": []}` (백엔드는 후보 0건이면 부르지 않음)
- [백엔드→프론트엔드] (2026-11-25) 게이트웨이 검색에서 점수 필드(`similarity_score`, `matching_score`, `similarity`, `image_similarity`, `text_similarity`, `location_score`, `time_score`)는 항상 `null`입니다. 위 '점수 %' 요청 대신, 결과 배열 순서(`rank`)와 `match_reasons`를 보여 주세요. 등록 분석이 실패하면 `defer_analysis=true`로 직접 입력값 등록 가능 / docs/API.md "게이트웨이 검색", "수동 등록" / 급함
- [백엔드→PM] (2026-11-25) CLAUDE.md 3절 정리: 'API 실패 시 analysis_pending'은 명세 변경으로 중단(로컬 브랜치 `feature/backend-analysis-pending`에만 커밋, push 안 함), 대신 '게이트웨이 검색·수동 등록'이 `feature/backend-gemini-search`에서 진행 중 / 보통
