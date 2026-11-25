# FindYU 백엔드 API

- **[게이트웨이 검색](#post-search--게이트웨이-검색-baze--mock)** · [수동 등록 `defer_analysis`](#수동-등록-defer_analysis) · [환경 설정](#환경-설정)
- [물품 목록](#get-items--물품-목록) · [장소 선택지](#get-itemslocations--장소-필터-선택지) · [검색 점수 (local 모드)](#검색-점수-similarity_score-2026-11-25-변경)
- 체크 폼: [form-schema](#get-form-schema) · [등록 분석](#post-itemsanalyze) · [등록](#post-items-추가된-필드) · [검색](#post-search-추가된-필드)

## 체크 폼

등록·검색 화면의 **품목별 체크 폼**과 관련된 API를 정리한다. 챗봇처럼 하나씩 묻지 않고, 품목별 항목과 선택지를 한 화면에 보여준다.

- 코드: `backend/check_form.py` (항목 정의, needs_check, photo_hint, 필터), `backend/main.py` (엔드포인트)
- 선택지는 `backend/labels.py`를 따른다
- **모든 선택형 항목에는 `"모르겠음"`이 있다.** `"모르겠음"`은 "답하지 않음"과 같다.
  - 등록: AI 값이 있으면 AI 값이 저장된다
  - 검색: 그 항목으로는 거르지 않는다

## 흐름

```
[등록] 사진 선택 → POST /items/analyze → 체크 폼 미리 채움(AI 값), needs_check 항목 "확인해주세요"
       → 습득자가 필요한 항목만 수정 → POST /items (analysis_id + form_answers)
[검색] GET /form-schema → 분실자가 아는 항목만 체크 → POST /search (category + filters)
```

---

## GET /form-schema

품목별 항목과 선택지를 준다.

| 쿼리 | 설명 |
|---|---|
| `category` (선택) | `스마트폰` / `이어폰` / `지갑` / `기타`. 빼면 전 품목을 한 번에 준다. 목록에 없는 값은 400 |

### 품목별 항목

| 품목 | 항목 (`key`: 선택지) |
|---|---|
| 스마트폰 | `brand`: 애플/삼성/기타 · `device_model`: 자유 입력(text) · `color` · `has_case`: 있음/없음 · `has_card_wallet`: 있음/없음 |
| 이어폰 | `brand`: 애플/삼성/기타 · `color` · `earphone_components`: 케이스+이어버드/케이스만/이어버드만 · `has_cover`: 있음/없음 |
| 지갑 | `wallet_type`: 장지갑/반지갑/카드지갑 · `material`: 가죽/인조가죽/천/금속/플라스틱/실리콘/유리/기타 · `color` · `wallet_closure`: 지퍼/똑딱이/없음 |
| 기타 | `color` |

- 위 선택지 끝에 모두 `"모르겠음"`이 붙는다.
- `color`: 검정, 흰색, 회색, 은색, 빨강, 주황, 노랑, 초록, 파랑, 남색, 보라, 분홍, 갈색, 베이지, 금색, 다색 (+모르겠음). `labels.COLORS`의 "미확인" 대신 "모르겠음"을 쓴다.
- `device_model`은 `type: "text"`. 선택지 대신 자유 입력이고, 분석 결과의 `suggestions`(AI 기종 + 대안후보)를 칩으로 보여준다.
- DB 컬럼 대응: `brand` → `manufacturer`(브랜드 선택지로 묶어 비교, 예: "삼성전자" → 삼성), 이어폰 `has_cover` → `has_case`, 나머지는 같은 이름의 컬럼.

### 예시: `GET /form-schema?category=이어폰`

```json
{
  "category": "이어폰",
  "category_field": {
    "key": "category", "label": "품목", "type": "choice",
    "options": ["스마트폰", "이어폰", "지갑", "기타", "모르겠음"]
  },
  "fields": [
    {"key": "brand", "label": "브랜드", "type": "choice", "options": ["애플", "삼성", "기타", "모르겠음"]},
    {"key": "color", "label": "색상", "type": "choice",
     "options": ["검정", "흰색", "...", "다색", "모르겠음"], "help": "케이스나 커버를 씌웠다면 겉으로 보이는 색"},
    {"key": "earphone_components", "label": "구성", "type": "choice",
     "options": ["케이스+이어버드", "케이스만", "이어버드만", "모르겠음"]},
    {"key": "has_cover", "label": "보호커버", "type": "choice",
     "options": ["있음", "없음", "모르겠음"], "help": "충전 케이스에 씌운 실리콘 커버 등"}
  ],
  "unknown_option": "모르겠음"
}
```

`category` 없이 부르면 `{"categories": [...], "category_field": {...}, "forms": {"스마트폰": [...], "이어폰": [...], ...}, "unknown_option": "모르겠음"}` 형태다.

---

## POST /items/analyze

등록 전에 사진을 분석한다. 기존 분석 필드에 아래가 추가됐다.

| 필드 | 설명 |
|---|---|
| `analysis_id` | 이 분석 결과의 id. `POST /items`에 함께 보내면 AI를 다시 부르지 않고 이 결과를 쓴다. 서버 메모리에 1시간 보관 (재시작·만료 시 등록 후 다시 분석) |
| `check_form.category` | AI가 고른 품목과 needs_check |
| `check_form.fields[]` | AI 품목의 항목들. 스키마 필드 + `ai_value`(폼 선택지 기준, 모르면 "모르겠음") + `needs_check` + `check_reasons` |
| `photo_hint` | 사진을 더 찍으면 판단이 나아지는 경우의 안내 문구. 없으면 `null` (`check_form.photo_hint`와 같음) |

### needs_check 기준 (애매하면 true)

| 조건 | 해당 항목 | `check_reasons` |
|---|---|---|
| AI가 값을 정하지 못함 (null) | 모든 항목 | AI가 판단하지 못함 |
| 품목 확신도 "낮음" | 품목과 모든 항목 | 품목 확신도 낮음 |
| 항목 확신도 "낮음" | 브랜드(제조사 확신도), 색상, 기종 | 확신도 낮음 |
| 색상이 "다색" | 색상 | 여러 색이 섞여 있음 |
| 대안후보(`device_model_candidates`) 있음 | 기종 | 대안 후보 있음 |
| 식별수준이 "확인"이 아니거나 기종이 "… 시리즈" | 기종 | 세대 구분 근거 없음 |

확신도는 품목·제조사·기종·색상만 있다. 케이스·카드지갑·구성·지갑 종류 등은 AI가 값을 정했는지(null 여부)로만 판단한다.

### photo_hint 기준

| 품목 | 조건 | 문구 |
|---|---|---|
| 스마트폰 | 식별수준이 "확인"이 아님 | 측면(버튼 쪽) 사진 추가 안내. 추가확인필요사항에 "전면"만 있으면 전면 사진 안내 |
| 이어폰 | 구성 또는 제조사를 모름 | 충전 케이스를 연 사진·로고 사진 안내 |
| 지갑 | 종류 또는 소재를 모름 | 펼친 사진·겉면 근접 사진 안내 |
| 품목 모름 / 품목 확신도 낮음 | | 다른 각도 사진 안내 |

스마트폰에서 측면을 먼저 안내하는 이유: 2026-11-25 측정에서 후면·전면만으로는 15 Pro 세대를 한 번도 확정하지 못했고, 측면 액션 버튼이 보일 때만 정답이 나왔다 (`docs/model_comparison.md`).

### 응답 예시 (실제 응답, 15 Pro 후면+전면, baze / gemini-3.5-flash / 프롬프트 v1.3)

```json
{
  "category": "스마트폰",
  "color": "검정",
  "manufacturer": "애플",
  "brand": "애플",
  "device_model": "iPhone Pro 시리즈",
  "device_model_candidates": ["iPhone 14 Pro", "iPhone 15 Pro"],
  "identification_level": "추정",
  "has_case": true,
  "has_card_wallet": true,
  "earphone_components": null,
  "wallet_type": null,
  "material": null,
  "wallet_closure": null,
  "verification_needed": [
    "측면 사진 없음 (액션 버튼 유무 확인 불가)",
    "하단 단자 사진 없음 (Lightning 또는 USB-C 구분 불가)"
  ],
  "features": "후면 검은색 카드지갑 부착 · 투명 테두리 케이스 착용 · 트리플 카메라 및 LiDAR 센서",
  "evidence": ["사진 1: 인덕션 형태의 트리플 카메라와 후면 검정 카드지갑 관찰됨", "사진 2: 평평한 전면 디스플레이 화면 관찰됨"],
  "generation_evidence": [],
  "same_item": true,
  "confidence": {"category": "높음", "manufacturer": "높음", "device_model": "보통", "color": "높음"},
  "confidence_scores": {"category": 0.9, "manufacturer": 0.9, "device_model": 0.6, "color": 0.9},
  "prompt_version": "v1.3",
  "model": "gemini-3.5-flash",
  "description": "후면 검은색 카드지갑 부착 · 투명 테두리 케이스 착용 · 트리플 카메라 및 LiDAR 센서",
  "analysis_id": "95f1d425aa3a422e97dc935941c9648a",
  "check_form": {
    "category": {"ai_value": "스마트폰", "needs_check": false, "check_reasons": []},
    "fields": [
      {"key": "brand", "label": "브랜드", "type": "choice", "options": ["애플", "삼성", "기타", "모르겠음"],
       "ai_value": "애플", "needs_check": false, "check_reasons": []},
      {"key": "device_model", "label": "기종", "type": "text", "unknown_option": "모르겠음",
       "help": "모르면 비워 두세요. AI가 추정한 기종과 후보가 함께 표시됩니다.",
       "ai_value": "iPhone Pro 시리즈", "needs_check": true,
       "check_reasons": ["대안 후보 있음", "세대 구분 근거 없음"],
       "suggestions": ["iPhone Pro 시리즈", "iPhone 14 Pro", "iPhone 15 Pro"]},
      {"key": "color", "label": "색상", "type": "choice", "options": ["검정", "흰색", "...", "모르겠음"],
       "help": "케이스나 커버를 씌웠다면 겉으로 보이는 색",
       "ai_value": "검정", "needs_check": false, "check_reasons": []},
      {"key": "has_case", "label": "케이스", "type": "choice", "options": ["있음", "없음", "모르겠음"],
       "ai_value": "있음", "needs_check": false, "check_reasons": []},
      {"key": "has_card_wallet", "label": "카드지갑 부착", "type": "choice", "options": ["있음", "없음", "모르겠음"],
       "help": "뒷면에 붙이는 카드지갑(MagSafe 카드지갑 등)",
       "ai_value": "있음", "needs_check": false, "check_reasons": []}
    ],
    "photo_hint": "측면(버튼 쪽) 사진을 추가하면 기종을 더 정확히 구분할 수 있어요."
  },
  "photo_hint": "측면(버튼 쪽) 사진을 추가하면 기종을 더 정확히 구분할 수 있어요."
}
```

(`color.options`는 지면상 줄였다. 실제로는 색상 16개 + 모르겠음)

---

## POST /items (추가된 필드)

| 필드 (multipart form) | 설명 |
|---|---|
| `analysis_id` (선택) | `/items/analyze` 응답의 id. **같은 사진 묶음**(순서는 무관, 대표 사진을 바꿔도 됨)일 때만 그 분석 결과를 쓴다. 다른 사진이거나 만료됐으면 무시하고 등록 후 백그라운드에서 다시 분석 |
| `form_answers` (선택) | 사람이 고른 값. JSON 객체 `{"category": "스마트폰", "device_model": "iPhone 15 Pro", "color": "모르겠음"}` |
| `defer_analysis` (선택) | `true`면 등록 분석을 부르지 않고 바로 `registered`로 저장한다 (아래 "수동 등록"). `true`/`false` 외의 값은 400 |

저장 규칙
- **우선순위: `form_answers`(사람) > 기존 입력란(`category`, `color`, `brand` 등) > AI 값.** AI 값은 빈 칸만 채운다.
- `"모르겠음"`이나 빈 값은 답하지 않은 것으로 보고 AI 값을 쓴다.
- **수정 없이 등록해도 된다.** `form_answers` 없이 `analysis_id`만 보내면 AI 값이 그대로 저장된다.
- 항목은 품목별로 검증한다. 품목은 `form_answers.category` → 분석 결과의 품목 순으로 정한다. 그 품목의 항목이 아니거나 선택지에 없는 값은 400.
  - 예: `{"category": "스마트폰", "wallet_type": "반지갑"}` → `400 'wallet_type'는 품목 '스마트폰'의 항목이 아닙니다.`
- 사람이 품목을 AI와 다르게 고르면, AI의 다른 품목 전용 값(예: 지갑 종류)은 저장하지 않는다.
- 브랜드는 사람이 고른 선택지가 AI 값과 같으면 더 구체적인 AI 값을 둔다 (사람 "삼성" + AI "삼성전자" → "삼성전자").
- 사람이 고른 항목에는 AI 확신도를 저장하지 않는다.

응답·조회(`GET /items`, `/items/{id}`)에 추가된 필드

| 필드 | 설명 |
|---|---|
| `has_card_wallet`, `earphone_components`, `wallet_closure` | 새 항목 (DB v7) |
| `form_values` | 체크 폼 기준 값 `{"category": "스마트폰", "brand": "애플", "has_case": "있음", ...}` (모르면 "모르겠음") |
| `field_sources` | 항목별 출처 `{"device_model": "human", "color": "ai", ...}` |
| `analysis_model` | 자동 분석에 쓴 모델·프롬프트, 예: `"baze:gemini-3.5-flash/v1.3"`. 등록 시 분석 결과를 반영했으면 바로 채워지고, 백그라운드 작업은 검색 임베딩만 계산한다 |

### 예시

```bash
curl -F item_type=found \
     -F image=@15pro_front.jpeg -F extra_images=@15pro_back.jpeg \
     -F analysis_id=95f1d425aa3a422e97dc935941c9648a \
     --form-string 'form_answers={"device_model":"iPhone 15 Pro","color":"모르겠음"}' \
     http://127.0.0.1:8000/items
```

```json
{
  "id": 12,
  "status": "analyzing",
  "category": "스마트폰",
  "device_model": "iPhone 15 Pro",
  "color": "검정",
  "confidence": {"category": 0.9, "manufacturer": 0.9, "device_model": null, "color": 0.9},
  "form_values": {"category": "스마트폰", "brand": "애플", "device_model": "iPhone 15 Pro",
                  "color": "검정", "has_case": "있음", "has_card_wallet": "있음"},
  "field_sources": {"device_model": "human", "category": "ai", "brand": "ai", "color": "ai",
                    "has_case": "ai", "has_card_wallet": "ai"},
  "analysis_model": "baze:gemini-3.5-flash/v1.3"
}
```

(응답은 주요 필드만 표시. `status`는 검색 임베딩 계산이 끝나면 `registered`가 된다)

---

## POST /search (추가된 필드)

| 필드 (multipart form) | 설명 |
|---|---|
| `category` (선택) | 품목. `"모르겠음"`이면 품목으로 거르지 않음 |
| `filters` (선택) | 분실자가 체크한 항목. JSON 객체 `{"color": "검정", "has_card_wallet": "있음"}`. 키는 `category`의 폼 항목이어야 하며, `filters`를 쓰려면 `category`가 필요하다 (항목이 품목별로 다르므로) |

동작
- 체크한 항목(**`"모르겠음"` 제외**)과 값이 **다른** 습득물은 후보에서 뺀다.
- 습득물 쪽 값이 비어 있으면(AI도 사람도 모름) **빼지 않고** `filter_check`에 `"미확인"`으로 표시한다. AI가 판단하지 못한 습득물이 검색에서 사라지지 않게 하기 위해서다.
- 기종(`device_model`) 필터: 띄어쓰기·대소문자를 무시하고 습득물의 기종 또는 대안후보와 같으면 일치. 습득물 기종이 "… 시리즈"(제품군)면 "미확인"으로 남긴다.
- 남은 후보는 `similarity_score`로 순위를 매긴다 (아래 "검색 점수" 참고).

### 검색 점수 `similarity_score` (2026-11-25 변경)

> **`FINDYU_SEARCH_ANALYZER_MODE=local`(기존 로컬 모델 검색)에서만 해당한다.** baze·mock 게이트웨이 검색에서는 이 필드들이 모두 `null`이다 ([게이트웨이 검색](#post-search--게이트웨이-검색-baze--mock)).

| 필드 | 의미 |
|---|---|
| `similarity_score` | 최종 점수 0~1. 아래 항목 중 **값이 있는 것만** 가중 평균: 이미지 0.45 / 텍스트 0.25 / 장소 0.20 / 시간 0.10. 결과는 이 값의 내림차순 |
| `image_similarity` | 검색 사진과 습득물 대표 사진의 DINOv2 코사인 유사도 (음수는 0). 사진 없이 검색하면 `null` |
| `text_similarity` | 검색어와 습득물 사진의 SigLIP2 코사인 유사도 (음수는 0). 검색어가 없으면 `null` |
| `location_score`, `time_score` | 장소·시간 점수 0~1. 입력이 없으면 `null` |
| `matching_score`, `similarity` | **이전 이름. `similarity_score`와 같은 값이며, 프론트 전환 후 제거 예정** |

- **확률이 아니다.** 화면에 "%"·"확률"·"일치율"로 보여주지 않고, 순위나 "높음/보통/낮음" 정도로만 보여준다 (AGENTS.md 7-2). 높음/보통/낮음 구간은 아직 측정하지 않았다.
- 예전에는 코사인 값을 `(cos + 1) / 2`로 바꿔서 관련 없는 물품도 0.5~0.7이 나왔다. 지금은 코사인 값을 그대로 쓴다. 같은 사진은 1.0, 관련 없는 물품은 대체로 0~0.35 (2026-11-25 로컬 데이터 7건 기준).
- SigLIP2 텍스트 유사도는 값 자체가 작다 (같은 측정에서 0.03~0.15). 순위 비교에만 쓴다.
- 이 변경으로 이미지·텍스트 점수는 예전 값의 절반 폭이 되어, 장소·시간을 함께 입력하면 장소·시간의 영향이 예전보다 커진다. 이미지와 텍스트 사이의 비중·순위는 그대로다.
- `POST /compare`도 `similarity_score`(코사인)를 준다. `is_same_item`은 예전과 같은 기준(예전 점수 0.8 = 코사인 0.6 이상)이다.

응답에 추가된 필드

| 필드 | 설명 |
|---|---|
| `applied_filters` | 실제로 적용한 조건 (`"모르겠음"` 제외) |
| `total_found_items` | 필터 전 습득물 수 |
| `total_candidates` | 필터 후 후보 수 |
| `results[].filter_check` | 항목별 `"일치"` / `"미확인"` |

### 예시

```bash
curl -F image=@15pro_side2.jpeg -F category=스마트폰 \
     --form-string 'filters={"color":"검정","has_card_wallet":"있음","brand":"모르겠음"}' \
     http://127.0.0.1:8000/search
```

```json
{
  "applied_filters": {"category": "스마트폰", "color": "검정", "has_card_wallet": "있음"},
  "total_found_items": 10,
  "total_candidates": 2,
  "results": [
    {"id": 12, "category": "스마트폰", "device_model": "iPhone 15 Pro", "color": "검정",
     "similarity_score": 0.3906, "image_similarity": 0.3906, "text_similarity": null,
     "location_score": null, "time_score": null,
     "matching_score": 0.3906, "similarity": 0.3906,
     "filter_check": {"category": "일치", "color": "일치", "has_card_wallet": "일치"}}
  ]
}
```

오류
- `filters`만 있고 `category`가 없음 → `400 filters를 쓰려면 category를 함께 보내야 합니다.`
- 품목에 없는 항목 → `400 'has_case'는 품목 '지갑'의 검색 항목이 아닙니다.`
- 선택지에 없는 값 → `400 색상: '투명'는 선택지에 없습니다 (...)`

---

## 수동 등록 `defer_analysis`

AI 분석을 쓸 수 없을 때(게이트웨이 오류 등) 프론트가 사람이 입력한 값으로 바로 등록하는 경로 (공통 명세 3절, 백엔드 명세 B1).

- `POST /items`에 `defer_analysis=true`를 보내면 **등록 분석을 부르지 않고**(호출 0회) 사진·입력값을 저장한 뒤 바로 `status: "registered"`와 실제 `id`를 돌려준다. 새 상태·마이그레이션·재처리 큐는 없다.
- 같은 사진 묶음에 유효한 `analysis_id`가 함께 오면 그 분석 결과는 재사용한다 (다시 호출하지 않음).
- 저장 직후 백그라운드에서 **사진 검색 임베딩만 1회 시도**한다. 실패하면 비워 두고 등록 결과에는 영향이 없다 (일반 등록도 같음).
- 수동 등록 물품도 목록·상세·검색 후보에 바로 나온다.

```bash
curl -F item_type=found -F image=@back.jpg -F extra_images=@side.jpg \
     -F defer_analysis=true \
     --form-string 'form_answers={"category":"지갑","wallet_type":"반지갑","color":"갈색"}' \
     -F location=IT관 http://127.0.0.1:8000/items
```

```json
{"id": 21, "status": "registered", "category": "지갑", "wallet_type": "반지갑", "color": "갈색",
 "field_sources": {"category": "human", "wallet_type": "human", "color": "human"},
 "analysis_model": null, "...": "(GET /items/{id}와 같은 나머지 필드)"}
```

---

## POST /search — 게이트웨이 검색 (baze · mock)

`FINDYU_SEARCH_ANALYZER_MODE=baze` 또는 `mock`(**현재 기본값**)일 때의 검색. 기본값은 AI 담당의 `backend/search_analyzer.py`가 병합될 때까지 `mock`이다 (병합되면 `baze`로 바꾼다). 로컬 검색 모델(DINOv2·SigLIP2·Qwen)을 불러오지 않는다. 요청 필드는 그대로다 (`image` 또는 `description`, 선택 `category`·`filters`·`location`·`occurred_at`·`top_k`).

### 흐름

1. **체크 폼 필터**: 위 "POST /search (추가된 필드)"와 같은 규칙 (`일치`·`미확인`, `total_candidates` 의미 동일). `analysis_failed`는 제외, 수동 등록은 포함.
2. **비교 후보 최대 10건** (`evaluated_count`)
   - **사진 검색**: 검색 사진의 임베딩(게이트웨이 1회)과 저장된 사진 임베딩의 코사인 유사도 상위부터. 임베딩이 없는 물품(수동 등록 중 실패·백필 전 물품, 다른 모델의 임베딩)은 **남은 자리를 명세 순서로** 채운다. 대표 사진을 읽을 수 없는 물품은 건너뛴다. 후보 중 임베딩이 있는 물품이 하나도 없으면 검색 사진 임베딩도 부르지 않는다.
   - **자연어 검색**: 명세 순서. 문장→사진 임베딩은 쓰지 않는다. 대표 사진을 읽을 수 없어도 저장된 외형 문장·체크 폼 값으로 비교한다.
   - **명세 순서**: 요청한 `location`과 부분 일치 → `occurred_at`과 습득 시각이 가까운 순 → 등록 최신순(`created_at`, `id`). 입력하지 않은 기준은 건너뛴다.
   - **공통 명세와 다른 점 (2026-11-25 팀 결정)**: 명세는 사진 검색도 명세 순서로만 고르지만, 여기서는 사진 임베딩 상위 10건을 먼저 고른다.
3. **검색 비교 한 번**: 검색 입력과 후보 묶음(ID, 품목, 외형 문장, 체크 폼 값, 장소, 습득 시각, 대표 사진 JPEG)을 검색 어댑터에 보낸다. 파일 경로·URL은 보내지 않는다. mock은 받은 순서를 그대로 돌려준다.
4. **검증·결합**: 어댑터가 돌려준 ID가 보낸 후보 안에 있고 중복이 없는지 검사한다 (어긋나면 전체 502). 결과 순서가 순위이며 **Top-5 이내**(`top_k`는 1~5로 자름). 어댑터가 일부 후보만 돌려주는 것은 허용한다.

- 후보가 0건이면 AI를 부르지 않고 200과 `results: []`.
- 사진·설명 없이 필터만 보내면 AI를 부르지 않고 명세 순서로 `top_k`건 (`evaluated_count: 0`).

### 응답

| 필드 | 설명 |
|---|---|
| `results[]` | 물품 객체(`GET /items/{id}`와 같음) + 아래 필드. **배열 순서 = 순위** |
| `results[].rank` | 1부터 |
| `results[].match_reasons` | 모델이 낸 짧은 비교 근거 (최대 3개, 없으면 `[]`) |
| `results[].filter_check` | 체크 폼 항목별 `"일치"` / `"미확인"` |
| `results[].selection_source` | `"embedding"`(사진 임베딩 상위로 뽑힘) / `"order"`(명세 순서로 뽑힘) |
| `results[].similarity_score`, `matching_score`, `similarity`, `image_similarity`, `text_similarity`, `location_score`, `time_score` | **전환 기간 동안 항상 `null`.** 화면은 이 값을 쓰지 말고 순위(`rank`)와 `match_reasons`를 보여준다. 프론트 전환이 끝나면 필드를 지운다 |
| `search_kind` | `"image"` / `"text"` / `"filter_only"` |
| `search_analyzer_mode` | `"baze"` / `"mock"` |
| `embedding_model` | 사진 검색에 쓴 임베딩 모델 (예: `"gemini-embedding-2@256"`), 자연어 검색이면 `null` |
| `applied_filters`, `total_found_items`, `total_candidates` | 위와 같음 |
| `evaluated_count` | 비교에 보낸 후보 수 (최대 10) |
| `selection` | `{"by_embedding": 3, "by_order": 1}` 비교 후보가 어떻게 뽑혔는지 |
| `timings` | `{"embedding_ms": 820, "compare_ms": 4100, "total_ms": 5010}` (호출하지 않은 단계는 없음) |

```json
{
  "query_description": null,
  "query_location": "IT관",
  "query_occurred_at": null,
  "search_kind": "image",
  "search_analyzer_mode": "baze",
  "embedding_model": "gemini-embedding-2@256",
  "applied_filters": {"category": "이어폰"},
  "total_found_items": 30,
  "total_candidates": 6,
  "evaluated_count": 6,
  "selection": {"by_embedding": 5, "by_order": 1},
  "timings": {"embedding_ms": 820, "compare_ms": 4100, "total_ms": 5010},
  "results": [
    {
      "id": 12, "category": "이어폰", "location": "IT관(E21)", "image_url": "/uploads/....jpg",
      "rank": 1,
      "match_reasons": ["흰색 충전 케이스 형태가 유사함"],
      "filter_check": {"category": "일치", "has_cover": "미확인"},
      "selection_source": "embedding",
      "similarity_score": null, "matching_score": null, "similarity": null,
      "image_similarity": null, "text_similarity": null, "location_score": null, "time_score": null,
      "...": "(GET /items/{id}와 같은 나머지 필드)"
    }
  ]
}
```

(`timings` 값은 형식 예시다. 실제 측정값은 확인 후 `docs/HANDOFF.md`에 적는다)

### 오류

| 상황 | 응답 |
|---|---|
| 필터·`category` 값 오류, 읽을 수 없는 검색 사진 | 400 |
| 게이트웨이 호출 실패·응답 이상 (임베딩, 비교), 어댑터가 계약과 다른 결과 (보내지 않은 ID, 중복, 형식) | **502** `{"detail": "..."}` |
| 설정 문제 (`BAZE_API_KEY` 없음, AI 검색 어댑터 `backend/search_analyzer.py`가 아직 없음) | **503** |
| 조회 결과 0건 | 200, `results: []` (오류 아님) |

### 사진 임베딩

- 모델 `gemini-embedding-2`, 256차원. 대표 사진 1장을 긴 변 1024px JPEG로 줄여 `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}` 객체로 보낸다.
- 응답의 `usage.prompt_tokens`가 **사진 1장당 1,000을 넘으면 오류(502)**로 본다. 사진으로 처리되면 장당 258토큰이고, data URL을 문자열로 보내 글자로 처리되면 18만 토큰이 나온다 (2026-11-25 실험). 게이트웨이가 200을 주면서 엉뚱한 벡터를 돌려주는 경우를 막기 위한 검사다.
- 등록 후 백그라운드에서 1회 시도하고, 실패하면 비워 둔다. 기존 `embedding`(DINOv2) 칸과 따로 `image_embedding_gemini`·`image_embedding_model`(DB v8)에 저장해 섞지 않는다. 다른 모델로 만든 임베딩은 검색에서 "없음"으로 본다.
- 비어 있는 물품은 수동 백필로 채운다 (서버 시작 때 자동 실행 안 함):
  `FINDYU_SEARCH_ANALYZER_MODE=baze .venv/bin/python tools/backfill_gemini_embeddings.py` → 대상 수와 게이트웨이 호출 수를 보여주고 확인받은 뒤 실행 (`--dry-run`, `--batch`). 모드를 주지 않으면 서버와 같은 기본값(mock)으로 API 없이 채운다

---

## GET /items — 물품 목록

통합 Dashboard의 목록 화면용. 필터 + 등록 시각 정렬 + 페이지 나누기. (2026-11-25 변경: 응답이 배열에서 객체로 바뀜)

| 쿼리 (모두 선택) | 값 | 기본 |
|---|---|---|
| `item_type` | `found`(습득물) / `lost`(분실물) | 전체 |
| `category` | `스마트폰` / `이어폰` / `지갑` / `기타`. `모르겠음`이면 거르지 않음 | 전체 |
| `location` | 장소 **부분 일치** (예: `IT관` → "IT관(E21)", "IT관 2층"). 영문 대소문자 무시, `%`·`_`는 글자 그대로 비교 | 전체 |
| `status` | `analyzing`(AI 분석 중) / `registered`(등록 완료) / `analysis_failed`(분석 실패) | 전체 |
| `page` | 1부터 | 1 |
| `page_size` | 1~100 | 20 |
| `sort` | `newest`(최신 등록순) / `oldest` | `newest` |

- 정렬은 등록 시각(`created_at`) 기준이고, 같으면 `id`로 순서를 고정한다 (페이지를 넘겨도 순서가 흔들리지 않음).
- 마지막 페이지를 넘는 `page`는 오류가 아니라 빈 `items`를 준다.
- 잘못된 값은 400. 예: `{"detail": "page_size는 1~100 사이여야 합니다."}`
- `items[]`의 각 물품은 `GET /items/{id}`와 같은 형식이다 (`form_values`, `field_sources`, `images` 포함).

### 예시: `GET /items?item_type=found&page_size=3`

```json
{
  "items": [
    {
      "id": 9,
      "item_type": "found",
      "category": "기타",
      "color": "검정",
      "brand": "SQ",
      "description": "흰둥이 키링이 달려 있음",
      "location": "과학도서관(F24)",
      "occurred_at": null,
      "status": "registered",
      "created_at": "2026-10-04T10:17:11",
      "image_url": "/uploads/....jpg",
      "images": [{"position": 0, "image_url": "/uploads/....jpg"}],
      "form_values": {"category": "기타", "color": "검정"},
      "field_sources": {},
      "...": "(GET /items/{id}와 같은 나머지 필드)"
    }
  ],
  "total": 7,
  "page": 1,
  "page_size": 3,
  "total_pages": 3,
  "has_next": true,
  "sort": "newest",
  "filters": {"item_type": "found"}
}
```

- `total`: 필터를 적용한 전체 개수 (현재 페이지 개수가 아님)
- `filters`: 실제로 적용한 필터 (빈 값·`모르겠음`은 빠짐)

### 예시: `GET /items?item_type=found&category=이어폰&location=IT관`

```json
{"items": [...], "total": 2, "page": 1, "page_size": 20, "total_pages": 1, "has_next": false,
 "sort": "newest", "filters": {"item_type": "found", "category": "이어폰", "location": "IT관"}}
```

---

## GET /items/locations — 장소 필터 선택지

등록된 장소와 물품 수. 장소는 자유 입력이라, Dashboard의 장소 필터 선택지를 만들 때 쓴다.

| 쿼리 | 값 |
|---|---|
| `item_type` (선택) | `found` / `lost`. 없으면 전체 |

- 앞뒤 공백을 지운 장소별로 센다. 빈 장소는 빠진다.
- 물품이 많은 순, 같으면 이름순.
- 선택한 장소를 `GET /items?location=<장소>`로 넘기면 부분 일치로 거른다.

### 예시: `GET /items/locations?item_type=found`

```json
{
  "locations": [
    {"location": "IT관(E21)", "count": 4},
    {"location": "과학도서관(F24)", "count": 1},
    {"location": "상경관(B02)", "count": 1},
    {"location": "전기관(E22)", "count": 1}
  ]
}
```

---

## 품목 "이어폰" 추가 (DB v7, 프롬프트 v1.3)

- 품목이 `스마트폰 / 이어폰 / 지갑 / 기타`로 바뀌었다. 무선 이어폰과 충전 케이스가 이어폰이고, 헤드폰은 기타다.
- 마이그레이션 v7: 새 컬럼(`has_card_wallet`, `earphone_components`, `wallet_closure`, `field_sources`, `analysis_model`)을 추가한다. 기존 `기타` 중 설명·브랜드에 이어폰 단어(버즈, 에어팟, 이어폰 등)가 있는 물품은 `이어폰`으로 바꾼다.
- 프롬프트 v1.3: 이어폰 분류와 새 항목을 추가했다. 스마트폰 기종 식별 규칙(Step 4)과 식별수준 규칙은 v1.2와 같다.

---

## 환경 설정

| 환경변수 | 값 | 기본 |
|---|---|---|
| `FINDYU_REGISTRATION_ANALYZER_MODE` | `baze` / `gemini` / `mock` / `vlm` | `baze` |
| `FINDYU_SEARCH_ANALYZER_MODE` | `baze`(게이트웨이 임베딩 + 검색 어댑터) / `mock`(API 호출 없음, 테스트·개발) / `local`(기존 DINOv2·SigLIP2) | **`mock`** (`search_analyzer.py` 병합 전까지) |
| `BAZE_API_KEY`, `FINDYU_BAZE_BASE_URL`, `FINDYU_BAZE_MODEL` | 등록 분석과 검색 비교가 함께 쓴다 | |
| `FINDYU_EMBEDDING_MODEL` | 사진 임베딩 모델 | `gemini-embedding-2` |
| `FINDYU_EMBEDDING_DIMENSIONS` | 임베딩 차원 | `256` |
| `FINDYU_EMBEDDING_TIMEOUT` | 임베딩 요청 제한 시간(초) | `60` |
| `FINDYU_DB_PATH`, `FINDYU_UPLOAD_DIR` | DB 파일·업로드 폴더 위치 (테스트용) | `backend/findyu.db`, `backend/uploads` |

- `baze` 검색은 AI 담당의 `backend/search_analyzer.py`가 있어야 동작한다 (없으면 503). 그래서 병합 전까지 기본값은 `mock`이고, 병합되면 백�d가 기본값을 `baze`로 바꾼다 (`search_adapter.DEFAULT_MODE`).
- `mock` 검색은 사진 임베딩도 API 없이 만들기 때문에, mock으로 저장된 임베딩은 `baze`로 바꾼 뒤 "없음"으로 취급된다 (모델이 다름). 필요하면 백필 도구로 다시 채운다.
- 테스트(`pytest`)는 `tests/conftest.py`가 임시 DB·업로드 폴더와 `mock` 모드를 정한다. 실제 DB와 API를 쓰지 않는다.
