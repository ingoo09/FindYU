"""
파일 경로 유틸.

- 서버를 어느 폴더에서 실행하든(backend/ 또는 저장소 루트) 같은 DB·업로드 폴더를 쓰도록
  backend/ 폴더 기준 절대경로를 사용한다.
- DB의 image_path는 OS와 무관하게 "uploads/<파일명>" (POSIX 상대경로)로 저장한다.
- 과거 Windows에서 저장된 "uploads\\파일명.jpg" 같은 값도 resolve_image_path로 읽을 수 있다.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR_NAME = "uploads"
# 테스트에서 임시 폴더를 쓰도록 바꿀 수 있다 (DB에는 여전히 "uploads/<파일명>"으로 저장)
UPLOAD_DIR = Path(os.getenv("FINDYU_UPLOAD_DIR") or BASE_DIR / UPLOAD_DIR_NAME)


def image_filename(stored_path: str | None) -> str | None:
    """DB에 저장된 경로에서 파일명만 꺼낸다. 역슬래시/슬래시/절대경로 모두 허용."""
    if not stored_path:
        return None
    name = stored_path.replace("\\", "/").rstrip("/").split("/")[-1]
    return name or None


def to_stored_path(filename: str) -> str:
    """DB에 저장할 이미지 경로 형식: uploads/<파일명>"""
    return f"{UPLOAD_DIR_NAME}/{filename}"


def normalize_stored_path(stored_path: str | None) -> str | None:
    """기존 DB 값을 저장 형식으로 정규화 (마이그레이션용)."""
    name = image_filename(stored_path)
    return to_stored_path(name) if name else stored_path


def resolve_image_path(stored_path: str | None) -> Path | None:
    """DB에 저장된 image_path를 실제 파일 경로로 바꾼다. 파일이 없으면 None."""
    name = image_filename(stored_path)
    if not name:
        return None
    path = UPLOAD_DIR / name
    return path if path.is_file() else None
