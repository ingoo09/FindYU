"""
휴대폰·지갑 전용 필드의 허용값과 정규화 함수.

DB에는 한국어 라벨을 그대로 저장한다.
"""

import json
import re

# ---------------------------------------------------------
# 품명 (category)
# ---------------------------------------------------------
CATEGORY_PHONE = "스마트폰"
CATEGORY_WALLET = "지갑"
CATEGORY_OTHER = "기타"
CATEGORIES = (CATEGORY_PHONE, CATEGORY_WALLET, CATEGORY_OTHER)

# 단어 단위로 분류한다. 한국어 명사구는 마지막 명사가 중심이므로
# "마지막으로 분류된 단어"가 품명을 결정한다.
#   "아이폰 케이스" → 케이스(기타) / "케이스 낀 아이폰" → 아이폰(스마트폰)
#   "갤럭시 버즈" → 버즈(기타)   / "갤럭시 S24" → 갤럭시(스마트폰)
_WALLET_WORDS = ("지갑", "wallet", "카드케이스", "카드홀더", "머니클립", "cardholder")
_OTHER_WORDS = (
    "이어폰", "헤드폰", "헤드셋", "버즈", "에어팟", "워치", "시계", "태블릿", "아이패드",
    "패드", "갤럭시탭", "노트북", "충전기", "케이블", "보조배터리", "케이스", "가방",
    "백팩", "파우치", "우산", "열쇠", "카드", "earphone", "earbud", "airpods", "buds",
    "watch", "tablet", "ipad", "laptop", "charger", "cable", "case", "bag",
)
_PHONE_EXACT = ("폰", "갤럭시", "galaxy", "phone", "smartphone", "cellphone", "휴대전화")
_PHONE_PREFIX = (
    "스마트폰", "휴대폰", "핸드폰", "아이폰", "iphone", "갤럭시s", "갤럭시z", "갤럭시a",
    "갤럭시폰", "갤럭시노트", "z플립", "z폴드", "플립", "폴드",
)


def _classify_token(token: str) -> str | None:
    if any(word in token for word in _WALLET_WORDS):
        return CATEGORY_WALLET
    if any(word in token for word in _OTHER_WORDS):
        return CATEGORY_OTHER
    if token in _PHONE_EXACT or token.startswith(_PHONE_PREFIX):
        return CATEGORY_PHONE
    return None


def normalize_category(value) -> str | None:
    """자유 텍스트 품명 → 스마트폰 / 지갑 / 기타. 빈 값은 None."""
    text = _clean(value).lower()
    if not text:
        return None
    if text in CATEGORIES:
        return text

    decided = None
    for token in re.findall(r"[0-9a-z가-힣]+", text):
        label = _classify_token(token)
        if label:
            decided = label
    return decided or CATEGORY_OTHER


# ---------------------------------------------------------
# 색상 (color) — VLM COLOR_LABELS와 같은 체계
# ---------------------------------------------------------
COLOR_MULTI = "다색"
COLOR_UNKNOWN = "미확인"

_COLOR_ALIASES = {
    "검정": ("검정", "검정색", "검은색", "검은", "까만색", "까만", "블랙", "black", "흑색"),
    "흰색": ("흰색", "흰", "하얀색", "하얀", "하양", "화이트", "white", "백색"),
    "회색": ("회색", "그레이", "gray", "grey", "쥐색"),
    "은색": ("은색", "실버", "silver"),
    "빨강": ("빨강", "빨간색", "빨간", "레드", "red", "적색"),
    "주황": ("주황", "주황색", "오렌지", "orange"),
    "노랑": ("노랑", "노란색", "노란", "옐로우", "옐로", "yellow"),
    "초록": ("초록", "초록색", "녹색", "연두", "연두색", "그린", "green"),
    "파랑": ("파랑", "파란색", "파란", "하늘색", "블루", "blue", "청색"),
    "남색": ("남색", "네이비", "navy", "곤색"),
    "보라": ("보라", "보라색", "퍼플", "purple", "라벤더"),
    "분홍": ("분홍", "분홍색", "핑크", "pink"),
    "갈색": ("갈색", "브라운", "brown", "밤색"),
    "베이지": ("베이지", "beige"),
    "금색": ("금색", "골드", "gold"),
    COLOR_MULTI: ("다색", "멀티", "알록달록", "multicolor", "multi"),
    COLOR_UNKNOWN: ("미확인", "모름", "모르겠음", "unknown", "불명"),
}
COLORS = tuple(_COLOR_ALIASES)

# 긴 별칭부터 매칭해야 "검은색"이 "은색"으로 잘못 잡히지 않는다
_COLOR_ALIAS_LIST = sorted(
    ((alias, color) for color, aliases in _COLOR_ALIASES.items() for alias in aliases),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


def normalize_color(value) -> str | None:
    """
    자유 텍스트 색상 → COLORS 중 하나. 빈 값은 None.
    서로 다른 색이 2개 이상이면 '다색', 알아볼 수 없으면 '미확인'.
    """
    text = _clean(value).lower().replace(" ", "")
    if not text:
        return None
    if text in COLORS:
        return text

    found = []
    remaining = text
    for alias, color in _COLOR_ALIAS_LIST:
        if alias in remaining:
            remaining = remaining.replace(alias, " ")  # 매칭된 부분은 다시 쓰지 않음
            if color not in found:
                found.append(color)

    found = [c for c in found if c != COLOR_UNKNOWN] or found
    if not found:
        return COLOR_UNKNOWN
    if len(found) > 1:
        return COLOR_MULTI
    return found[0]


# ---------------------------------------------------------
# 소재 (material)
# ---------------------------------------------------------
MATERIALS = ("가죽", "인조가죽", "천", "금속", "플라스틱", "실리콘", "유리", "기타")

_MATERIAL_ALIASES = [  # 순서 중요: 인조가죽을 가죽보다 먼저
    (("인조가죽", "합성가죽", "pu가죽", "faux"), "인조가죽"),
    (("가죽", "leather", "레더"), "가죽"),
    (("천", "패브릭", "fabric", "캔버스", "나일론", "cloth"), "천"),
    (("금속", "메탈", "metal", "알루미늄", "스테인리스", "티타늄"), "금속"),
    (("플라스틱", "plastic"), "플라스틱"),
    (("실리콘", "젤리", "silicone", "tpu"), "실리콘"),
    (("유리", "glass"), "유리"),
]


def normalize_material(value) -> str | None:
    text = _clean(value).lower().replace(" ", "")
    if not text:
        return None
    if text in MATERIALS:
        return text
    if text == "pu":  # 부분 문자열로 찾으면 "tpu"(실리콘)와 겹치므로 정확히 일치할 때만
        return "인조가죽"
    for aliases, label in _MATERIAL_ALIASES:
        if any(alias in text for alias in aliases):
            return label
    return "기타"


# ---------------------------------------------------------
# 식별수준: 기종을 얼마나 확신하는지
IDENTIFICATION_LEVELS = ("확인", "추정", "미확인")

# 지갑 종류 (스마트폰/기타면 NULL)
WALLET_TYPES = ("장지갑", "반지갑", "카드지갑")

# 확신도: AI는 높음/보통/낮음으로 답하고, DB에는 숫자로 저장한다
CONFIDENCE_SCORES = {"높음": 0.9, "보통": 0.6, "낮음": 0.3}
CONFIDENCE_LEVELS = tuple(CONFIDENCE_SCORES)


def confidence_to_score(value) -> float | None:
    """'높음'→0.9, '보통'→0.6, '낮음'→0.3, 그 외 None"""
    return CONFIDENCE_SCORES.get(_clean(value))


def _clean(value) -> str:
    return str(value).strip() if value is not None else ""


def normalize_identification_level(value) -> str | None:
    text = _clean(value)
    if not text:
        return None
    if text in IDENTIFICATION_LEVELS:
        return text
    aliases = {
        "confirmed": "확인", "확실": "확인",
        "estimated": "추정", "likely": "추정",
        "unknown": "미확인", "모름": "미확인",
    }
    return aliases.get(text.lower())


def normalize_wallet_type(value) -> str | None:
    text = _clean(value).replace(" ", "")
    if not text:
        return None
    if text in WALLET_TYPES:
        return text
    aliases = {
        "long": "장지갑", "longwallet": "장지갑",
        "bifold": "반지갑", "half": "반지갑",
        "card": "카드지갑", "cardholder": "카드지갑", "카드케이스": "카드지갑",
    }
    return aliases.get(text.lower())


def parse_optional_bool(value) -> bool | None:
    """'true'/'false'/'있음'/'없음' 등 → bool, 판단 불가/빈 값 → None"""
    if value is None or isinstance(value, bool):
        return value
    text = _clean(value).lower()
    if text in {"true", "1", "yes", "y", "있음", "o"}:
        return True
    if text in {"false", "0", "no", "n", "없음", "x"}:
        return False
    return None


def dump_str_list(value) -> str | None:
    """리스트(또는 JSON 배열 문자열/쉼표 구분 문자열)를 DB 저장용 JSON 문자열로."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [part for part in text.split(",")]
        value = parsed if isinstance(parsed, list) else [parsed]

    items = [str(v).strip() for v in value if v is not None and str(v).strip()]
    return json.dumps(items, ensure_ascii=False) if items else None


def load_str_list(value) -> list[str]:
    """DB의 JSON 문자열 → list[str]. 비어 있거나 깨진 값은 []."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(v) for v in parsed] if isinstance(parsed, list) else []
