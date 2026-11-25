"""
사진 검색 임베딩 수동 백필: 임베딩이 비어 있는 습득물(found)의 대표 사진 임베딩을 채운다.

서버 시작 때 자동으로 돌지 않는다. 필요할 때 직접 실행한다 (backend/에서):

    .venv/bin/python tools/backfill_gemini_embeddings.py            # 대상·호출 수를 보여주고 확인받은 뒤 실행
    .venv/bin/python tools/backfill_gemini_embeddings.py --dry-run  # 대상·호출 수만 보기

- 대상: item_type=found, status != analysis_failed, 사진 임베딩이 없거나 지금 모델과 다른 모델로 만든 것
  (수동 등록 중 임베딩 실패, v8 이전 물품 등)
- 모델은 서버와 같은 설정을 쓴다 (FINDYU_SEARCH_ANALYZER_MODE, FINDYU_EMBEDDING_MODEL, FINDYU_EMBEDDING_DIMENSIONS)
  - baze: 게이트웨이 호출 (사진 --batch장씩 한 번에)
  - mock: API 호출 없음
  - local: 필요 없음 (DINOv2는 서버가 처리)
- 실패한 묶음은 재시도하지 않고 비워 둔다. API 키는 출력하지 않는다.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageOps

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")  # 서버(main.py)와 같은 설정. 셸 환경변수가 우선

import os  # noqa: E402

import gemini_embedding  # noqa: E402
import models  # noqa: E402
from database import DB_PATH, Base, SessionLocal, engine  # noqa: E402
from migrations import run_migrations  # noqa: E402
from paths import resolve_image_path  # noqa: E402

MAX_BATCH = 10


def open_image(path) -> Image.Image:
    # main.open_image와 같은 처리 (EXIF 회전 반영). main을 import하면 검색 모델 코드까지 불러오므로 따로 둔다
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def find_targets(db, model_id: str):
    items = (
        db.query(models.Item)
        .filter(models.Item.item_type == "found")
        .filter(models.Item.status != "analysis_failed")
        .order_by(models.Item.id)
        .all()
    )
    return [
        item for item in items
        if not item.image_embedding_gemini or item.image_embedding_model != model_id
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="대상과 호출 수만 보여주고 끝낸다")
    parser.add_argument("--batch", type=int, default=5, help=f"한 번에 보낼 사진 수 (1~{MAX_BATCH}, 기본 5)")
    args = parser.parse_args(argv)
    if not 1 <= args.batch <= MAX_BATCH:
        parser.error(f"--batch는 1~{MAX_BATCH} 사이여야 합니다.")

    mode = os.getenv("FINDYU_SEARCH_ANALYZER_MODE", "baze").strip().lower()
    embedder = gemini_embedding.make_embedder(mode)
    if embedder is None:
        print(f"FINDYU_SEARCH_ANALYZER_MODE={mode}: 사진 임베딩 백필이 필요 없습니다 (baze 또는 mock에서 사용).")
        return 0

    Base.metadata.create_all(bind=engine)
    run_migrations(DB_PATH)

    db = SessionLocal()
    try:
        targets = find_targets(db, embedder.model_id)
        readable, missing = [], []
        for item in targets:
            path = resolve_image_path(item.image_path)
            (readable if path is not None else missing).append((item, path))

        calls = math.ceil(len(readable) / args.batch) if readable else 0
        api_calls = calls if mode == "baze" else 0
        print(f"DB: {DB_PATH}")
        print(f"모드: {mode}  모델: {embedder.model_id}")
        print(f"대상 습득물: {len(targets)}건 (대표 사진 있음 {len(readable)}건, 없음 {len(missing)}건)")
        if missing:
            print(f"  사진이 없어 건너뜀: {[item.id for item, _ in missing]}")
        print(f"게이트웨이 호출 예정: {api_calls}회 (사진 {args.batch}장씩)")

        if not readable:
            print("채울 물품이 없습니다.")
            return 0
        if args.dry_run:
            print("--dry-run: 실행하지 않았습니다.")
            return 0
        answer = input("진행할까요? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("취소했습니다.")
            return 0

        done, failed = 0, []
        started = time.perf_counter()
        for start in range(0, len(readable), args.batch):
            batch = readable[start:start + args.batch]
            ids = [item.id for item, _ in batch]
            t0 = time.perf_counter()
            try:
                vectors = embedder.embed_images([open_image(path) for _, path in batch])
            except Exception as exc:
                db.rollback()
                failed.extend(ids)
                print(f"  실패 {ids}: {exc}")
                continue
            for (item, _), vector in zip(batch, vectors):
                item.image_embedding_gemini = json.dumps(vector)
                item.image_embedding_model = embedder.model_id
            db.commit()
            done += len(batch)
            print(f"  완료 {ids} ({time.perf_counter() - t0:.2f}s)")

        print(f"결과: 채움 {done}건, 실패 {len(failed)}건{f' {failed}' if failed else ''}, "
              f"총 {time.perf_counter() - started:.1f}s")
        return 0 if not failed else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
