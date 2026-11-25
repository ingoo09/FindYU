"""
등록(수동 등록 포함)·게이트웨이 검색 API 테스트.

conftest.py가 임시 DB·업로드 폴더와 mock 모드를 정해 두므로 실제 findyu.db와 API는 쓰지 않는다.
TestClient를 with 없이 써서 서버 시작 작업(분석 스레드)은 돌리지 않고, 백그라운드 작업은
main.analyze_registered_item을 직접 불러 흉내 낸다.
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
import models
from gemini_analyzer import AnalyzerConfigError, AnalyzerError
from gemini_embedding import MockEmbedder


# ---------------------------------------------------------
# 준비
# ---------------------------------------------------------
class CountingEmbedder(MockEmbedder):
    def __init__(self, error=None):
        super().__init__()
        self.error = error

    def embed_images(self, images):
        if self.error:
            self.calls += 1
            raise self.error
        return super().embed_images(images)


class AdapterSpy:
    """search_adapter.compare 대신. 받은 후보 순서를 기록하고 정해진 결과를 돌려준다."""

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def __call__(self, mode, query, candidates):
        self.calls.append({"mode": mode, "query": query, "ids": [c.id for c in candidates]})
        if self.error:
            raise self.error
        if self.result is not None:
            return main.search_adapter.validate_results(self.result, [c.id for c in candidates])
        return [{"id": c.id, "match_reasons": []} for c in candidates]


def _pattern(kind: str) -> bytes:
    """mock 임베딩이 서로 구분되는 합성 사진 (개인정보 없음)."""
    base = Image.linear_gradient("L")
    image = {
        "h": base,
        "v": base.rotate(90),
        "d": base.rotate(45),
        "c": Image.radial_gradient("L"),
    }[kind].convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch):
    db = main.SessionLocal()
    db.query(models.Item).delete()
    db.commit()
    db.close()

    monkeypatch.setattr(main, "SEARCH_ANALYZER_MODE", "mock")
    embedder = CountingEmbedder()
    monkeypatch.setattr(main, "_embedder", embedder)
    analysis_calls = []

    def fake_extract(images):
        analysis_calls.append(len(images))
        return {**main.EMPTY_ANALYSIS, "category": "스마트폰", "color": "검정", "model": "fake"}

    monkeypatch.setattr(main, "extract_item_info", fake_extract)
    spy = AdapterSpy()
    monkeypatch.setattr(main.search_adapter, "compare", spy)

    c = TestClient(main.app)
    c.embedder, c.analysis_calls, c.adapter = embedder, analysis_calls, spy
    return c


def _register(client, kind="h", run_worker=True, **form):
    files = [("image", (f"{kind}.jpg", _pattern(kind), "image/jpeg"))]
    data = {"item_type": "found", **form}
    resp = client.post("/items", data=data, files=files)
    assert resp.status_code == 200, resp.text
    item = resp.json()
    if run_worker:
        main.analyze_registered_item(item["id"])
    return item


def _get(client, item_id):
    return client.get(f"/items/{item_id}").json()


def _search(client, kind=None, **form):
    files = [("image", (f"q{kind}.jpg", _pattern(kind), "image/jpeg"))] if kind else None
    return client.post("/search", data=form, files=files)


# ---------------------------------------------------------
# 등록
# ---------------------------------------------------------
def test_defer_analysis_registers_immediately_without_analysis_call(client):
    item = _register(
        client, run_worker=False, defer_analysis="true",
        form_answers=json.dumps({"category": "지갑", "wallet_type": "반지갑"}), location="IT관",
    )
    assert item["status"] == "registered"
    assert item["form_values"]["wallet_type"] == "반지갑"

    # 백그라운드 작업이 돌아도 등록 분석은 부르지 않고, 사진 임베딩만 1회 시도
    main.analyze_registered_item(item["id"])
    assert client.analysis_calls == []
    assert client.embedder.calls == 1

    saved = _get(client, item["id"])
    assert saved["status"] == "registered"
    listed = client.get("/items", params={"item_type": "found"}).json()
    assert [i["id"] for i in listed["items"]] == [item["id"]]


def test_defer_analysis_rejects_bad_value(client):
    resp = client.post("/items", data={"item_type": "found", "defer_analysis": "maybe"},
                       files=[("image", ("a.jpg", _pattern("h"), "image/jpeg"))])
    assert resp.status_code == 400


def test_normal_registration_analyzes_then_embeds(client):
    item = _register(client, run_worker=False)
    assert item["status"] == "analyzing"
    main.analyze_registered_item(item["id"])
    assert client.analysis_calls == [1]

    db = main.SessionLocal()
    row = db.get(models.Item, item["id"])
    assert row.status == "registered"
    assert row.image_embedding_model == MockEmbedder.model_id
    assert len(json.loads(row.image_embedding_gemini)) == 256
    assert row.embedding is None  # DINOv2 칸은 건드리지 않음
    db.close()


def test_embedding_failure_leaves_null_and_keeps_registration(client, monkeypatch):
    failing = CountingEmbedder(error=AnalyzerError("임베딩 API 오류 (503): busy"))
    monkeypatch.setattr(main, "_embedder", failing)
    item = _register(client)
    db = main.SessionLocal()
    row = db.get(models.Item, item["id"])
    assert (row.status, row.image_embedding_gemini) == ("registered", None)
    db.close()
    assert failing.calls == 1  # 1회만 시도


# ---------------------------------------------------------
# 사진 검색
# ---------------------------------------------------------
def test_image_search_ranks_by_embedding_then_fills_with_spec_order(client, monkeypatch):
    h = _register(client, "h")
    v = _register(client, "v")
    d = _register(client, "d")
    # 임베딩 없는 물품 (임베딩 실패) → 임베딩 순위 뒤, 명세 순서로
    monkeypatch.setattr(main, "_embedder", CountingEmbedder(error=AnalyzerError("x")))
    no_emb = _register(client, "c")
    monkeypatch.setattr(main, "_embedder", client.embedder)
    client.embedder.calls = 0

    resp = _search(client, "v")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert client.embedder.calls == 1                 # 검색 사진 임베딩 1회
    assert len(client.adapter.calls) == 1             # 비교 1회
    sent = client.adapter.calls[0]["ids"]
    assert sent[0] == v["id"]                          # 같은 사진이 1순위로 보내짐
    assert sent[-1] == no_emb["id"]                    # 임베딩 없는 물품은 마지막
    assert set(sent) == {h["id"], v["id"], d["id"], no_emb["id"]}
    assert body["evaluated_count"] == 4
    assert body["selection"] == {"by_embedding": 3, "by_order": 1}
    assert body["search_kind"] == "image"

    first = body["results"][0]
    assert first["id"] == v["id"] and first["rank"] == 1
    assert first["match_reasons"] == [] and first["filter_check"] == {}
    for field in main.LEGACY_SCORE_FIELDS:
        assert first[field] is None                    # 구형 점수 필드는 null
    assert "embedding_ms" in body["timings"] and "compare_ms" in body["timings"]


def test_results_follow_adapter_order_and_top_k_cap(client):
    items = [_register(client, k) for k in ("h", "v", "d", "c", "h", "v")]
    ids = [i["id"] for i in items]
    client.adapter.result = {"results": [{"id": i, "match_reasons": ["근거"]} for i in reversed(ids)]}
    body = _search(client, "h", top_k="20").json()
    assert [r["id"] for r in body["results"]] == list(reversed(ids))[:5]   # Top-5 이내
    assert body["results"][0]["match_reasons"] == ["근거"]


def test_candidates_capped_at_ten(client):
    for _ in range(12):
        _register(client, "h")
    body = _search(client, "h").json()
    assert len(client.adapter.calls[0]["ids"]) == 10
    assert body["evaluated_count"] == 10
    assert body["total_candidates"] == 12


def test_unreadable_photo_is_skipped_in_image_search(client):
    a = _register(client, "h")
    b = _register(client, "v")
    Path(main.UPLOAD_DIR, Path(_get(client, a["id"])["image_path"]).name).unlink()
    _search(client, "h")
    assert client.adapter.calls[0]["ids"] == [b["id"]]


@pytest.mark.parametrize("make_result", [
    lambda item_id: {"results": [{"id": item_id}, {"id": 999999}]},   # 보내지 않은 ID
    lambda item_id: {"results": [{"id": str(item_id)}]},              # 정수가 아닌 ID
    lambda item_id: {"results": [{"id": item_id}, {"id": item_id}]},  # 중복 ID
    lambda item_id: "not a dict",                                       # 형식 오류
])
def test_bad_adapter_output_is_502(client, make_result):
    item = _register(client, "h")
    client.adapter.result = make_result(item["id"])
    resp = _search(client, "h")
    assert resp.status_code == 502
    assert resp.json()["detail"]


@pytest.mark.parametrize("error, status", [
    (AnalyzerError("검색 비교 실패 (504)"), 502),
    (AnalyzerConfigError("검색 비교 어댑터(backend/search_analyzer.py)가 아직 없습니다."), 503),
])
def test_adapter_gateway_errors(client, error, status):
    _register(client, "h")
    client.adapter.error = error
    assert _search(client, "h").status_code == status


def test_query_embedding_failure_is_502(client, monkeypatch):
    _register(client, "h")
    monkeypatch.setattr(main, "_embedder", CountingEmbedder(error=AnalyzerError("임베딩 API 오류 (500)")))
    assert _search(client, "h").status_code == 502


def test_zero_candidates_is_200_without_ai_calls(client):
    _register(client, "h")  # 품목: 스마트폰 (fake 분석)
    client.embedder.calls = 0
    resp = _search(client, "h", category="지갑")
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == [] and body["total_candidates"] == 0 and body["evaluated_count"] == 0
    assert client.embedder.calls == 0 and client.adapter.calls == []


def test_empty_db_search_is_200(client):
    resp = _search(client, description="흰색 무선 이어폰")
    assert resp.status_code == 200 and resp.json()["results"] == []
    assert client.adapter.calls == []


# ---------------------------------------------------------
# 자연어 검색
# ---------------------------------------------------------
def test_text_search_uses_spec_order_and_no_embedding(client):
    a = _register(client, "h", location="중앙도서관")
    b = _register(client, "v", location="IT관(E21)")
    c = _register(client, "d", location="공학관")
    client.embedder.calls = 0

    body = _search(client, description="검은색 아이폰", location="IT관").json()
    assert client.embedder.calls == 0                   # 문장→사진 임베딩은 쓰지 않음
    call = client.adapter.calls[0]
    assert call["query"].kind == "text" and call["query"].text == "검은색 아이폰"
    assert call["ids"] == [b["id"], c["id"], a["id"]]   # 장소 일치 → 최신순
    assert body["search_kind"] == "text" and body["embedding_model"] is None


def test_text_search_includes_photoless_items(client):
    a = _register(client, "h")
    Path(main.UPLOAD_DIR, Path(_get(client, a["id"])["image_path"]).name).unlink()
    _search(client, description="검은색 아이폰")
    assert client.adapter.calls[0]["ids"] == [a["id"]]  # 사진이 없어도 저장된 외형 정보로 비교


def test_filter_only_search_does_not_call_ai(client):
    a = _register(client, "h")
    body = _search(client, category="스마트폰").json()
    assert [r["id"] for r in body["results"]] == [a["id"]]
    assert client.adapter.calls == [] and body["evaluated_count"] == 0


def test_candidate_payload_has_no_paths(client):
    _register(client, "h", location="IT관")
    _search(client, description="검은색 아이폰")
    # AdapterSpy는 SearchCandidate 객체를 받는다: 경로·URL 필드가 없어야 함
    import search_adapter
    fields = set(search_adapter.SearchCandidate.__dataclass_fields__)
    assert not fields & {"image_path", "image_url", "images"}


# ---------------------------------------------------------
# 로컬 모델 없이 시작
# ---------------------------------------------------------
def test_server_start_does_not_load_local_models(tmp_path):
    """서버 시작 작업(분석 스레드)을 돌려도 baze·mock 모드에서는 DINOv2·SigLIP2를 불러오지 않는다."""
    code = (
        "import time, main\n"
        "main.start_analysis_worker()\n"
        "time.sleep(1)\n"
        "m = main._retrieval_models\n"
        "print('LOADED' if (m._dino_model or m._siglip_model) else 'NOT_LOADED')\n"
    )
    env = {
        **os.environ,
        "FINDYU_DB_PATH": str(tmp_path / "findyu.db"),
        "FINDYU_UPLOAD_DIR": str(tmp_path),
        "FINDYU_SEARCH_ANALYZER_MODE": "mock",
        "FINDYU_REGISTRATION_ANALYZER_MODE": "mock",
    }
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(main.__file__).parent, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert "NOT_LOADED" in out.stdout, out.stdout + out.stderr
