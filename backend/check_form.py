"""
등록·검색 화면의 품목별 체크 폼.

챗봇처럼 하나씩 묻는 대신, 품목별 항목과 선택지를 한 화면에 보여준다.
- GET /form-schema       : 품목별 항목·선택지 (form_schema)
- POST /items/analyze    : AI가 고른 값 + needs_check + photo_hint (build_check_form)
- POST /items            : 사람이 고른 값을 AI 값보다 우선 저장 (apply_answers → apply_ai)
- POST /search           : 분실자가 체크한 항목으로 후보를 거른다 (parse_filters, match_filters)

모든 선택형 항목에는 "모르겠음"이 있다. "모르겠음"은 "답하지 않음"과 같다.
- 등록: AI 값이 있으면 AI 값이 저장된다
- 검색: 그 항목으로는 거르지 않는다
"""

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field

import labels

UNKNOWN = "모르겠음"
YES, NO = "있음", "없음"

SOURCE_HUMAN = "human"
SOURCE_AI = "ai"

# 폼 색상 선택지: labels.COLORS에서 "미확인"은 "모르겠음"으로 대신한다
FORM_COLORS = tuple(c for c in labels.COLORS if c != labels.COLOR_UNKNOWN)


@dataclass(frozen=True)
class FormField:
    key: str            # API 키 (form_answers / filters / check_form.fields[].key)
    label: str
    column: str         # models.Item 컬럼
    type: str = "choice"            # choice | text
    options: tuple = ()             # "모르겠음" 제외 선택지
    help: str | None = None
    # bool 컬럼은 있음/없음 ↔ True/False로 바꾼다
    boolean: bool = False

    def choice_from_column(self, value):
        """DB(또는 분석 결과) 값 → 폼 선택지. 해당 없음은 None."""
        if value is None:
            return None
        if self.boolean:
            return YES if value else NO
        if self.key == "brand":
            return labels.normalize_brand_choice(value)
        if self.key == "color":
            return None if value == labels.COLOR_UNKNOWN else value
        if self.type == "text":
            return str(value).strip() or None
        return value if value in self.options else None

    def column_from_choice(self, choice):
        """폼 선택지 → DB 값. '모르겠음'·빈 값은 None (= 답하지 않음)."""
        if choice is None:
            return None
        text = str(choice).strip()
        if not text or text == UNKNOWN:
            return None
        if self.boolean:
            if text == YES:
                return True
            if text == NO:
                return False
            raise ValueError(f"{self.label}: '{text}'는 선택지에 없습니다 ({YES}/{NO}/{UNKNOWN})")
        if self.type == "text":
            return text
        if text not in self.options:
            raise ValueError(
                f"{self.label}: '{text}'는 선택지에 없습니다 ({', '.join(self.options)}, {UNKNOWN})"
            )
        return text

    def to_schema(self):
        data = {"key": self.key, "label": self.label, "type": self.type}
        if self.type == "choice":
            data["options"] = [*self.options, UNKNOWN]
        else:
            data["unknown_option"] = UNKNOWN
        if self.help:
            data["help"] = self.help
        return data


BRAND = FormField("brand", "브랜드", "manufacturer", options=labels.BRAND_CHOICES)
DEVICE_MODEL = FormField(
    "device_model", "기종", "device_model", type="text",
    help="모르면 비워 두세요. AI가 추정한 기종과 후보가 함께 표시됩니다.",
)
COLOR = FormField("color", "색상", "color", options=FORM_COLORS,
                  help="케이스나 커버를 씌웠다면 겉으로 보이는 색")
PHONE_CASE = FormField("has_case", "케이스", "has_case", options=(YES, NO), boolean=True)
CARD_WALLET = FormField("has_card_wallet", "카드지갑 부착", "has_card_wallet", options=(YES, NO),
                        boolean=True, help="뒷면에 붙이는 카드지갑(MagSafe 카드지갑 등)")
EARPHONE_COMPONENTS = FormField("earphone_components", "구성", "earphone_components",
                                options=labels.EARPHONE_COMPONENTS)
EARPHONE_COVER = FormField("has_cover", "보호커버", "has_case", options=(YES, NO), boolean=True,
                           help="충전 케이스에 씌운 실리콘 커버 등")
WALLET_TYPE = FormField("wallet_type", "종류", "wallet_type", options=labels.WALLET_TYPES)
MATERIAL = FormField("material", "소재", "material", options=labels.MATERIALS, help="겉면 소재")
WALLET_CLOSURE = FormField("wallet_closure", "여밈 방식", "wallet_closure",
                           options=labels.WALLET_CLOSURES)

CATEGORY_FIELDS: dict[str, tuple[FormField, ...]] = {
    labels.CATEGORY_PHONE: (BRAND, DEVICE_MODEL, COLOR, PHONE_CASE, CARD_WALLET),
    labels.CATEGORY_EARPHONE: (BRAND, COLOR, EARPHONE_COMPONENTS, EARPHONE_COVER),
    labels.CATEGORY_WALLET: (WALLET_TYPE, MATERIAL, COLOR, WALLET_CLOSURE),
    labels.CATEGORY_OTHER: (COLOR,),
}

# 품목에 따라 의미가 있는 컬럼. 다른 품목의 컬럼은 저장하지 않는다
CATEGORY_SPECIFIC_COLUMNS = {
    "has_case": {labels.CATEGORY_PHONE, labels.CATEGORY_EARPHONE},
    "has_card_wallet": {labels.CATEGORY_PHONE},
    "earphone_components": {labels.CATEGORY_EARPHONE},
    "wallet_type": {labels.CATEGORY_WALLET},
    "material": {labels.CATEGORY_WALLET},
    "wallet_closure": {labels.CATEGORY_WALLET},
}


def fields_for(category: str | None) -> tuple[FormField, ...]:
    return CATEGORY_FIELDS.get(category, ())


def validate_category(category) -> str | None:
    """폼 품목 선택지 검증. 빈 값·모르겠음은 None."""
    text = (category or "").strip()
    if not text or text == UNKNOWN:
        return None
    if text not in labels.CATEGORIES:
        raise ValueError(f"category는 {', '.join(labels.CATEGORIES)}, {UNKNOWN} 중 하나여야 합니다.")
    return text


def form_schema(category: str | None = None) -> dict:
    """GET /form-schema 응답. category가 없으면 전 품목."""
    category_item = {
        "key": "category", "label": "품목", "type": "choice",
        "options": [*labels.CATEGORIES, UNKNOWN],
    }
    if category is not None:
        return {
            "category": category,
            "category_field": category_item,
            "fields": [f.to_schema() for f in fields_for(category)],
            "unknown_option": UNKNOWN,
        }
    return {
        "categories": list(labels.CATEGORIES),
        "category_field": category_item,
        "forms": {c: [f.to_schema() for f in fields_for(c)] for c in labels.CATEGORIES},
        "unknown_option": UNKNOWN,
    }


# ---------------------------------------------------------
# 등록 분석 → 체크 폼 (AI 값 + needs_check)
# ---------------------------------------------------------
LOW = "낮음"


def _confidence(analysis, key):
    return (analysis.get("confidence") or {}).get(key)


def _needs_check(fld: FormField, analysis: dict, value) -> list[str]:
    """애매하면 사유 목록을 돌려준다 (비어 있으면 needs_check=false)."""
    reasons = []
    if value is None:
        reasons.append("AI가 판단하지 못함")
    if _confidence(analysis, "category") == LOW:
        reasons.append("품목 확신도 낮음")

    if fld.key == "brand" and value is not None and _confidence(analysis, "manufacturer") == LOW:
        reasons.append("확신도 낮음")
    if fld.key == "color" and value is not None:
        if _confidence(analysis, "color") == LOW:
            reasons.append("확신도 낮음")
        if value == labels.COLOR_MULTI:
            reasons.append("여러 색이 섞여 있음")
    if fld.key == "device_model" and value is not None:
        if _confidence(analysis, "device_model") == LOW:
            reasons.append("확신도 낮음")
        if analysis.get("device_model_candidates"):
            reasons.append("대안 후보 있음")
        if analysis.get("identification_level") != "확인" or "시리즈" in value:
            reasons.append("세대 구분 근거 없음")
    return list(dict.fromkeys(reasons))


def build_check_form(analysis: dict, image_count: int) -> dict:
    """/items/analyze 응답의 check_form. AI가 고른 값을 폼 선택지로 바꾸고 needs_check를 붙인다."""
    category = analysis.get("category")
    category_reasons = []
    if category is None:
        category_reasons.append("AI가 판단하지 못함")
    elif _confidence(analysis, "category") == LOW:
        category_reasons.append("확신도 낮음")

    fields = []
    for fld in fields_for(category):
        if fld.key == "brand":
            source_value = analysis.get("manufacturer") or analysis.get("brand")
        else:
            source_value = analysis.get(fld.column)
        value = fld.choice_from_column(source_value)
        reasons = _needs_check(fld, analysis, value)
        entry = {
            **fld.to_schema(),
            "ai_value": value if value is not None else UNKNOWN,
            "needs_check": bool(reasons),
            "check_reasons": reasons,
        }
        if fld.key == "device_model":
            entry["suggestions"] = [
                v for v in [value, *(analysis.get("device_model_candidates") or [])] if v
            ]
        fields.append(entry)

    return {
        "category": {
            "ai_value": category or UNKNOWN,
            "needs_check": bool(category_reasons),
            "check_reasons": category_reasons,
        },
        "fields": fields,
        "photo_hint": photo_hint(analysis, image_count),
    }


def photo_hint(analysis: dict, image_count: int) -> str | None:
    """사진을 더 찍으면 판단이 나아지는 경우의 안내 문구. 해당 없으면 None."""
    category = analysis.get("category")
    missing = " ".join(analysis.get("verification_needed") or [])

    if category == labels.CATEGORY_PHONE:
        if analysis.get("identification_level") == "확인":
            return None
        # 2026-11-25 측정: 후면·전면만으로는 15 Pro 세대를 한 번도 확정하지 못했고,
        # 측면(액션 버튼)이 보일 때만 정답이 나왔다 → 측면 안내를 가장 먼저
        if "측면" in missing or image_count == 1 or "전면" not in missing:
            return "측면(버튼 쪽) 사진을 추가하면 기종을 더 정확히 구분할 수 있어요."
        return "전면 사진을 추가하면 기종을 더 정확히 구분할 수 있어요."

    if category == labels.CATEGORY_EARPHONE:
        if analysis.get("earphone_components") is None or analysis.get("manufacturer") is None:
            return "충전 케이스를 연 사진(이어버드가 보이게)이나 로고가 보이는 사진을 추가해 주세요."
        return None

    if category == labels.CATEGORY_WALLET:
        if analysis.get("wallet_type") is None or analysis.get("material") is None:
            return "지갑을 펼친 사진이나 겉면을 가까이 찍은 사진을 추가해 주세요."
        return None

    if category is None or _confidence(analysis, "category") == LOW:
        return "물품 전체가 보이도록 다른 각도에서 찍은 사진을 추가해 주세요."
    return None


# ---------------------------------------------------------
# 등록 저장: 사람 > AI
# ---------------------------------------------------------
def parse_answers(raw) -> dict:
    """form_answers(JSON 문자열 또는 dict) → {key: 선택지 문자열}."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("form_answers는 JSON 객체여야 합니다.") from exc
    if not isinstance(raw, dict):
        raise ValueError("form_answers는 JSON 객체여야 합니다.")
    return {str(k): ("" if v is None else str(v)) for k, v in raw.items()}


@dataclass
class HumanAnswers:
    category: str | None = None                   # 사람이 고른 품목 (없으면 None)
    form_category: str | None = None              # 답을 검증한 폼의 품목 (사람 품목 → AI 품목)
    columns: dict = field(default_factory=dict)   # 컬럼 → 값 (모르겠음 제외)
    answered: list = field(default_factory=list)  # 사람이 실제로 고른 폼 키


def resolve_answers(answers: dict, fallback_category: str | None = None) -> HumanAnswers:
    """
    사람이 고른 값을 검증하고 컬럼 값으로 바꾼다.
    품목은 answers["category"] → fallback_category(AI 품목) 순. 품목의 폼에 없는 키는 오류.
    """
    result = HumanAnswers()
    result.category = validate_category(answers.get("category"))
    if result.category:
        result.answered.append("category")
    category = result.category or fallback_category
    result.form_category = category

    allowed = {f.key: f for f in fields_for(category)}
    for key, choice in answers.items():
        if key == "category":
            continue
        fld = allowed.get(key)
        if fld is None:
            if category is None:
                if not choice or choice == UNKNOWN:
                    continue
                raise ValueError(
                    "항목을 저장하려면 품목이 필요합니다. 품목을 선택해 주세요 "
                    "(AI 분석 결과가 만료되었을 수 있습니다)."
                )
            raise ValueError(f"'{key}'는 품목 '{category}'의 항목이 아닙니다.")
        value = fld.column_from_choice(choice)
        if value is None:
            continue
        result.columns[fld.column] = value
        result.answered.append(key)
    return result


def column_allowed(column: str, category: str | None) -> bool:
    allowed = CATEGORY_SPECIFIC_COLUMNS.get(column)
    return allowed is None or category in allowed


def _same_choice(fld: FormField, human_value, ai_value) -> bool:
    return fld.choice_from_column(human_value) == fld.choice_from_column(ai_value)


def apply_human(item, human: HumanAnswers, ai_analysis: dict | None = None) -> dict:
    """
    사람이 고른 값을 item에 저장하고 {폼 키: "human"} 출처를 돌려준다.
    브랜드처럼 선택지가 AI 값보다 거친 항목은, 사람이 고른 선택지가 AI 값과 같으면
    더 구체적인 AI 값(예: "삼성전자")을 그대로 둔다.
    """
    sources = {}
    if human.category:
        item.category = human.category
        item.category_confidence = None
        sources["category"] = SOURCE_HUMAN

    # 품목을 AI가 정하는 경우 item.category는 아직 비어 있으므로 답을 검증한 폼의 품목을 쓴다
    by_column = {f.column: f for f in fields_for(human.form_category or item.category)}
    for column, value in human.columns.items():
        fld = by_column.get(column)
        if fld is None:
            continue
        ai_value = None
        if ai_analysis is not None:
            ai_value = ai_analysis.get("manufacturer") if fld.key == "brand" else ai_analysis.get(column)
        if fld.key == "brand" and ai_value and _same_choice(fld, value, ai_value):
            value = ai_value
        setattr(item, column, value)
        confidence_column = f"{column}_confidence"
        if hasattr(item, confidence_column):
            setattr(item, confidence_column, None)  # 사람이 고른 값에는 AI 확신도를 두지 않음
        sources[fld.key] = SOURCE_HUMAN
    return sources


def ai_sources(item, filled_columns: list[str]) -> dict:
    """AI가 채운 컬럼 → {폼 키: "ai"}."""
    sources = {}
    if "category" in filled_columns:
        sources["category"] = SOURCE_AI
    for fld in fields_for(item.category):
        if fld.column in filled_columns:
            sources[fld.key] = SOURCE_AI
    return sources


def merge_sources(existing: str | None, *updates: dict) -> str | None:
    data = {}
    if existing:
        try:
            data = json.loads(existing) or {}
        except json.JSONDecodeError:
            data = {}
    for update in updates:
        for key, value in update.items():
            # 사람이 고른 항목은 나중에 AI가 덮지 않는다
            if data.get(key) == SOURCE_HUMAN and value != SOURCE_HUMAN:
                continue
            data[key] = value
    return json.dumps(data, ensure_ascii=False) if data else None


def item_form_values(item) -> dict:
    """저장된 물품 → {폼 키: 선택지} (품목 폼 기준, 모르는 값은 '모르겠음')."""
    values = {"category": item.category or UNKNOWN}
    for fld in fields_for(item.category):
        raw = (item.manufacturer or item.brand) if fld.key == "brand" else getattr(item, fld.column)
        value = fld.choice_from_column(raw)
        values[fld.key] = value if value is not None else UNKNOWN
    return values


# ---------------------------------------------------------
# 검색 필터
# ---------------------------------------------------------
def parse_filters(category, raw_filters) -> tuple[str | None, list[tuple[FormField, object]]]:
    """
    분실자가 체크한 항목 → (품목, [(항목, 비교할 컬럼 값)]). '모르겠음'은 거르지 않는다.
    품목 없이 항목만 보내면 오류 (항목은 품목별로 다르므로).
    """
    category = validate_category(category)
    answers = parse_answers(raw_filters)
    answers.pop("category", None)
    if answers and category is None:
        if all(not v or v == UNKNOWN for v in answers.values()):
            return None, []
        raise ValueError("filters를 쓰려면 category를 함께 보내야 합니다.")

    allowed = {f.key: f for f in fields_for(category)}
    filters = []
    for key, choice in answers.items():
        fld = allowed.get(key)
        if fld is None:
            raise ValueError(f"'{key}'는 품목 '{category}'의 검색 항목이 아닙니다.")
        value = fld.column_from_choice(choice)
        if value is not None:
            filters.append((fld, value))
    return category, filters


def _norm_model(text) -> str:
    return "".join(str(text or "").lower().split())


def _device_model_match(query: str, item) -> str:
    candidate = item.device_model
    if not candidate or "시리즈" in candidate:
        return "미확인"  # 제품군까지만 식별된 물품은 기종으로 빼지 않는다
    q = _norm_model(query)
    alternatives = [candidate, *labels.load_str_list(item.device_model_candidates)]
    return "일치" if any(_norm_model(a) == q for a in alternatives) else "불일치"


def match_filters(item, category: str | None, filters) -> dict | None:
    """
    후보 물품이 체크 항목을 통과하면 {항목 키: "일치" | "미확인"}, 탈락이면 None.
    물품 쪽 값이 비어 있으면(AI도 사람도 모름) 거르지 않고 "미확인"으로 표시한다.
    """
    result = {}
    if category is not None:
        if item.category is None:
            result["category"] = "미확인"
        elif item.category != category:
            return None
        else:
            result["category"] = "일치"

    for fld, value in filters:
        if fld.key == "device_model":
            outcome = _device_model_match(value, item)
        else:
            raw = (item.manufacturer or item.brand) if fld.key == "brand" else getattr(item, fld.column)
            item_choice = fld.choice_from_column(raw)
            if item_choice is None:
                outcome = "미확인"
            else:
                outcome = "일치" if item_choice == fld.choice_from_column(value) else "불일치"
        if outcome == "불일치":
            return None
        result[fld.key] = outcome
    return result


# ---------------------------------------------------------
# 등록 전 분석 결과 보관
# 등록 화면은 /items/analyze 결과로 폼을 미리 채우고, 습득자가 확인한 뒤 POST /items를 보낸다.
# 그때 analysis_id로 같은 분석 결과를 다시 쓰면 AI를 두 번 호출하지 않는다.
# 서버 메모리에만 두므로 재시작되거나 만료되면 등록 후 백그라운드에서 다시 분석한다.
# ---------------------------------------------------------
def image_digests(blobs) -> list[str]:
    """사진 묶음 식별용. 순서(대표 사진 변경)와 무관하게 비교한다."""
    return sorted(hashlib.sha256(b).hexdigest() for b in blobs)


class AnalysisCache:
    def __init__(self, ttl_seconds: float = 3600, max_entries: int = 200, clock=time.monotonic):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, list[str], dict]] = {}

    def put(self, analysis: dict, digests: list[str]) -> str:
        analysis_id = uuid.uuid4().hex
        with self._lock:
            self._evict()
            if len(self._entries) >= self._max:
                oldest = min(self._entries, key=lambda k: self._entries[k][0])
                del self._entries[oldest]
            self._entries[analysis_id] = (self._clock(), list(digests), analysis)
        return analysis_id

    def get(self, analysis_id: str | None, digests: list[str]) -> dict | None:
        """같은 사진 묶음에 대한 분석이면 결과를, 아니면(만료·다른 사진) None."""
        if not analysis_id:
            return None
        with self._lock:
            self._evict()
            entry = self._entries.get(analysis_id)
        if entry is None or entry[1] != list(digests):
            return None
        return entry[2]

    def _evict(self):
        now = self._clock()
        for key in [k for k, (t, _, _) in self._entries.items() if now - t > self._ttl]:
            del self._entries[key]
