import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

import models
import paths
from database import Base, SessionLocal, engine

TOOL = Path(__file__).resolve().parents[1] / "tools" / "backfill_gemini_embeddings.py"


@pytest.fixture
def tool(monkeypatch):
    spec = importlib.util.spec_from_file_location("backfill_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("FINDYU_SEARCH_ANALYZER_MODE", "mock")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.query(models.Item).delete()
    for name in ("a.jpg", "b.jpg"):
        Image.linear_gradient("L").convert("RGB").save(paths.UPLOAD_DIR / name)
    rows = [
        # (id, item_type, status, image, 기존 임베딩 모델)
        (1, "found", "registered", "uploads/a.jpg", None),                 # 대상
        (2, "found", "registered", "uploads/b.jpg", "gemini-embedding-2@256"),  # 다른 모델 → 대상
        (3, "found", "registered", "uploads/missing.jpg", None),           # 사진 없음 → 건너뜀
        (4, "lost", "registered", "uploads/a.jpg", None),                  # 분실물 → 제외
        (5, "found", "analysis_failed", "uploads/a.jpg", None),            # 실패 → 제외
        (6, "found", "registered", "uploads/a.jpg", "mock-pixels@256"),    # 이미 있음 → 제외
    ]
    for item_id, item_type, status, image, model in rows:
        db.add(models.Item(
            id=item_id, item_type=item_type, status=status, image_path=image,
            image_embedding_gemini=json.dumps([0.0]) if model else None, image_embedding_model=model,
        ))
    db.commit()
    db.close()
    return module


def _models():
    db = SessionLocal()
    try:
        return {i.id: i.image_embedding_model for i in db.query(models.Item).order_by(models.Item.id)}
    finally:
        db.close()


def test_dry_run_shows_counts_without_changes(tool, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("dry-run은 묻지 않아야 함"))
    assert tool.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "대상 습득물: 3건 (대표 사진 있음 2건, 없음 1건)" in out
    assert "게이트웨이 호출 예정: 0회" in out   # mock 모드
    assert _models()[1] is None


def test_cancel_keeps_db(tool, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    tool.main([])
    assert _models()[1] is None


def test_confirm_fills_targets_only(tool, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert tool.main(["--batch", "1"]) == 0
    result = _models()
    assert result[1] == result[2] == "mock-pixels@256"
    assert result[3] is None and result[4] is None and result[5] is None


def test_local_mode_needs_nothing(tool, monkeypatch, capsys):
    monkeypatch.setenv("FINDYU_SEARCH_ANALYZER_MODE", "local")
    assert tool.main([]) == 0
    assert "필요 없습니다" in capsys.readouterr().out
