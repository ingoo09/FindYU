import json
from types import SimpleNamespace

import pytest

import check_form as cf
import labels


def _analysis(**overrides):
    data = {
        "category": "스마트폰",
        "color": "검정",
        "manufacturer": "애플",
        "brand": "애플",
        "device_model": "iPhone 15 Pro",
        "device_model_candidates": [],
        "identification_level": "확인",
        "has_case": True,
        "has_card_wallet": None,
        "earphone_components": None,
        "wallet_type": None,
        "material": None,
        "wallet_closure": None,
        "verification_needed": [],
        "confidence": {"category": "높음", "manufacturer": "높음", "device_model": "높음", "color": "높음"},
    }
    data.update(overrides)
    return data


def _item(**overrides):
    data = {
        "id": 1, "category": None, "color": None, "brand": None, "manufacturer": None,
        "device_model": None, "device_model_candidates": None, "identification_level": None,
        "has_case": None, "has_card_wallet": None, "earphone_components": None,
        "wallet_type": None, "material": None, "wallet_closure": None,
        "category_confidence": None, "manufacturer_confidence": None,
        "device_model_confidence": None, "color_confidence": None, "field_sources": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


# ---------------------------------------------------------
# form-schema
# ---------------------------------------------------------
def test_each_category_has_fields_with_unknown_option():
    schema = cf.form_schema()
    assert schema["categories"] == list(labels.CATEGORIES)
    assert "모르겠음" in schema["category_field"]["options"]
    for category in (labels.CATEGORY_PHONE, labels.CATEGORY_EARPHONE, labels.CATEGORY_WALLET):
        fields = schema["forms"][category]
        assert 4 <= len(fields) <= 6, category
        for fld in fields:
            if fld["type"] == "choice":
                assert fld["options"][-1] == "모르겠음"
            else:
                assert fld["unknown_option"] == "모르겠음"


def test_schema_options_follow_labels():
    forms = cf.form_schema()["forms"]
    by_key = lambda cat: {f["key"]: f for f in forms[cat]}
    phone, earphone, wallet = by_key("스마트폰"), by_key("이어폰"), by_key("지갑")
    assert set(phone) == {"brand", "device_model", "color", "has_case", "has_card_wallet"}
    assert set(earphone) == {"brand", "color", "earphone_components", "has_cover"}
    assert set(wallet) == {"wallet_type", "material", "color", "wallet_closure"}
    assert earphone["brand"]["options"] == ["애플", "삼성", "기타", "모르겠음"]
    assert wallet["wallet_type"]["options"][:-1] == list(labels.WALLET_TYPES)
    assert wallet["material"]["options"][:-1] == list(labels.MATERIALS)
    assert earphone["earphone_components"]["options"][:-1] == list(labels.EARPHONE_COMPONENTS)
    # 색상: labels.COLORS에서 '미확인' 대신 '모르겠음'
    assert phone["color"]["options"] == [c for c in labels.COLORS if c != "미확인"] + ["모르겠음"]


def test_single_category_schema_and_invalid_category():
    schema = cf.form_schema("지갑")
    assert schema["category"] == "지갑"
    assert [f["key"] for f in schema["fields"]] == ["wallet_type", "material", "color", "wallet_closure"]
    with pytest.raises(ValueError):
        cf.validate_category("헤드폰")
    assert cf.validate_category("모르겠음") is None


# ---------------------------------------------------------
# 분석 → 체크 폼
# ---------------------------------------------------------
def _fields(form):
    return {f["key"]: f for f in form["fields"]}


def test_confident_values_do_not_need_check():
    form = cf.build_check_form(_analysis(has_card_wallet=False), image_count=3)
    fields = _fields(form)
    assert form["category"] == {"ai_value": "스마트폰", "needs_check": False, "check_reasons": []}
    assert fields["brand"]["ai_value"] == "애플" and not fields["brand"]["needs_check"]
    assert fields["has_case"]["ai_value"] == "있음" and not fields["has_case"]["needs_check"]
    assert fields["has_card_wallet"]["ai_value"] == "없음"
    assert not fields["device_model"]["needs_check"]
    assert form["photo_hint"] is None


def test_low_confidence_candidates_and_unknown_need_check():
    form = cf.build_check_form(_analysis(
        manufacturer="삼성전자", device_model="iPhone Pro 시리즈",
        device_model_candidates=["iPhone 14 Pro", "iPhone 15 Pro"], identification_level="확인",
        color="다색",
        confidence={"category": "높음", "manufacturer": "낮음", "device_model": "보통", "color": "보통"},
    ), image_count=2)
    fields = _fields(form)
    assert fields["brand"]["ai_value"] == "삼성"
    assert fields["brand"]["needs_check"] and "확신도 낮음" in fields["brand"]["check_reasons"]
    assert fields["device_model"]["needs_check"]
    assert "대안 후보 있음" in fields["device_model"]["check_reasons"]
    assert "세대 구분 근거 없음" in fields["device_model"]["check_reasons"]  # 시리즈는 확인이어도 애매
    assert fields["device_model"]["suggestions"] == ["iPhone Pro 시리즈", "iPhone 14 Pro", "iPhone 15 Pro"]
    assert fields["color"]["needs_check"]
    # AI가 판단하지 못한 항목
    assert fields["has_card_wallet"]["ai_value"] == "모르겠음"
    assert fields["has_card_wallet"]["needs_check"]


def test_low_category_confidence_flags_everything():
    form = cf.build_check_form(_analysis(
        confidence={"category": "낮음", "manufacturer": "높음", "device_model": "높음", "color": "높음"},
    ), image_count=1)
    assert form["category"]["needs_check"]
    assert all(f["needs_check"] for f in form["fields"])


def test_unknown_category_has_no_fields():
    form = cf.build_check_form(_analysis(category=None), image_count=1)
    assert form["category"]["ai_value"] == "모르겠음" and form["category"]["needs_check"]
    assert form["fields"] == []
    assert form["photo_hint"]


@pytest.mark.parametrize("overrides, image_count, expected", [
    ({"identification_level": "추정", "verification_needed": ["측면 사진 없음 (액션 버튼 여부 확인 불가)"]}, 2, "측면"),
    ({"identification_level": "추정", "verification_needed": ["전면 사진 없음"]}, 2, "전면"),
    ({"identification_level": "추정", "verification_needed": []}, 1, "측면"),
    ({"identification_level": "확인"}, 1, None),
    ({"category": "이어폰", "earphone_components": None}, 1, "충전 케이스를 연"),
    ({"category": "이어폰", "earphone_components": "케이스만"}, 1, None),
    ({"category": "지갑", "wallet_type": None, "material": "가죽"}, 1, "펼친"),
    ({"category": "지갑", "wallet_type": "반지갑", "material": "가죽"}, 1, None),
    ({"category": "기타"}, 1, None),
])
def test_photo_hint(overrides, image_count, expected):
    hint = cf.photo_hint(_analysis(**overrides), image_count)
    if expected is None:
        assert hint is None
    else:
        assert expected in hint


def test_earphone_cover_uses_has_case():
    form = cf.build_check_form(_analysis(
        category="이어폰", device_model=None, has_case=False, earphone_components="케이스+이어버드",
    ), image_count=2)
    fields = _fields(form)
    assert fields["has_cover"]["ai_value"] == "없음"
    assert fields["earphone_components"]["ai_value"] == "케이스+이어버드"


# ---------------------------------------------------------
# 등록: 사람 > AI
# ---------------------------------------------------------
def test_resolve_answers_validates_and_skips_unknown():
    human = cf.resolve_answers(
        {"color": "빨강", "has_case": "없음", "brand": "모르겠음", "has_card_wallet": ""},
        fallback_category="스마트폰",
    )
    assert human.category is None
    assert human.columns == {"color": "빨강", "has_case": False}
    assert human.answered == ["color", "has_case"]

    with pytest.raises(ValueError):
        cf.resolve_answers({"color": "투명"}, fallback_category="스마트폰")
    with pytest.raises(ValueError):  # 지갑 항목인데 품목은 스마트폰
        cf.resolve_answers({"wallet_type": "반지갑"}, fallback_category="스마트폰")


def test_human_category_switches_form():
    human = cf.resolve_answers({"category": "지갑", "wallet_type": "반지갑"}, fallback_category="스마트폰")
    assert human.category == "지갑"
    assert human.columns == {"wallet_type": "반지갑"}


def test_apply_human_overrides_and_keeps_specific_ai_brand():
    item = _item(category="스마트폰")
    ai = _analysis(manufacturer="삼성전자")
    human = cf.resolve_answers({"brand": "삼성", "color": "빨강"}, fallback_category="스마트폰")
    sources = cf.apply_human(item, human, ai)
    assert item.manufacturer == "삼성전자"  # 같은 선택지면 더 구체적인 AI 값 유지
    assert item.color == "빨강"
    assert sources == {"brand": "human", "color": "human"}

    item = _item(category="스마트폰")
    cf.apply_human(item, cf.resolve_answers({"brand": "기타"}, "스마트폰"), ai)
    assert item.manufacturer == "기타"


def test_apply_human_before_ai_category_is_set():
    """습득자가 품목을 고르지 않으면 item.category는 비어 있다 → AI 품목 폼 기준으로 저장."""
    item = _item(category=None)
    human = cf.resolve_answers({"device_model": "iPhone 15 Pro", "color": "모르겠음"}, fallback_category="스마트폰")
    sources = cf.apply_human(item, human, _analysis(device_model="iPhone Pro 시리즈"))
    assert item.device_model == "iPhone 15 Pro"
    assert item.color is None  # 모르겠음 → AI 값이 나중에 채움
    assert sources == {"device_model": "human"}


def test_merge_sources_keeps_human():
    merged = cf.merge_sources(None, {"color": "human"})
    merged = cf.merge_sources(merged, {"color": "ai", "has_case": "ai"})
    assert json.loads(merged) == {"color": "human", "has_case": "ai"}


def test_column_allowed_by_category():
    assert cf.column_allowed("has_case", "이어폰")
    assert not cf.column_allowed("wallet_type", "스마트폰")
    assert cf.column_allowed("color", "기타")


def test_item_form_values():
    item = _item(category="이어폰", manufacturer="삼성전자", has_case=True, color="흰색")
    assert cf.item_form_values(item) == {
        "category": "이어폰", "brand": "삼성", "color": "흰색",
        "earphone_components": "모르겠음", "has_cover": "있음",
    }


# ---------------------------------------------------------
# 검색 필터
# ---------------------------------------------------------
def test_parse_filters():
    category, filters = cf.parse_filters("스마트폰", json.dumps({"color": "검정", "has_case": "모르겠음", "brand": "애플"}))
    assert category == "스마트폰"
    assert [(f.key, v) for f, v in filters] == [("color", "검정"), ("brand", "애플")]

    assert cf.parse_filters(None, None) == (None, [])
    assert cf.parse_filters("모르겠음", '{"color": "모르겠음"}') == (None, [])
    with pytest.raises(ValueError):
        cf.parse_filters(None, '{"color": "검정"}')
    with pytest.raises(ValueError):
        cf.parse_filters("지갑", '{"has_case": "있음"}')


def test_match_filters():
    category, filters = cf.parse_filters("스마트폰", json.dumps({"color": "검정", "brand": "삼성", "has_case": "있음"}))
    match = lambda **kw: cf.match_filters(_item(**kw), category, filters)

    assert match(category="스마트폰", color="검정", manufacturer="삼성전자", has_case=True) == {
        "category": "일치", "color": "일치", "brand": "일치", "has_case": "일치",
    }
    # 습득물 쪽 값을 모르면 빼지 않음
    assert match(category="스마트폰", color=None, manufacturer=None, has_case=None) == {
        "category": "일치", "color": "미확인", "brand": "미확인", "has_case": "미확인",
    }
    assert match(category=None, color="미확인")["category"] == "미확인"
    # 하나라도 다르면 탈락
    assert match(category="지갑") is None
    assert match(category="스마트폰", color="흰색") is None
    assert match(category="스마트폰", has_case=False) is None
    assert match(category="스마트폰", manufacturer="애플") is None


def test_match_device_model_filter():
    _, filters = cf.parse_filters("스마트폰", '{"device_model": "iphone 15pro"}')
    m = lambda **kw: cf.match_filters(_item(category="스마트폰", **kw), "스마트폰", filters)
    assert m(device_model="iPhone 15 Pro")["device_model"] == "일치"
    assert m(device_model="iPhone 14 Pro", device_model_candidates='["iPhone 15 Pro"]')["device_model"] == "일치"
    assert m(device_model="iPhone Pro 시리즈")["device_model"] == "미확인"
    assert m(device_model="iPhone 11") is None


# ---------------------------------------------------------
# 분석 결과 보관
# ---------------------------------------------------------
def test_analysis_cache_matches_same_photos_in_any_order():
    now = [0.0]
    cache = cf.AnalysisCache(ttl_seconds=10, max_entries=2, clock=lambda: now[0])
    digests = cf.image_digests([b"a", b"b"])
    analysis_id = cache.put({"category": "지갑"}, digests)

    assert cache.get(analysis_id, cf.image_digests([b"b", b"a"])) == {"category": "지갑"}
    assert cache.get(analysis_id, cf.image_digests([b"a"])) is None
    assert cache.get("unknown", digests) is None
    assert cache.get(None, digests) is None

    now[0] = 11
    assert cache.get(analysis_id, digests) is None


def test_analysis_cache_evicts_oldest():
    now = [0.0]
    cache = cf.AnalysisCache(max_entries=2, clock=lambda: now[0])
    first = cache.put({"n": 1}, ["x"])
    now[0] = 1
    cache.put({"n": 2}, ["x"])
    now[0] = 2
    cache.put({"n": 3}, ["x"])
    assert cache.get(first, ["x"]) is None


def test_answers_without_any_category():
    assert cf.resolve_answers({"color": "모르겠음"}, fallback_category=None).columns == {}
    with pytest.raises(ValueError, match="품목을 선택"):
        cf.resolve_answers({"color": "검정"}, fallback_category=None)
