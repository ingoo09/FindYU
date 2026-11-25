# 이수형 · 통합 Dashboard · Codex

[공통 구현 명세](00_공통.md)를 읽는다. 5시간 범위에서 습득물 최신순 카드, 장소·품목 필터, 상세 화면을 구현한다. 공개된 FindYU 목록·상세 API만 사용하며 백엔드의 Gemini 연결과 병렬 개발할 수 있다.

## 구현 순서

1. `frontend/src/dashboard/FoundItemsDashboard.jsx`에 `FoundItemsDashboard`를 기본 export한다. `apiUrl(path)`와 `assetUrl(path)`를 props로 받고, `App.jsx` 수정을 김승보에게 요청한다. 홈으로 돌아오면 다시 조회한다.
2. `GET /items?item_type=found&sort=newest&page=1&page_size=20`의 순서와 `items`, `total`, `page`, `has_next`를 사용한다. 장소는 `GET /items/locations?item_type=found` 선택지를 쓴다. 품목은 공통 규격의 세 가지와 전체를 제시한다. 필터를 바꾸면 1페이지로 돌아간다. 이전·다음 버튼으로 나머지 물품을 탐색한다.
3. 카드를 열면 `GET /items/{id}`로 대표·보완 사진과 품목·주요 외형·장소·시각을 표시한다. 목록 영역 안에서 전환하고, 돌아오면 선택한 필터와 페이지를 유지한다. 새 라우터는 필요하지 않다.
4. 로딩, 빈 결과, 오류, 이미지 누락을 최소 문구나 대체 이미지로 표시한다. 날짜는 습득과 등록을 구분한다. 상태 필터를 기본 요청에 추가하지 않아 기존·신규·수동 등록 건을 볼 수 있다.

## 최소 검증

- 새 물품 등록 뒤 홈 재진입, 습득물 최신순, 장소·품목 동시 적용, 상세 열기와 목록 복귀를 실 API에서 확인한다.
- 빈 결과·누락 이미지·구형 사진 1장 레코드에서 화면이 열리고 앱 빌드가 통과하는지 확인한다. 공통 E2E-04 결과를 PM과 프론트에 전달한다.

## Codex 시작 프롬프트

```text
역할은 이수형 Dashboard다. 00_공통.md, 05_Dashboard.md, AGENTS.md, docs/API.md를 읽어라. 소유 폴더 안에 FoundItemsDashboard를 만들고 apiUrl·assetUrl을 받아 습득물 목록·필터·상세를 실제 API에 연결하라. 홈 import는 프론트 담당에게 전달하고 E2E-04와 빌드 결과를 한국어로 남겨라.
```
