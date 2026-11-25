import sys
import types

import pytest

import search_adapter as sa
from gemini_analyzer import AnalyzerConfigError


def _cands(*ids):
    return [sa.SearchCandidate(id=i, description=f"물품 {i}") for i in ids]


QUERY = sa.SearchQuery(kind="text", text="흰색 무선 이어폰")


def test_mock_keeps_order_without_reasons():
    assert sa.compare("mock", QUERY, _cands(3, 1, 2)) == [
        {"id": 3, "match_reasons": []}, {"id": 1, "match_reasons": []}, {"id": 2, "match_reasons": []},
    ]


def test_no_candidates_no_call(monkeypatch):
    monkeypatch.setattr(sa, "_load_analyzer", lambda: pytest.fail("후보가 없으면 부르지 않아야 함"))
    assert sa.compare("baze", QUERY, []) == []


def test_too_many_candidates():
    with pytest.raises(ValueError):
        sa.compare("mock", QUERY, _cands(*range(1, 12)))


@pytest.mark.parametrize("raw, message", [
    ([], "형식"),
    ({"results": "x"}, "형식"),
    ({"results": [1]}, "항목 형식"),
    ({"results": [{"id": "1"}]}, "정수"),
    ({"results": [{"id": True}]}, "정수"),
    ({"results": [{"id": 99}]}, "보내지 않은"),
    ({"results": [{"id": 1}, {"id": 1}]}, "중복"),
    ({"results": [{"id": 1, "match_reasons": "같은 색"}]}, "문자열 배열"),
    ({"results": [{"id": 1, "match_reasons": [1]}]}, "문자열 배열"),
])
def test_validate_rejects_bad_output(raw, message):
    with pytest.raises(sa.AdapterOutputError, match=message):
        sa.validate_results(raw, [1, 2])


def test_validate_cleans_reasons_and_allows_subset():
    raw = {"results": [
        {"id": 2, "match_reasons": [" 흰색 케이스 ", "", "a", "b", "c"]},
        {"id": 1, "match_reasons": None},
    ]}
    assert sa.validate_results(raw, [1, 2, 3]) == [
        {"id": 2, "match_reasons": ["흰색 케이스", "a", "b"]},
        {"id": 1, "match_reasons": []},
    ]


def test_baze_without_ai_module_is_config_error(monkeypatch):
    monkeypatch.setattr(sa.importlib, "import_module", lambda name: (_ for _ in ()).throw(
        ModuleNotFoundError(f"No module named '{name}'", name=name)))
    with pytest.raises(AnalyzerConfigError, match="search_analyzer.py"):
        sa.compare("baze", QUERY, _cands(1))


def test_baze_calls_ai_module_with_plain_dicts(monkeypatch):
    seen = {}

    def compare(query, candidates):
        seen["query"], seen["candidates"] = query, candidates
        return {"results": [{"id": 2, "match_reasons": ["흰색"]}]}

    module = types.ModuleType(sa.ANALYZER_MODULE)
    module.compare = compare
    monkeypatch.setitem(sys.modules, sa.ANALYZER_MODULE, module)

    result = sa.compare("baze", QUERY, _cands(1, 2))
    assert result == [{"id": 2, "match_reasons": ["흰색"]}]
    assert seen["query"] == {"kind": "text", "text": "흰색 무선 이어폰", "image_jpeg": None,
                             "location": None, "occurred_at": None}
    assert [c["id"] for c in seen["candidates"]] == [1, 2]
    assert set(seen["candidates"][0]) == {"id", "category", "description", "form_values",
                                          "location", "occurred_at", "image_jpeg"}


def test_default_mode_is_mock_until_ai_adapter_is_merged():
    # search_analyzer.py가 병합되면 "baze"로 바꾸고 이 테스트도 고친다
    assert sa.DEFAULT_MODE == "mock"
