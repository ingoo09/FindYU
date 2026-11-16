import shutil
import sqlite3
from pathlib import Path

import pytest

import migrations

LEGACY_SCHEMA = """
CREATE TABLE items (
    id INTEGER NOT NULL,
    item_type VARCHAR NOT NULL,
    category VARCHAR,
    color VARCHAR,
    brand VARCHAR,
    description TEXT,
    image_path VARCHAR,
    embedding TEXT,
    location VARCHAR,
    occurred_at DATETIME,
    status VARCHAR,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);
"""

LEGACY_ROWS = [
    (1, "found", "이어폰 케이스", "흰색, 검은색", "모르겠음", "토끼 그림", "uploads/a.jpeg", "[0.1, 0.2]", "IT관(E21)", None, "registered"),
    (2, "found", "무선 이어폰", "흰색", "삼성", "키가 달려 있음", "uploads\\b.jpg", "[0.3]", "IT관(E21)", None, "registered"),
    (3, "found", "가방", "검은색", "SQ", None, "uploads\\c.jpg", None, None, None, "registered"),
]


@pytest.fixture
def legacy_db(tmp_path) -> Path:
    db_path = tmp_path / "findyu.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(LEGACY_SCHEMA)
    conn.executemany(
        "INSERT INTO items (id, item_type, category, color, brand, description, image_path,"
        " embedding, location, occurred_at, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        LEGACY_ROWS,
    )
    conn.commit()
    conn.close()
    return db_path


def _rows(db_path, columns):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT {', '.join(columns)} FROM items ORDER BY id").fetchall()
    finally:
        conn.close()


def _columns(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(items)")]
    finally:
        conn.close()


def test_migrates_legacy_db(legacy_db):
    applied = migrations.run_migrations(legacy_db)

    assert applied == [v for v, _ in migrations.MIGRATIONS]
    assert migrations.get_version(legacy_db) == migrations.LATEST_VERSION

    columns = _columns(legacy_db)
    for name, _ in migrations.NEW_COLUMNS + migrations.V4_COLUMNS:
        assert name in columns

    # 역슬래시 경로 정규화
    assert [r[0] for r in _rows(legacy_db, ["image_path"])] == [
        "uploads/a.jpeg", "uploads/b.jpg", "uploads/c.jpg",
    ]

    # 데이터 손실 없음: 행 수, 임베딩, 위치, 설명 유지
    assert _rows(legacy_db, ["id", "embedding", "location", "description", "status"]) == [
        (r[0], r[7], r[8], r[5], r[10]) for r in LEGACY_ROWS
    ]

    # 라벨 정규화
    assert _rows(legacy_db, ["category", "color"]) == [
        ("기타", "다색"), ("기타", "흰색"), ("기타", "검정"),
    ]

    # 새 컬럼은 비어 있음
    assert _rows(legacy_db, [name for name, _ in migrations.NEW_COLUMNS])[0] == (None,) * len(migrations.NEW_COLUMNS)


def test_creates_backup_only_when_needed(legacy_db):
    migrations.run_migrations(legacy_db)
    backups = list(legacy_db.parent.glob("findyu.db.bak-*"))
    assert len(backups) == 1
    # 백업은 마이그레이션 전 상태
    assert migrations.get_version(backups[0]) == 0
    assert "device_model" not in _columns(backups[0])

    # 두 번째 실행은 아무 것도 하지 않고 백업도 만들지 않음
    assert migrations.run_migrations(legacy_db) == []
    assert len(list(legacy_db.parent.glob("findyu.db.bak-*"))) == 1


def test_idempotent_data(legacy_db):
    migrations.run_migrations(legacy_db)
    before = _rows(legacy_db, ["*"])
    migrations.run_migrations(legacy_db)
    assert _rows(legacy_db, ["*"]) == before


def test_failed_step_rolls_back(legacy_db, monkeypatch):
    def boom(conn):
        conn.execute("UPDATE items SET color = 'XXX'")
        raise RuntimeError("fail")

    monkeypatch.setattr(
        migrations, "MIGRATIONS", migrations.MIGRATIONS + [(migrations.LATEST_VERSION + 1, boom)]
    )
    with pytest.raises(RuntimeError):
        migrations.run_migrations(legacy_db)

    # 실패한 단계 이전까지만 적용되고, 실패한 단계의 변경은 롤백됨
    assert migrations.get_version(legacy_db) == migrations.LATEST_VERSION
    assert "XXX" not in [r[0] for r in _rows(legacy_db, ["color"])]


def test_empty_new_db_no_backup(tmp_path):
    db_path = tmp_path / "findyu.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(LEGACY_SCHEMA)
    conn.close()

    migrations.run_migrations(db_path)
    assert not list(tmp_path.glob("findyu.db.bak-*"))
    assert migrations.get_version(db_path) == migrations.LATEST_VERSION


def test_real_findyu_db_copy(tmp_path):
    """저장소의 실제 findyu.db 복사본으로 검증 (원본은 건드리지 않음)."""
    src = Path(__file__).resolve().parents[1] / "findyu.db"
    if not src.exists():
        pytest.skip("findyu.db 없음")
    db_path = tmp_path / "findyu.db"
    shutil.copy(src, db_path)

    before_count = _rows(db_path, ["COUNT(*)"])[0][0]
    before_embeddings = _rows(db_path, ["id", "embedding"])

    migrations.run_migrations(db_path)

    assert _rows(db_path, ["COUNT(*)"])[0][0] == before_count
    assert _rows(db_path, ["id", "embedding"]) == before_embeddings
    assert all("\\" not in (r[0] or "") for r in _rows(db_path, ["image_path"]))

    import labels
    for category, color in _rows(db_path, ["category", "color"]):
        assert category is None or category in labels.CATEGORIES
        assert color is None or color in labels.COLORS
