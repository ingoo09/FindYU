"""
SQLite 자동 마이그레이션.

SQLAlchemy의 create_all은 "없는 테이블"만 만들고 기존 테이블에 컬럼을 추가하지 않는다.
그래서 서버 시작 시 run_migrations()가 PRAGMA user_version을 버전 번호로 사용해
아직 적용되지 않은 단계만 순서대로 실행한다.

- 각 단계는 하나의 트랜잭션으로 실행된다 (실패하면 그 단계 전체가 롤백되고 서버 시작 중단).
- 기존 데이터가 있는 DB를 마이그레이션하기 전에 findyu.db.bak-<시각> 백업을 만든다.
- 이미 적용된 단계는 건너뛰므로 여러 번 실행해도 안전하다.

새 단계를 추가할 때는 함수를 만들고 MIGRATIONS 끝에 (다음 번호, 함수)를 붙이면 된다.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from labels import CATEGORY_EARPHONE, CATEGORY_OTHER, is_earphone_text, normalize_category, normalize_color
from paths import normalize_stored_path, resolve_image_path

logger = logging.getLogger("findyu.migrations")

# (컬럼명, SQLite 타입) — models.Item과 일치해야 함
# v1에서 추가한 컬럼 (이미 배포된 단계이므로 이 목록은 바꾸지 말 것)
NEW_COLUMNS = [
    ("device_model", "VARCHAR"),
    ("device_model_candidates", "TEXT"),
    ("identification_level", "VARCHAR"),
    ("has_case", "BOOLEAN"),
    ("wallet_type", "VARCHAR"),
    ("material", "VARCHAR"),
    ("verification_needed", "TEXT"),
]


# v4에서 추가한 컬럼: 제조사, 항목별 AI 확신도
V4_COLUMNS = [
    ("manufacturer", "VARCHAR"),
    ("category_confidence", "FLOAT"),
    ("manufacturer_confidence", "FLOAT"),
    ("device_model_confidence", "FLOAT"),
    ("color_confidence", "FLOAT"),
]


def _add_columns(conn, columns):
    existing = _columns(conn, "items")
    for name, sql_type in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE items ADD COLUMN {name} {sql_type}")
            logger.info("컬럼 추가: items.%s", name)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _m1_add_phone_wallet_columns(conn: sqlite3.Connection):
    _add_columns(conn, NEW_COLUMNS)


def _m2_normalize_image_paths(conn: sqlite3.Connection):
    rows = conn.execute(
        "SELECT id, image_path FROM items WHERE image_path IS NOT NULL"
    ).fetchall()
    changed = 0
    for item_id, image_path in rows:
        normalized = normalize_stored_path(image_path)
        if normalized != image_path:
            conn.execute(
                "UPDATE items SET image_path = ? WHERE id = ?", (normalized, item_id)
            )
            changed += 1
    logger.info("image_path 정규화: %d건", changed)


def _m3_normalize_labels(conn: sqlite3.Connection):
    """품명은 스마트폰/지갑/기타, 색상은 labels.COLORS로 통일. 원래 값은 백업 파일에 남는다."""
    rows = conn.execute("SELECT id, category, color FROM items").fetchall()
    for item_id, category, color in rows:
        new_category = normalize_category(category)
        new_color = normalize_color(color)
        if (new_category, new_color) != (category, color):
            conn.execute(
                "UPDATE items SET category = ?, color = ? WHERE id = ?",
                (new_category, new_color, item_id),
            )
            logger.warning(
                "라벨 정규화 #%s: 품명 %r→%r, 색상 %r→%r",
                item_id, category, new_category, color, new_color,
            )


def _m4_add_confidence_columns(conn: sqlite3.Connection):
    _add_columns(conn, V4_COLUMNS)


def _m5_create_item_images(conn: sqlite3.Connection):
    """여러 장 사진 테이블 생성 + 기존 물품의 대표 사진(image_path)을 position 0으로 채운다."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS item_images (
            id INTEGER NOT NULL PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
            image_path VARCHAR NOT NULL,
            position INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_item_images_id ON item_images (id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_item_images_item_id ON item_images (item_id)")
    cursor = conn.execute(
        """
        INSERT INTO item_images (item_id, image_path, position)
        SELECT id, image_path, 0 FROM items
        WHERE image_path IS NOT NULL
          AND id NOT IN (SELECT item_id FROM item_images)
        """
    )
    logger.warning("item_images 대표 사진 채움: %d건", cursor.rowcount)


EXIF_ORIENTATION_TAG = 0x0112


def _m6_clear_rotated_embeddings(conn: sqlite3.Connection):
    """
    EXIF 회전 정보가 있는 사진의 검색 임베딩은 회전을 반영하지 않고 계산된 값이므로 비운다.
    서버 시작 시 main.backfill_missing_embeddings()가 회전을 반영해 다시 계산한다.
    """
    from PIL import Image

    rows = conn.execute(
        "SELECT id, image_path FROM items WHERE embedding IS NOT NULL AND image_path IS NOT NULL"
    ).fetchall()
    cleared = []
    for item_id, image_path in rows:
        image_file = resolve_image_path(image_path)
        if image_file is None:
            continue
        try:
            with Image.open(image_file) as image:
                orientation = image.getexif().get(EXIF_ORIENTATION_TAG)
        except Exception:
            continue
        if orientation not in (None, 1):
            conn.execute("UPDATE items SET embedding = NULL WHERE id = ?", (item_id,))
            cleared.append(item_id)
    logger.warning("EXIF 회전 사진 임베딩 초기화(재계산 예정): %s", cleared or "없음")


# v7에서 추가한 컬럼: 체크 폼 항목, 항목별 출처, 분석 모델
V7_COLUMNS = [
    ("has_card_wallet", "BOOLEAN"),
    ("earphone_components", "VARCHAR"),
    ("wallet_closure", "VARCHAR"),
    ("field_sources", "TEXT"),
    ("analysis_model", "VARCHAR"),
]


def _m7_check_form_columns(conn: sqlite3.Connection):
    """체크 폼 컬럼 추가 + 품명 '이어폰' 신설에 따라 기존 '기타' 중 이어폰을 재분류."""
    _add_columns(conn, V7_COLUMNS)
    moved = []
    rows = conn.execute(
        "SELECT id, description, brand FROM items WHERE category = ?", (CATEGORY_OTHER,)
    ).fetchall()
    for item_id, description, brand in rows:
        if is_earphone_text(description) or is_earphone_text(brand):
            conn.execute(
                "UPDATE items SET category = ? WHERE id = ?", (CATEGORY_EARPHONE, item_id)
            )
            moved.append(item_id)
    logger.warning("기타 → 이어폰 재분류: %s", moved or "없음")


MIGRATIONS = [
    (1, _m1_add_phone_wallet_columns),
    (2, _m2_normalize_image_paths),
    (3, _m3_normalize_labels),
    (4, _m4_add_confidence_columns),
    (5, _m5_create_item_images),
    (6, _m6_clear_rotated_embeddings),
    (7, _m7_check_form_columns),
]
LATEST_VERSION = MIGRATIONS[-1][0]


def get_version(db_path: Path | str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _has_rows(conn: sqlite3.Connection) -> bool:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='items'"
    ).fetchone():
        return False
    return conn.execute("SELECT 1 FROM items LIMIT 1").fetchone() is not None


def backup_database(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.bak-{stamp}")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)  # 파일 복사 대신 SQLite backup API (사용 중이어도 일관된 스냅샷)
    finally:
        dst.close()
        src.close()
    return backup_path


def run_migrations(db_path: Path | str) -> list[int]:
    """미적용 마이그레이션을 실행하고, 실행한 버전 번호 목록을 반환한다."""
    db_path = Path(db_path)
    # isolation_level=None: 드라이버의 암묵적 트랜잭션을 끄고 BEGIN/COMMIT을 직접 제어
    conn = sqlite3.connect(db_path, isolation_level=None)
    applied = []
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        pending = [(v, fn) for v, fn in MIGRATIONS if v > version]
        if not pending:
            return applied

        if _has_rows(conn):
            backup_path = backup_database(db_path)
            logger.warning("DB 마이그레이션 전 백업 생성: %s", backup_path)

        for target, fn in pending:
            conn.execute("BEGIN IMMEDIATE")
            try:
                fn(conn)
                conn.execute(f"PRAGMA user_version = {int(target)}")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                logger.exception("DB 마이그레이션 v%d 실패 - 롤백함", target)
                raise
            applied.append(target)
            logger.warning("DB 마이그레이션 v%d 적용 (%s)", target, fn.__name__)
    finally:
        conn.close()
    return applied
