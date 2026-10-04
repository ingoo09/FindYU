"""
FindYU 백엔드 - 중간발표용 통합 데모
실행: uvicorn main:app --reload
브라우저에서 http://localhost:8000/docs 열면 API 테스트 가능

NOTE:
- 이미지 임베딩은 Hugging Face의 facebook/dinov2-small 모델을 실제로 호출함.
- 자연어/위치/시간 점수는 중간발표용 규칙 기반 로직이며 이후 멀티모달 모델로 교체 가능함.
"""

from datetime import datetime
from difflib import SequenceMatcher
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from PIL import Image
from transformers import AutoImageProcessor, AutoModel
import torch
import torch.nn.functional as F
import io
import json
import os
import re
import threading
import uuid

from database import engine, Base, get_db
import models

app = FastAPI(title="FindYU Backend - Midterm Demo")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------
# 실제 DINOv2 이미지 임베딩
# ---------------------------------------------------------
MODEL_NAME = os.getenv("FINDYU_IMAGE_MODEL", "facebook/dinov2-small")
_image_processor = None
_image_model = None
_model_lock = threading.Lock()


def _load_image_model():
    """
    DINOv2 processor/model을 최초 호출 시 한 번만 로드한다.
    첫 실행에서는 Hugging Face에서 모델 가중치를 내려받을 수 있다.
    """
    global _image_processor, _image_model

    if _image_processor is None or _image_model is None:
        with _model_lock:
            if _image_processor is None or _image_model is None:
                _image_processor = AutoImageProcessor.from_pretrained(MODEL_NAME)
                _image_model = AutoModel.from_pretrained(MODEL_NAME)
                _image_model.eval()

    return _image_processor, _image_model


def get_embedding(image: Image.Image):
    """
    PIL 이미지를 DINOv2 CLS embedding으로 변환한다.
    반환 벡터는 L2 normalize하여 cosine similarity에 바로 사용할 수 있다.
    """
    processor, model = _load_image_model()
    inputs = processor(images=image.convert("RGB"), return_tensors="pt")

    with torch.inference_mode():
        outputs = model(**inputs)
        vector = outputs.last_hidden_state[:, 0, :]
        vector = F.normalize(vector, p=2, dim=1)

    return vector.squeeze(0).cpu().tolist()


def cosine_similarity(vec1, vec2):
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5

    if norm1 == 0 or norm2 == 0:
        return 0.0

    raw_cosine = dot / (norm1 * norm2)
    return max(0.0, min(1.0, (raw_cosine + 1.0) / 2.0))


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(re.findall(r"[0-9A-Za-z가-힣]+", value.lower()))


def text_similarity(query: str | None, candidate: str | None) -> float | None:
    query_norm = normalize_text(query)
    candidate_norm = normalize_text(candidate)

    if not query_norm:
        return None
    if not candidate_norm:
        return 0.0

    query_tokens = set(query_norm.split())
    candidate_tokens = set(candidate_norm.split())
    union = query_tokens | candidate_tokens
    jaccard = len(query_tokens & candidate_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, query_norm, candidate_norm).ratio()

    return max(jaccard, sequence * 0.75)


def location_similarity(query: str | None, candidate: str | None) -> float | None:
    query_norm = normalize_text(query)
    candidate_norm = normalize_text(candidate)

    if not query_norm:
        return None
    if not candidate_norm:
        return 0.0

    if query_norm == candidate_norm:
        return 1.0

    return SequenceMatcher(None, query_norm, candidate_norm).ratio()


def parse_optional_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def time_similarity(query_time: datetime | None, candidate_time: datetime | None):
    if query_time is None:
        return None
    if candidate_time is None:
        return 0.0

    hours = abs((query_time - candidate_time).total_seconds()) / 3600

    if hours <= 6:
        return 1.0
    if hours <= 24:
        return 0.9
    if hours <= 72:
        return 0.7
    if hours <= 168:
        return 0.4
    return 0.2


def public_image_url(path: str | None):
    if not path:
        return None
    normalized = path.replace("\\", "/")
    filename = os.path.basename(normalized)
    return f"/uploads/{filename}"


def save_uploaded_image(file_bytes: bytes, original_filename: str) -> str:
    ext = os.path.splitext(original_filename or "")[1].lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"

    unique_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(save_path, "wb") as file:
        file.write(file_bytes)

    return save_path


def item_embedding(item):
    """
    현재 DINOv2 차원과 일치하는 저장 임베딩은 그대로 사용한다.
    과거 mock/fallback 임베딩은 이미지 파일에서 DINOv2로 다시 계산한다.
    """
    _, model = _load_image_model()
    expected_size = int(model.config.hidden_size)

    try:
        stored = json.loads(item.embedding) if item.embedding else None
        if stored and len(stored) == expected_size:
            return [float(value) for value in stored]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    if item.image_path and os.path.exists(item.image_path):
        with Image.open(item.image_path) as image:
            return get_embedding(image)

    return []


def serialize_item(item):
    return {
        "id": item.id,
        "item_type": item.item_type,
        "category": item.category,
        "color": item.color,
        "brand": item.brand,
        "description": item.description,
        "location": item.location,
        "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "image_path": item.image_path,
        "image_url": public_image_url(item.image_path),
    }


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "message": "FindYU backend is running",
        "image_embedding_model": MODEL_NAME,
    }


@app.post("/compare")
async def compare_images(
    image1: UploadFile = File(...),
    image2: UploadFile = File(...),
):
    img1_bytes = await image1.read()
    img2_bytes = await image2.read()

    img1 = Image.open(io.BytesIO(img1_bytes)).convert("RGB")
    img2 = Image.open(io.BytesIO(img2_bytes)).convert("RGB")

    emb1 = get_embedding(img1)
    emb2 = get_embedding(img2)
    similarity = cosine_similarity(emb1, emb2)

    return {
        "similarity": round(similarity, 4),
        "is_same_item": similarity >= 0.8,
        "scoring_mode": "dinov2+metadata",
    }


@app.post("/items")
async def register_item(
    item_type: str = Form(...),
    category: str = Form(None),
    color: str = Form(None),
    brand: str = Form(None),
    description: str = Form(None),
    location: str = Form(None),
    occurred_at: str = Form(None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if item_type not in {"found", "lost"}:
        raise HTTPException(status_code=400, detail="item_type must be 'found' or 'lost'")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="image is required")

    saved_path = save_uploaded_image(image_bytes, image.filename)

    try:
        pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        if os.path.exists(saved_path):
            os.remove(saved_path)
        raise HTTPException(status_code=400, detail="invalid image file") from exc

    embedding_vector = get_embedding(pil_image)

    new_item = models.Item(
        item_type=item_type,
        category=category,
        color=color,
        brand=brand,
        description=description,
        image_path=saved_path,
        embedding=json.dumps(embedding_vector),
        location=location,
        occurred_at=parse_optional_datetime(occurred_at),
    )

    db.add(new_item)
    db.commit()
    db.refresh(new_item)

    return serialize_item(new_item)


@app.get("/items")
def list_items(db: Session = Depends(get_db)):
    items = db.query(models.Item).order_by(models.Item.created_at.desc()).all()
    return [serialize_item(item) for item in items]


@app.get("/items/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return serialize_item(item)


@app.post("/search")
async def search_items(
    description: str = Form(None),
    location: str = Form(None),
    occurred_at: str = Form(None),
    image: UploadFile = File(None),
    top_k: int = Form(5),
    db: Session = Depends(get_db),
):
    if top_k < 1:
        top_k = 1
    if top_k > 20:
        top_k = 20

    query_image_embedding = None
    if image is not None and image.filename:
        image_bytes = await image.read()
        if image_bytes:
            try:
                query_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                query_image_embedding = get_embedding(query_image)
            except Exception as exc:
                raise HTTPException(status_code=400, detail="invalid search image") from exc

    query_time = parse_optional_datetime(occurred_at)

    candidates = (
        db.query(models.Item)
        .filter(models.Item.item_type == "found")
        .all()
    )

    results = []

    for candidate in candidates:
        image_score = None
        if query_image_embedding is not None:
            candidate_embedding = item_embedding(candidate)
            image_score = cosine_similarity(query_image_embedding, candidate_embedding)

        candidate_text = " ".join(
            value
            for value in [
                candidate.category,
                candidate.color,
                candidate.brand,
                candidate.description,
            ]
            if value
        )
        text_score = text_similarity(description, candidate_text)
        location_score = location_similarity(location, candidate.location)
        time_score = time_similarity(query_time, candidate.occurred_at)

        weighted_components = []
        if image_score is not None:
            weighted_components.append((0.45, image_score))
        if text_score is not None:
            weighted_components.append((0.30, text_score))
        if location_score is not None:
            weighted_components.append((0.15, location_score))
        if time_score is not None:
            weighted_components.append((0.10, time_score))

        if weighted_components:
            total_weight = sum(weight for weight, _ in weighted_components)
            matching_score = sum(
                weight * score for weight, score in weighted_components
            ) / total_weight
        else:
            matching_score = 0.0

        results.append(
            {
                **serialize_item(candidate),
                "image_similarity": round(image_score, 4) if image_score is not None else None,
                "text_similarity": round(text_score, 4) if text_score is not None else None,
                "location_score": round(location_score, 4) if location_score is not None else None,
                "time_score": round(time_score, 4) if time_score is not None else None,
                "matching_score": round(matching_score, 4),
                "similarity": round(matching_score, 4),
                "scoring_mode": "dinov2+metadata",
            }
        )

    results.sort(key=lambda item: item["matching_score"], reverse=True)

    return {
        "query_description": description,
        "query_location": location,
        "query_occurred_at": occurred_at,
        "scoring_mode": "dinov2+metadata",
        "total_candidates": len(candidates),
        "results": results[:top_k],
    }
