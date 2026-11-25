import pytest

import labels


@pytest.mark.parametrize(
    "raw, expected",
    [
        # 기존 findyu.db 값
        ("이어폰 케이스", "이어폰"),
        ("야구공", "기타"),
        ("스마트시계", "기타"),
        ("갤럭시 버즈", "이어폰"),
        ("에어팟", "이어폰"),
        ("무선 이어폰", "이어폰"),
        ("가방", "기타"),
        # 이어폰 (v7): 이어폰 뒤의 케이스는 충전 케이스
        ("에어팟 프로 케이스", "이어폰"),
        ("AirPods Pro", "이어폰"),
        ("갤럭시 버즈2 프로", "이어폰"),
        ("버즈 케이스 낀 갤럭시", "스마트폰"),
        # 스마트폰
        ("스마트폰", "스마트폰"),
        ("휴대폰", "스마트폰"),
        ("핸드폰", "스마트폰"),
        ("아이폰 15 Pro", "스마트폰"),
        ("아이폰15", "스마트폰"),
        ("iPhone 13", "스마트폰"),
        ("갤럭시 S24", "스마트폰"),
        ("갤럭시S23 울트라", "스마트폰"),
        ("Z플립5", "스마트폰"),
        ("케이스 낀 아이폰", "스마트폰"),
        ("phone", "스마트폰"),
        # "폰"이 들어 있지만 스마트폰이 아닌 것
        ("헤드폰", "기타"),
        ("아이폰 케이스", "기타"),
        ("갤럭시 워치", "기타"),
        ("갤럭시탭", "기타"),
        # 지갑
        ("지갑", "지갑"),
        ("장지갑", "지갑"),
        ("검은 반지갑", "지갑"),
        ("카드지갑", "지갑"),
        ("카드케이스", "지갑"),
        ("wallet", "지갑"),
        ("가방 속 지갑", "지갑"),
        # 그 외
        ("카드", "기타"),
        ("기타", "기타"),
        ("뭔지 모르겠음", "기타"),
        (None, None),
        ("  ", None),
    ],
)
def test_normalize_category(raw, expected):
    assert labels.normalize_category(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("검은색", "검정"),
        ("검정", "검정"),
        ("검정색", "검정"),
        ("블랙", "검정"),
        ("Black", "검정"),
        ("흰색", "흰색"),
        ("하얀색", "흰색"),
        ("화이트", "흰색"),
        ("보라색", "보라"),
        ("은색", "은색"),
        ("실버", "은색"),
        ("남색", "남색"),
        ("네이비", "남색"),
        ("하늘색", "파랑"),
        ("진한 파란색", "파랑"),
        ("골드", "금색"),
        ("흰색, 검은색", "다색"),
        ("검정/빨강", "다색"),
        ("알록달록", "다색"),
        ("모르겠음", "미확인"),
        ("투명", "미확인"),
        ("검정 (모름)", "검정"),
        (None, None),
        ("", None),
    ],
)
def test_normalize_color(raw, expected):
    assert labels.normalize_color(raw) == expected


def test_canonical_values_are_fixed_points():
    for value in labels.CATEGORIES:
        assert labels.normalize_category(value) == value
    for value in labels.COLORS:
        assert labels.normalize_color(value) == value
    for value in labels.MATERIALS:
        assert labels.normalize_material(value) == value


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("소가죽", "가죽"),
        ("인조 가죽", "인조가죽"),
        ("PU", "인조가죽"),
        ("TPU", "실리콘"),
        ("젤리 케이스", "실리콘"),
        ("알루미늄", "금속"),
        ("나일론", "천"),
        ("나무", "기타"),
        (None, None),
    ],
)
def test_normalize_material(raw, expected):
    assert labels.normalize_material(raw) == expected


def test_enums_and_lists():
    assert labels.normalize_identification_level("추정") == "추정"
    assert labels.normalize_identification_level("아마도") is None
    assert labels.normalize_wallet_type("반 지갑") == "반지갑"
    assert labels.parse_optional_bool("false") is False
    assert labels.parse_optional_bool("") is None
    assert labels.dump_str_list('["a", " b ", ""]') == '["a", "b"]'
    assert labels.dump_str_list("a, b") == '["a", "b"]'
    assert labels.dump_str_list([]) is None
    assert labels.load_str_list('["카드 수납 개수"]') == ["카드 수납 개수"]
    assert labels.load_str_list("깨진값") == []


@pytest.mark.parametrize("raw, expected", [
    ("애플", "애플"), ("Apple", "애플"), ("삼성전자", "삼성"), ("Samsung", "삼성"),
    ("구글", "기타"), ("모르겠음", None), ("", None), (None, None),
])
def test_normalize_brand_choice(raw, expected):
    assert labels.normalize_brand_choice(raw) == expected


def test_earphone_components_and_closure():
    assert labels.normalize_earphone_components("케이스 + 이어버드") == "케이스+이어버드"
    assert labels.normalize_earphone_components("충전 케이스") == "케이스만"
    assert labels.normalize_earphone_components("유닛") == "이어버드만"
    assert labels.normalize_earphone_components("모름") is None
    assert labels.normalize_wallet_closure("스냅") == "똑딱이"
    assert labels.normalize_wallet_closure("지퍼") == "지퍼"
