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
from transformers import AutoImageProcessor, AutoModel, AutoProcessor

try:
    # Transformers 5.x / current SmolVLM API
    from transformers import AutoModelForImageTextToText as AutoVLMModel
except ImportError:
    # Compatibility with older Transformers releases
    from transformers import AutoModelForVision2Seq as AutoVLMModel
import torch
import torch.nn.functional as F
import io
import json
import logging
import os
import queue
import re
import threading
import uuid

from database import engine, Base, get_db, SessionLocal
import models

logger = logging.getLogger("findyu")

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

VLM_MODEL_NAME = os.getenv("FINDYU_VLM_MODEL", "HuggingFaceTB/SmolVLM-500M-Instruct")
_vlm_processor = None
_vlm_model = None
_vlm_lock = threading.Lock()


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



def _load_vlm_model():
    """
    습득물 사진에서 등록 정보를 자동 추출하기 위한 소형 Vision-Language 모델.
    최초 분석 시 Hugging Face에서 모델 가중치를 내려받는다.
    """
    global _vlm_processor, _vlm_model

    if _vlm_processor is None or _vlm_model is None:
        with _vlm_lock:
            if _vlm_processor is None or _vlm_model is None:
                device = "cuda" if torch.cuda.is_available() else "cpu"
                dtype = torch.bfloat16 if device == "cuda" else torch.float32

                _vlm_processor = AutoProcessor.from_pretrained(VLM_MODEL_NAME)
                _vlm_model = AutoVLMModel.from_pretrained(
                    VLM_MODEL_NAME,
                    torch_dtype=dtype,
                    _attn_implementation="eager",
                ).to(device)
                _vlm_model.eval()

    return _vlm_processor, _vlm_model


# ---------------------------------------------------------
# 등록용 VLM 출력 정규화
# - 작은 VLM이 장문/반복 문장을 만들지 않도록 CODE 선택 방식 사용
# - category/color/brand는 최종적으로 한국어 단일 명사로 정규화
# ---------------------------------------------------------
CATEGORY_LABELS = {
    "PHONE": "스마트폰",
    "SMARTWATCH": "스마트워치",
    "WATCH": "시계",
    "EARBUDS": "이어폰",
    "EARBUD_CASE": "이어폰케이스",
    "WALLET": "지갑",
    "CARD": "카드",
    "KEY": "열쇠",
    "UMBRELLA": "우산",
    "BAG": "가방",
    "BACKPACK": "백팩",
    "LAPTOP": "노트북",
    "TABLET": "태블릿",
    "CHARGER": "충전기",
    "CABLE": "케이블",
    "BOTTLE": "물병",
    "TUMBLER": "텀블러",
    "GLASSES": "안경",
    "MOUSE": "마우스",
    "KEYBOARD": "키보드",
    "BOOK": "책",
    "PEN": "필기구",
    "OTHER": "기타",
}

COLOR_LABELS = {
    "BLACK": "검정",
    "WHITE": "흰색",
    "GRAY": "회색",
    "SILVER": "은색",
    "RED": "빨강",
    "ORANGE": "주황",
    "YELLOW": "노랑",
    "GREEN": "초록",
    "BLUE": "파랑",
    "NAVY": "남색",
    "PURPLE": "보라",
    "PINK": "분홍",
    "BROWN": "갈색",
    "BEIGE": "베이지",
    "GOLD": "금색",
    "MULTI": "다색",
    "UNKNOWN": "미확인",
}

FEATURE_LABELS = {
    "SQUARE": "사각형",
    "RECTANGULAR": "직사각형",
    "ROUND": "원형",
    "OVAL": "타원형",
    "STRAP": "밴드부착",
    "SCREEN": "화면있음",
    "CASE": "케이스형",
    "SCRATCH": "흠집있음",
    "STICKER": "스티커있음",
    "PATTERN": "무늬있음",
    "METAL": "금속재질",
    "PLASTIC": "플라스틱재질",
    "FABRIC": "천재질",
    "LEATHER": "가죽재질",
    "TRANSPARENT": "투명부분",
    "BUTTON": "버튼있음",
    "CABLE": "케이블부착",
    "HANDLE": "손잡이있음",
    "ZIPPER": "지퍼있음",
    "RING": "고리있음",
    "COVER": "커버있음",
    "KEYCHAIN": "키링있음",
}

BRAND_ALIASES = [
    (("apple", "iphone", "airpods", "macbook"), "애플"),
    (("samsung", "galaxy", "buds"), "삼성"),
    (("lg", "gram"), "엘지"),
    (("sony",), "소니"),
    (("bose",), "보스"),
    (("jbl",), "제이비엘"),
    (("xiaomi", "mi "), "샤오미"),
    (("huawei",), "화웨이"),
    (("lenovo",), "레노버"),
    (("logitech",), "로지텍"),
    (("microsoft", "surface"), "마이크로소프트"),
    (("nike",), "나이키"),
    (("adidas",), "아디다스"),
    (("new balance", "newbalance"), "뉴발란스"),
    (("puma",), "푸마"),
    (("starbucks",), "스타벅스"),
    (("anker",), "앤커"),
    (("belkin",), "벨킨"),
    (("casio",), "카시오"),
    (("seiko",), "세이코"),
]


def _normalize_raw_answer(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"^```(?:\\w+)?\\s*", "", value)
    value = re.sub(r"\\s*```$", "", value)
    return value.strip()


def _pick_code(text: str, labels: dict[str, str], keyword_fallback: dict[str, str] | None = None):
    raw = _normalize_raw_answer(text)
    upper = raw.upper()

    # 긴 code가 짧은 code를 포함할 수 있으므로 길이순 검사
    for code in sorted(labels, key=len, reverse=True):
        if re.search(rf"(?<![A-Z0-9_]){re.escape(code)}(?![A-Z0-9_])", upper):
            return labels[code]

    if keyword_fallback:
        lowered = raw.lower()
        for keyword, code in keyword_fallback.items():
            if keyword in lowered and code in labels:
                return labels[code]

    return None


def _normalize_category(text: str) -> str:
    keyword_fallback = {
        "smart watch": "SMARTWATCH",
        "smartwatch": "SMARTWATCH",
        "watch": "WATCH",
        "phone": "PHONE",
        "iphone": "PHONE",
        "smartphone": "PHONE",
        "earbud case": "EARBUD_CASE",
        "earbuds case": "EARBUD_CASE",
        "earbud": "EARBUDS",
        "earbuds": "EARBUDS",
        "wallet": "WALLET",
        "card": "CARD",
        "key": "KEY",
        "umbrella": "UMBRELLA",
        "backpack": "BACKPACK",
        "bag": "BAG",
        "laptop": "LAPTOP",
        "tablet": "TABLET",
        "charger": "CHARGER",
        "cable": "CABLE",
        "bottle": "BOTTLE",
        "tumbler": "TUMBLER",
        "glasses": "GLASSES",
        "mouse": "MOUSE",
        "keyboard": "KEYBOARD",
        "book": "BOOK",
        "pen": "PEN",
    }
    return _pick_code(text, CATEGORY_LABELS, keyword_fallback) or "기타"


def _normalize_color(text: str) -> str:
    keyword_fallback = {
        "black": "BLACK",
        "white": "WHITE",
        "gray": "GRAY",
        "grey": "GRAY",
        "silver": "SILVER",
        "red": "RED",
        "orange": "ORANGE",
        "yellow": "YELLOW",
        "green": "GREEN",
        "blue": "BLUE",
        "navy": "NAVY",
        "purple": "PURPLE",
        "pink": "PINK",
        "brown": "BROWN",
        "beige": "BEIGE",
        "gold": "GOLD",
        "multicolor": "MULTI",
        "multi-color": "MULTI",
    }
    return _pick_code(text, COLOR_LABELS, keyword_fallback) or "미확인"


def _normalize_brand(text: str) -> str:
    raw = _normalize_raw_answer(text)
    lowered = raw.lower().strip(" .,:;")

    if lowered in {
        "", "none", "unknown", "n/a", "not visible", "not sure", "unclear",
        "no brand", "no logo",
    }:
        return "미확인"

    for aliases, korean in BRAND_ALIASES:
        if any(alias in lowered for alias in aliases):
            return korean

    # 한글 한 단어가 직접 나온 경우에만 허용
    korean_words = re.findall(r"[가-힣]+", raw)
    if korean_words:
        return korean_words[0]

    # 알 수 없는 영문 브랜드를 그대로 노출하지 않고 한글 명사로 통일
    return "미확인"


def _normalize_features(text: str) -> str:
    raw = _normalize_raw_answer(text)
    upper = raw.upper()

    found = []
    for code, label in FEATURE_LABELS.items():
        if re.search(rf"(?<![A-Z0-9_]){re.escape(code)}(?![A-Z0-9_])", upper):
            if label not in found:
                found.append(label)

    # code를 무시하고 장문을 출력했을 때 최소 fallback
    keyword_fallback = [
        (("square",), "사각형"),
        (("rectangular", "rectangle"), "직사각형"),
        (("round", "circular"), "원형"),
        (("oval",), "타원형"),
        (("strap", "band"), "밴드부착"),
        (("screen", "display"), "화면있음"),
        (("case",), "케이스형"),
        (("scratch",), "흠집있음"),
        (("sticker",), "스티커있음"),
        (("pattern",), "무늬있음"),
        (("metal",), "금속재질"),
        (("plastic",), "플라스틱재질"),
        (("fabric", "cloth"), "천재질"),
        (("leather",), "가죽재질"),
        (("transparent", "clear"), "투명부분"),
        (("button",), "버튼있음"),
        (("cable", "cord"), "케이블부착"),
        (("handle",), "손잡이있음"),
        (("zipper", "zip"), "지퍼있음"),
        (("ring",), "고리있음"),
        (("cover",), "커버있음"),
        (("keychain",), "키링있음"),
    ]
    lowered = raw.lower()
    for keywords, label in keyword_fallback:
        if any(keyword in lowered for keyword in keywords) and label not in found:
            found.append(label)

    if not found:
        return "외형특징미확인"

    return " · ".join(found[:4])


def _batch_ask_vlm(image: Image.Image):
    """
    작은 VLM의 자유문장 생성을 최소화하기 위해
    category/color/features는 정해진 CODE 중 하나(또는 여러 개)만 선택하게 한다.
    """
    processor, model = _load_vlm_model()
    device = next(model.parameters()).device
    rgb_image = image.convert("RGB")

    category_codes = ", ".join(CATEGORY_LABELS.keys())
    color_codes = ", ".join(COLOR_LABELS.keys())
    feature_codes = ", ".join(FEATURE_LABELS.keys())

    questions = [
        (
            "Classify the single main lost-and-found object. "
            f"Choose EXACTLY ONE code from this list: {category_codes}. "
            "Return ONLY the code. No sentence. No explanation."
        ),
        (
            "Classify the main visible color of the main object. "
            f"Choose EXACTLY ONE code from this list: {color_codes}. "
            "Return ONLY the code. No sentence. No explanation."
        ),
        (
            "Identify the visible brand or logo of the main object. "
            "Return ONLY ONE short brand name such as Apple, Samsung, Sony, Nike. "
            "If the brand/logo is not clearly visible, return ONLY NONE. "
            "No sentence. No explanation."
        ),
        (
            "Select visible exterior feature codes for the main object. "
            f"Choose up to FOUR codes from this list: {feature_codes}. "
            "Return ONLY comma-separated codes. "
            "If none are clearly visible, return ONLY NONE. "
            "No sentence. No explanation."
        ),
    ]

    prompts = []
    for question in questions:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": question},
                ],
            }
        ]
        prompts.append(
            processor.apply_chat_template(messages, add_generation_prompt=True)
        )

    inputs = processor(
        text=prompts,
        images=[[rgb_image], [rgb_image], [rgb_image], [rgb_image]],
        padding=True,
        return_tensors="pt",
    )
    inputs = {
        key: value.to(device) if hasattr(value, "to") else value
        for key, value in inputs.items()
    }

    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=20,
            do_sample=False,
        )

    input_length = inputs["input_ids"].shape[-1]
    generated_only = generated_ids[:, input_length:]
    answers = processor.batch_decode(
        generated_only,
        skip_special_tokens=True,
    )

    while len(answers) < 4:
        answers.append("")

    return answers[:4]


def extract_item_info(image: Image.Image):
    """
    습득물 사진에서 등록 필드를 추출한 뒤
    사용자 화면에는 한국어 정규화 값만 반환한다.
    """
    answers = _batch_ask_vlm(image)

    return {
        "category": _normalize_category(answers[0]),
        "color": _normalize_color(answers[1]),
        "brand": _normalize_brand(answers[2]),
        "features": _normalize_features(answers[3]),
        "model": VLM_MODEL_NAME,
        "_raw_output": {
            "category": answers[0],
            "color": answers[1],
            "brand": answers[2],
            "features": answers[3],
        },
    }


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


# ---------------------------------------------------------
# 습득물 백그라운드 자동 분석
# 습득자는 사진만 올리고 바로 나갈 수 있도록 등록은 즉시 끝내고,
# VLM 정보 추출 + DINOv2 임베딩은 서버의 분석 스레드 하나가 순서대로 처리한다.
# (CPU에서 모델을 여러 요청이 동시에 돌리면 메모리가 부족해지므로 한 번에 하나씩)
# ---------------------------------------------------------
STATUS_ANALYZING = "analyzing"
STATUS_REGISTERED = "registered"
STATUS_ANALYSIS_FAILED = "analysis_failed"

_analysis_queue = queue.Queue()


def analyze_registered_item(item_id: int):
    """등록된 습득물 사진을 분석해서 비어 있는 칸만 채우고 상태를 registered로 바꾼다."""
    db = SessionLocal()
    try:
        item = db.query(models.Item).filter(models.Item.id == item_id).first()
        if item is None or item.status != STATUS_ANALYZING:
            return

        try:
            with Image.open(item.image_path) as image:
                rgb_image = image.convert("RGB")

            if not item.embedding:
                item.embedding = json.dumps(get_embedding(rgb_image))

            info = extract_item_info(rgb_image)

            # 습득자가 직접 입력한 값은 덮어쓰지 않는다
            item.category = item.category or info["category"]
            item.color = item.color or info["color"]
            item.brand = item.brand or info["brand"]
            item.description = item.description or info["features"]
            item.status = STATUS_REGISTERED
        except Exception:
            logger.exception("습득물 #%s 자동 분석 실패", item_id)
            item.status = STATUS_ANALYSIS_FAILED

        db.commit()
    finally:
        db.close()


def _analysis_worker():
    while True:
        item_id = _analysis_queue.get()
        try:
            analyze_registered_item(item_id)
        except Exception:
            logger.exception("습득물 #%s 분석 작업 오류", item_id)
        finally:
            _analysis_queue.task_done()


@app.on_event("startup")
def start_analysis_worker():
    threading.Thread(target=_analysis_worker, name="findyu-analysis", daemon=True).start()

    # 분석 도중 서버가 꺼졌던 항목은 다시 대기열에 넣는다
    db = SessionLocal()
    try:
        pending = (
            db.query(models.Item.id)
            .filter(models.Item.status == STATUS_ANALYZING)
            .order_by(models.Item.id)
            .all()
        )
    finally:
        db.close()

    for (item_id,) in pending:
        _analysis_queue.put(item_id)


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "message": "FindYU backend is running",
        "image_embedding_model": MODEL_NAME,
        "registration_vlm_model": VLM_MODEL_NAME,
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


@app.post("/items/analyze")
async def analyze_item_image(image: UploadFile = File(...)):
    """
    습득물 사진을 등록하기 전에 VLM으로 종류/색상/브랜드/외형적 특징을 추출한다.
    프론트엔드는 이 결과를 입력란에 자동 채우고, 사용자가 수정한 뒤 POST /items로 확정 등록한다.
    """
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="image is required")

    try:
        pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid image file") from exc

    try:
        result = extract_item_info(pil_image)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Vision-Language analysis failed: {exc}",
        ) from exc

    if not any(result.get(key) for key in ("category", "color", "brand", "features")):
        raw_output = result.get("_raw_output") or {}
        raise HTTPException(
            status_code=422,
            detail=f"VLM 응답은 받았지만 등록 정보를 추출하지 못했습니다. 원문: {raw_output}",
        )

    result.pop("_raw_output", None)

    return {
        **result,
        "description": result["features"],
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

    try:
        Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid image file") from exc

    saved_path = save_uploaded_image(image_bytes, image.filename)

    # 임베딩·VLM 분석은 기다리지 않고 바로 응답한다 (analyze_registered_item 참고)
    new_item = models.Item(
        item_type=item_type,
        category=category,
        color=color,
        brand=brand,
        description=description,
        image_path=saved_path,
        location=location,
        occurred_at=parse_optional_datetime(occurred_at),
        status=STATUS_ANALYZING,
    )

    db.add(new_item)
    db.commit()
    db.refresh(new_item)

    _analysis_queue.put(new_item.id)

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
