"""
DB 연결 설정.
지금은 SQLite(파일 하나짜리 DB, findyu.db)를 씀.
나중에 진짜 서버에 배포할 때는 이 부분만 PostgreSQL 등으로 교체하면 됨.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from paths import BASE_DIR

# 실행 위치(CWD)와 무관하게 항상 backend/findyu.db를 사용
DB_PATH = BASE_DIR / "findyu.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}  # SQLite 전용 옵션
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI 엔드포인트에서 DB 세션을 빌려 쓰고 자동으로 반납하는 함수"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
