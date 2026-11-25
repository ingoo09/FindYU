# FindYU 백엔드 API — 체크 폼

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
- 남은 후보는 기존 점수(DINOv2 이미지 0.45 / SigLIP2 텍스트 0.25 / 장소 0.20 / 시간 0.10)로 순위를 매긴다.

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
     "matching_score": 0.6953, "image_similarity": 0.6953,
     "filter_check": {"category": "일치", "color": "일치", "has_card_wallet": "일치"}}
  ]
}
```

오류
- `filters`만 있고 `category`가 없음 → `400 filters를 쓰려면 category를 함께 보내야 합니다.`
- 품목에 없는 항목 → `400 'has_case'는 품목 '지갑'의 검색 항목이 아닙니다.`
- 선택지에 없는 값 → `400 색상: '투명'는 선택지에 없습니다 (...)`

---

## 품목 "이어폰" 추가 (DB v7, 프롬프트 v1.3)

- 품목이 `스마트폰 / 이어폰 / 지갑 / 기타`로 바뀌었다. 무선 이어폰과 충전 케이스가 이어폰이고, 헤드폰은 기타다.
- 마이그레이션 v7: 새 컬럼(`has_card_wallet`, `earphone_components`, `wallet_closure`, `field_sources`, `analysis_model`)을 추가한다. 기존 `기타` 중 설명·브랜드에 이어폰 단어(버즈, 에어팟, 이어폰 등)가 있는 물품은 `이어폰`으로 바꾼다.
- 프롬프트 v1.3: 이어폰 분류와 새 항목을 추가했다. 스마트폰 기종 식별 규칙(Step 4)과 식별수준 규칙은 v1.2와 같다.
