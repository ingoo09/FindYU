"""
DB 연결 설정.
지금은 SQLite(파일 하나짜리 DB, findyu.db)를 씀.
나중에 진짜 서버에 배포할 때는 이 부분만 PostgreSQL 등으로 교체하면 됨.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from paths import BASE_DIR

# 실행 위치(CWD)와 무관하게 항상 backend/findyu.db를 사용
DB_PATH = BASE_DIR / "findyu.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}  # SQLite 전용 옵션
)


def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """
    SQLite는 연결마다 외래키 검사가 꺼져 있으므로 연결할 때마다 켠다.
    → 물품(items)을 지우면 item_images가 ON DELETE CASCADE로 함께 지워진다.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


event.listen(engine, "connect", enable_sqlite_foreign_keys)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI 엔드포인트에서 DB 세션을 빌려 쓰고 자동으로 반납하는 함수"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
