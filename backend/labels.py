"""
휴대폰·지갑 전용 필드의 허용값과 정규화 함수.

DB에는 한국어 라벨을 그대로 저장한다.
"""

import json

# 식별수준: 기종을 얼마나 확신하는지
IDENTIFICATION_LEVELS = ("확인", "추정", "미확인")

# 지갑 종류 (스마트폰/기타면 NULL)
WALLET_TYPES = ("장지갑", "반지갑", "카드지갑")


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
