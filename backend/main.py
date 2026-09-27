"""
FindYU 백엔드 - 1주차 스프린트용 최소 서버
실행: uvicorn main:app --reload
브라우저에서 http://localhost:8000/docs 열면 자동으로 API 테스트 화면이 뜸
"""

from fastapi import FastAPI, UploadFile, File, Form, Depends
from sqlalchemy.orm import Session
from PIL import Image
import io
import os
import uuid
import json

from database import engine, Base, get_db
import models

app = FastAPI(title="FindYU Backend - Sprint 1")

# 업로드된 이미지를 저장할 폴더 (없으면 자동 생성)
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 서버 시작 시 DB 테이블이 없으면 자동으로 생성
Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------
# TODO: 최준서(AI팀원)가 완성하면 이 함수를 실제 구현으로 교체
# 지금은 자리만 잡아둔 가짜(mock) 함수
# ---------------------------------------------------------
def get_embedding(image: Image.Image):
    """
    이미지를 받아서 임베딩 벡터(리스트)를 반환하는 함수.
    최준서가 CLIP으로 완성하면 이 함수 내용만 교체하면 됨.
    지금은 테스트용으로 아무 값이나 반환.
    """
    return [0.0] * 512  # CLIP 기본 차원(예시). 실제 값은 AI팀원 함수로 교체


def cosine_similarity(vec1, vec2):
    """두 벡터 간 코사인 유사도 계산 (0~1 사이 값, 1에 가까울수록 유사)"""
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


@app.get("/")
def health_check():
    """서버가 살아있는지 확인용"""
    return {"status": "ok", "message": "FindYU backend is running"}


@app.post("/compare")
async def compare_images(image1: UploadFile = File(...), image2: UploadFile = File(...)):
    """
    사진 2장을 받아서 유사도 점수를 반환하는 핵심 엔드포인트.
    프론트엔드(김승보)는 이 엔드포인트에 사진 2장을 multipart/form-data로 보내면 됨.
    """
    img1_bytes = await image1.read()
    img2_bytes = await image2.read()

    img1 = Image.open(io.BytesIO(img1_bytes)).convert("RGB")
    img2 = Image.open(io.BytesIO(img2_bytes)).convert("RGB")

    emb1 = get_embedding(img1)
    emb2 = get_embedding(img2)

    similarity = cosine_similarity(emb1, emb2)

    return {
        "similarity": round(similarity, 4),
        "is_same_item": similarity >= 0.8,  # 임계값은 나중에 테스트하면서 조정
    }


def save_uploaded_image(file_bytes: bytes, original_filename: str) -> str:
    """
    업로드된 이미지를 uploads/ 폴더에 고유한 이름으로 저장하고,
    저장된 경로를 반환하는 함수.
    """
    ext = os.path.splitext(original_filename)[1] or ".jpg"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(save_path, "wb") as f:
        f.write(file_bytes)

    return save_path


@app.post("/items")
async def register_item(
    item_type: str = Form(...),          # "found" 또는 "lost"
    category: str = Form(None),
    color: str = Form(None),
    brand: str = Form(None),
    description: str = Form(None),
    location: str = Form(None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    습득물/분실물 등록 엔드포인트.
    사진 + 메타데이터를 받아서 저장하고, 등록된 항목의 id를 돌려줌.
    지금은 임베딩을 가짜값으로 채움 - 최준서 함수 완성되면 실제 값으로 교체.
    """
    image_bytes = await image.read()
    saved_path = save_uploaded_image(image_bytes, image.filename)

    pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    embedding_vector = get_embedding(pil_image)  # 지금은 mock 함수

    new_item = models.Item(
        item_type=item_type,
        category=category,
        color=color,
        brand=brand,
        description=description,
        image_path=saved_path,
        embedding=json.dumps(embedding_vector),  # 벡터를 JSON 문자열로 저장
        location=location,
    )

    db.add(new_item)
    db.commit()
    db.refresh(new_item)

    return {
        "id": new_item.id,
        "item_type": new_item.item_type,
        "category": new_item.category,
        "color": new_item.color,
        "image_path": new_item.image_path,
        "status": new_item.status,
    }


@app.get("/items")
def list_items(db: Session = Depends(get_db)):
    """등록된 전체 항목을 확인하기 위한 테스트용 엔드포인트"""
    items = db.query(models.Item).all()
    return [
        {
            "id": i.id,
            "item_type": i.item_type,
            "category": i.category,
            "color": i.color,
            "image_path": i.image_path,
            "status": i.status,
        }
        for i in items
    ]


@app.post("/search")
async def search_items(
    description: str = Form(None),
    image: UploadFile = File(None),
    top_k: int = Form(5),
    db: Session = Depends(get_db),
):
    """
    분실물 검색 엔드포인트 (지금은 가짜 버전).
    실제로는 업로드된 사진의 임베딩과 DB에 있는 습득물(item_type="found") 임베딩을
    비교해서 유사도 높은 순으로 반환해야 하는데,
    아직 실제 임베딩이 의미없는 값이라 지금은 "등록된 습득물 중 최근 top_k개"를
    그냥 후보로 돌려주는 자리만 잡은 버전입니다.
    프론트엔드는 이 엔드포인트로 먼저 화면 연동을 진행하면 됩니다.
    """
    candidates = (
        db.query(models.Item)
        .filter(models.Item.item_type == "found")
        .order_by(models.Item.created_at.desc())
        .limit(top_k)
        .all()
    )

    results = [
        {
            "id": c.id,
            "category": c.category,
            "color": c.color,
            "image_path": c.image_path,
            "location": c.location,
            "similarity": 0.0,  # TODO: 최준서 함수 연결되면 실제 유사도로 교체
        }
        for c in candidates
    ]

    return {"query_description": description, "results": results}
