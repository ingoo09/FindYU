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
from pathlib import Path

from dotenv import load_dotenv

# backend/.env의 환경변수를 읽는다 (이미 설정된 환경변수가 우선)
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from PIL import Image, ImageOps
from transformers import AutoProcessor

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
import time
import uuid

from database import DB_PATH, engine, Base, get_db, SessionLocal
import models
import labels
from migrations import run_migrations
from paths import UPLOAD_DIR, image_filename, resolve_image_path, to_stored_path
from ai_retrieval import RetrievalModelManager, cosine_score
from search_graph import run_search_graph
from ai_query_parser import QueryParser
import baze_analyzer
import check_form
import gemini_embedding
import item_list
import search_adapter
import search_candidates
import gemini_analyzer
from gemini_analyzer import AnalyzerConfigError, AnalyzerError

logger = logging.getLogger("findyu")

# AI 브랜치의 실행 모드 의미를 그대로 따른다.
# query_parser_mode: "mock" | "llm"
# registration_analyzer_mode: "mock" | "vlm" | "gemini" | "baze"(기본, 팩트챗 게이트웨이)
QUERY_PARSER_MODE = os.getenv("FINDYU_QUERY_PARSER_MODE", "llm").lower()
QUERY_LLM_MODEL_NAME = os.getenv(
    "FINDYU_QUERY_LLM_MODEL",
    "Qwen/Qwen3-0.6B",
)
REGISTRATION_ANALYZER_MODE = os.getenv(
    "FINDYU_REGISTRATION_ANALYZER_MODE",
    "baze",
).lower()
# search_analyzer_mode: "baze"(게이트웨이 임베딩 + Gemini 비교) | "mock"(기본, API 호출 없음) | "local"(기존 DINOv2·SigLIP2)
# 기본값은 AI의 search_analyzer.py가 병합될 때까지 mock (search_adapter.DEFAULT_MODE)
# baze·mock에서는 로컬 검색 모델을 불러오지 않는다
SEARCH_ANALYZER_MODE = (
    os.getenv("FINDYU_SEARCH_ANALYZER_MODE", "").strip().lower() or search_adapter.DEFAULT_MODE
)
if SEARCH_ANALYZER_MODE not in search_adapter.MODES:
    raise RuntimeError("FINDYU_SEARCH_ANALYZER_MODE는 baze, mock, local 중 하나여야 합니다.")

app = FastAPI(title="FindYU Backend - Midterm Demo")

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
run_migrations(DB_PATH)  # 기존 findyu.db에 새 컬럼 추가 등 (migrations.py 참고)


# ---------------------------------------------------------
# AI branch retrieval models
# ---------------------------------------------------------
MODEL_NAME = os.getenv("FINDYU_IMAGE_MODEL", "facebook/dinov2-small")
TEXT_IMAGE_MODEL_NAME = os.getenv(
    "FINDYU_TEXT_IMAGE_MODEL",
    "google/siglip2-base-patch16-224",
)

_retrieval_models = RetrievalModelManager(
    image_model_name=MODEL_NAME,
    text_image_model_name=TEXT_IMAGE_MODEL_NAME,
)

VLM_MODEL_NAME = os.getenv(
    "FINDYU_VLM_MODEL",
    "HuggingFaceTB/SmolVLM-500M-Instruct",
)
_vlm_processor = None
_vlm_model = None
_vlm_lock = threading.Lock()

# candidate SigLIP image embedding cache: {resolved file path: (mtime, embedding)}
_siglip_image_cache = {}
_siglip_cache_lock = threading.Lock()

_query_parser = QueryParser(
    mode=QUERY_PARSER_MODE,
    model_name=QUERY_LLM_MODEL_NAME,
    prompt_path=os.path.join(
        os.path.dirname(__file__),
        "prompts",
        "query_parser_system.txt",
    ),
)


def open_image(source) -> Image.Image:
    """
    사진을 RGB로 연다. 휴대폰 사진의 EXIF 회전 정보를 반영해 똑바로 세운다.
    검색 임베딩·검색어 사진·등록 분석 모두 이 함수를 거쳐야 같은 방향으로 비교된다.
    """
    with Image.open(source) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def get_embedding(image: Image.Image):
    """AI branch의 DINOv2 image embedding을 현재 PIL 기반 API에 맞게 사용."""
    return _retrieval_models.dino_image(image)


def get_text_embedding(text: str):
    """AI branch의 SigLIP2 text embedding."""
    if not text or not text.strip():
        return None
    return _retrieval_models.siglip_text(text.strip())


def get_siglip_image_embedding(item):
    """등록 이미지의 SigLIP2 embedding을 메모리 캐시와 함께 반환."""
    image_file = resolve_image_path(item.image_path)
    if image_file is None:
        return []

    cache_key = str(image_file)
    try:
        mtime = image_file.stat().st_mtime
    except OSError:
        return []

    with _siglip_cache_lock:
        cached = _siglip_image_cache.get(cache_key)
        if cached and cached[0] == mtime:
            return cached[1]

    try:
        vector = _retrieval_models.siglip_image(open_image(image_file))
    except Exception:
        logger.exception("SigLIP2 candidate embedding 실패: %s", item.image_path)
        return []

    with _siglip_cache_lock:
        _siglip_image_cache[cache_key] = (mtime, vector)

    return vector


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


_gemini_analyzer = gemini_analyzer.GeminiAnalyzer()
_baze_analyzer = baze_analyzer.BazeAnalyzer()
# /items/analyze 결과를 POST /items에서 다시 쓰기 위한 보관소 (check_form.AnalysisCache 참고)
_analysis_cache = check_form.AnalysisCache()
# 사진 검색용 이미지 임베딩 (baze: 게이트웨이 / mock: API 없음 / local: 없음, DINOv2 사용)
_embedder = gemini_embedding.make_embedder(SEARCH_ANALYZER_MODE)

# 세 분석 모드가 공통으로 반환하는 키. 모드가 지원하지 않는 항목은 기본값으로 둔다.
EMPTY_ANALYSIS = {
    "category": None,
    "color": None,
    "manufacturer": None,
    "brand": None,
    "device_model": None,
    "device_model_candidates": [],
    "identification_level": None,
    "has_case": None,
    "has_card_wallet": None,
    "earphone_components": None,
    "wallet_type": None,
    "material": None,
    "wallet_closure": None,
    "verification_needed": [],
    "features": None,
    "evidence": [],
    "generation_evidence": [],
    "same_item": None,
    "confidence": {},
    "confidence_scores": {},
    "prompt_version": None,
    "model": None,
}


def extract_item_info(images: list[Image.Image]):
    """
    습득물 사진(1장 이상)에서 등록 필드를 추출한다.

    registration_analyzer_mode:
    - mock  : 모델을 실행하지 않고 고정 결과 반환
    - vlm   : 로컬 SmolVLM 실행 (첫 번째 사진만 사용, 기종·확신도 미지원)
    - gemini: Gemini API + 프롬프트 v1.2 (gemini_analyzer.py)
    - baze  : 팩트챗(BAZE) 게이트웨이로 Gemini 호출, 프롬프트·스키마는 gemini와 같음 (baze_analyzer.py)
    """
    if isinstance(images, Image.Image):
        images = [images]
    if not images:
        raise ValueError("분석할 사진이 없습니다.")

    if REGISTRATION_ANALYZER_MODE == "mock":
        return {
            **EMPTY_ANALYSIS,
            "category": labels.CATEGORY_PHONE,
            "color": "검정",
            "manufacturer": "애플",
            "brand": "애플",
            "device_model": "iPhone 15",
            "device_model_candidates": ["iPhone 14"],
            "identification_level": "추정",
            "has_case": True,
            "verification_needed": ["측면 사진 없음 (액션 버튼 여부 확인 불가)"],
            "features": "케이스형",
            "same_item": True,
            "confidence": {"category": "높음", "manufacturer": "높음", "device_model": "보통", "color": "보통"},
            "confidence_scores": {"category": 0.9, "manufacturer": 0.9, "device_model": 0.6, "color": 0.6},
            "model": "mock",
            "_raw_output": {},
        }

    if REGISTRATION_ANALYZER_MODE == "gemini":
        return _gemini_analyzer.analyze(images)

    if REGISTRATION_ANALYZER_MODE == "baze":
        return _baze_analyzer.analyze(images)

    # AI 브랜치에서는 registration_analyzer_mode="vlm"이 올바른 값이다.
    # 사용자가 실수로 "llm"을 넣은 경우도 데모가 죽지 않도록 VLM alias로 허용한다.
    if REGISTRATION_ANALYZER_MODE not in {"vlm", "llm"}:
        raise ValueError(
            "registration_analyzer_mode는 mock, vlm, gemini, baze 중 하나여야 합니다."
        )

    answers = _batch_ask_vlm(images[0])

    # VLM의 세부 품명(이어폰, 카드 등)은 서비스 품명(스마트폰/지갑/기타)으로 다시 매핑
    brand = _normalize_brand(answers[2])
    return {
        **EMPTY_ANALYSIS,
        "category": labels.normalize_category(_normalize_category(answers[0])),
        "color": labels.normalize_color(_normalize_color(answers[1])),
        "brand": None if brand == "미확인" else brand,
        "features": _normalize_features(answers[3]),
        "model": VLM_MODEL_NAME,
        "_raw_output": {
            "category": answers[0],
            "color": answers[1],
            "brand": answers[2],
            "features": answers[3],
        },
    }


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
    filename = image_filename(path)
    return f"/uploads/{filename}" if filename else None


def save_uploaded_image(file_bytes: bytes, original_filename: str) -> str:
    ext = os.path.splitext(original_filename or "")[1].lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"

    unique_name = f"{uuid.uuid4().hex}{ext}"

    with open(UPLOAD_DIR / unique_name, "wb") as file:
        file.write(file_bytes)

    # DB에는 OS와 무관한 "uploads/<파일명>" 형식으로 저장
    return to_stored_path(unique_name)


def item_embedding(item):
    """
    현재 DINOv2 차원과 일치하는 저장 임베딩은 그대로 사용한다.
    과거 mock/fallback 임베딩은 이미지 파일에서 DINOv2로 다시 계산한다.
    """
    expected_size = _retrieval_models.dino_dimension()

    try:
        stored = json.loads(item.embedding) if item.embedding else None
        if stored and len(stored) == expected_size:
            return [float(value) for value in stored]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    image_file = resolve_image_path(item.image_path)
    if image_file is not None:
        return get_embedding(open_image(image_file))

    return []


def serialize_item(item):
    images = list(item.images or [])
    if not images and item.image_path:
        # item_images가 없는 경우(마이그레이션 이전 데이터 등) 대표 사진만 표시
        image_list = [{"position": 0, "image_url": public_image_url(item.image_path)}]
    else:
        image_list = [
            {"position": image.position, "image_url": public_image_url(image.image_path)}
            for image in images
        ]

    return {
        "id": item.id,
        "item_type": item.item_type,
        "category": item.category,
        "color": item.color,
        "brand": item.brand,
        "description": item.description,
        "manufacturer": item.manufacturer,
        "device_model": item.device_model,
        "device_model_candidates": labels.load_str_list(item.device_model_candidates),
        "identification_level": item.identification_level,
        "has_case": item.has_case,
        "has_card_wallet": item.has_card_wallet,
        "earphone_components": item.earphone_components,
        "wallet_type": item.wallet_type,
        "material": item.material,
        "wallet_closure": item.wallet_closure,
        "verification_needed": labels.load_str_list(item.verification_needed),
        # 체크 폼 기준 값과 항목별 출처(human/ai)
        "form_values": check_form.item_form_values(item),
        "field_sources": json.loads(item.field_sources) if item.field_sources else {},
        "analysis_model": item.analysis_model,
        "confidence": {
            "category": item.category_confidence,
            "manufacturer": item.manufacturer_confidence,
            "device_model": item.device_model_confidence,
            "color": item.color_confidence,
        },
        "location": item.location,
        "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "image_path": item.image_path,
        "image_url": public_image_url(item.image_path),
        "images": image_list,
    }


# ---------------------------------------------------------
# 습득물 백그라운드 자동 분석
# 습득자는 사진만 올리고 바로 나갈 수 있도록 등록은 즉시 끝내고,
# VLM 정보 추출 + DINOv2 임베딩은 서버의 분석 스레드 하나가 순서대로 처리한다.
# (CPU에서 모델을 여러 요청이 동시에 돌리면 메모리가 부족해지므로 한 번에 하나씩)
# ---------------------------------------------------------
# 상태 값은 목록 API의 status 필터와 함께 item_list.py에 둔다
STATUS_ANALYZING = item_list.STATUS_ANALYZING
STATUS_REGISTERED = item_list.STATUS_REGISTERED
STATUS_ANALYSIS_FAILED = item_list.STATUS_ANALYSIS_FAILED

_analysis_queue = queue.Queue()


# AI 확신도를 함께 저장하는 항목: (DB 컬럼, 확신도 컬럼, 분석 결과 키)
CONFIDENCE_FIELDS = [
    ("category", "category_confidence", "category"),
    ("manufacturer", "manufacturer_confidence", "manufacturer"),
    ("device_model", "device_model_confidence", "device_model"),
    ("color", "color_confidence", "color"),
]


def apply_analysis(item, info: dict):
    """
    분석 결과를 비어 있는 칸에만 채운다 (습득자가 고른 값은 덮어쓰지 않음 = 사람 > AI).
    확신도는 AI가 실제로 채운 항목에만 저장한다.
    품목별 전용 항목(케이스, 지갑 종류 등)은 최종 품목에 해당할 때만 채운다
    (습득자가 품목을 AI와 다르게 고른 경우 AI의 다른 품목 항목은 버림).
    """
    filled = []
    scores = info.get("confidence_scores") or {}
    for column, confidence_column, key in CONFIDENCE_FIELDS:
        if getattr(item, column) is None and info.get(key) is not None:
            setattr(item, column, info[key])
            setattr(item, confidence_column, scores.get(key))
            filled.append(column)

    for column in (
        "brand", "identification_level", "has_case", "has_card_wallet",
        "earphone_components", "wallet_type", "material", "wallet_closure",
    ):
        if not check_form.column_allowed(column, item.category):
            continue
        if getattr(item, column) is None and info.get(column) is not None:
            setattr(item, column, info[column])
            filled.append(column)

    for column in ("device_model_candidates", "verification_needed"):
        if not getattr(item, column):
            setattr(item, column, labels.dump_str_list(info.get(column)))

    item.description = item.description or info.get("features")
    item.field_sources = check_form.merge_sources(
        item.field_sources, check_form.ai_sources(item, filled)
    )
    model = info.get("model") or REGISTRATION_ANALYZER_MODE
    item.analysis_model = f"{REGISTRATION_ANALYZER_MODE}:{model}/{info.get('prompt_version') or '-'}"


def analyze_registered_item(item_id: int):
    """
    등록 후 백그라운드 작업 (물품 하나).

    1) status=analyzing이면 등록 분석으로 비어 있는 칸만 채우고 registered로 바꾼다.
       수동 등록(defer_analysis)은 처음부터 registered라 등록 분석을 부르지 않는다.
    2) 사진 검색용 임베딩을 계산한다.
       - baze·mock: Gemini 이미지 임베딩 1회 시도. 실패하면 비워 두고 등록 결과에는 영향 없음
       - local: 기존 DINOv2 임베딩 (로컬 모델)
    """
    db = SessionLocal()
    try:
        item = db.query(models.Item).filter(models.Item.id == item_id).first()
        if item is None:
            return
        if item.status == STATUS_ANALYZING:
            _run_registration_analysis(db, item)
        if item.status != STATUS_ANALYSIS_FAILED:
            _store_search_embedding(db, item)
    finally:
        db.close()


def _store_search_embedding(db, item):
    image_file = resolve_image_path(item.image_path)
    if image_file is None:
        logger.warning("습득물 #%s 검색 임베딩 생략: 대표 사진 없음", item.id)
        return

    if _embedder is None:  # local
        if not item.embedding:
            try:
                item.embedding = json.dumps(get_embedding(open_image(image_file)))
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("습득물 #%s DINOv2 임베딩 실패", item.id)
        return

    if item.image_embedding_gemini and item.image_embedding_model == _embedder.model_id:
        return
    try:
        vector = _embedder.embed_images([open_image(image_file)])[0]
    except Exception as exc:
        # 1회만 시도하고 비워 둔다. 사진 검색에서는 남은 자리를 명세 순서로 채울 때 들어간다
        db.rollback()
        logger.warning("습득물 #%s 사진 임베딩 실패 (비워 둠): %s", item.id, exc)
        return
    item.image_embedding_gemini = json.dumps(vector)
    item.image_embedding_model = _embedder.model_id
    db.commit()


def _run_registration_analysis(db, item):
    """등록 분석으로 비어 있는 칸만 채운다. 실패하면 analysis_failed (검색 대상에서 빠짐)."""
    item_id = item.id
    try:
        image_file = resolve_image_path(item.image_path)
        if image_file is None:
            raise FileNotFoundError(f"이미지 파일 없음: {item.image_path}")

        # 등록 분석은 사진 전체(대표 사진 먼저)를 함께 본다
        analysis_files = [image_file]
        for extra in item.images or []:
            extra_file = resolve_image_path(extra.image_path)
            if extra_file is None:
                logger.warning("습득물 #%s 추가 사진 없음: %s", item_id, extra.image_path)
            elif extra_file not in analysis_files:
                analysis_files.append(extra_file)

        # 등록 전에 /items/analyze 결과를 이미 반영했다면(analysis_model 있음) 다시 호출하지 않는다
        if item.analysis_model is None:
            info = extract_item_info([open_image(f) for f in analysis_files])
            apply_analysis(item, info)
        item.status = STATUS_REGISTERED
    except AnalyzerConfigError as exc:
        # API 키 누락 등 설정 문제: 스택트레이스 대신 해결 방법이 담긴 메시지만 남긴다
        logger.error("습득물 #%s 자동 분석 불가: %s", item_id, exc)
        item.status = STATUS_ANALYSIS_FAILED
    except Exception:
        logger.exception("습득물 #%s 자동 분석 실패", item_id)
        item.status = STATUS_ANALYSIS_FAILED

    db.commit()


def backfill_missing_embeddings():
    """
    검색 임베딩이 비어 있는 등록 완료 물품의 임베딩을 계산해 저장한다.
    (마이그레이션 v6이 EXIF 회전 반영 전 임베딩을 비운 경우 등)
    """
    db = SessionLocal()
    try:
        items = (
            db.query(models.Item)
            .filter(models.Item.embedding.is_(None))
            .filter(models.Item.status == STATUS_REGISTERED)
            .all()
        )
        done = 0
        for item in items:
            image_file = resolve_image_path(item.image_path)
            if image_file is None:
                continue
            try:
                item.embedding = json.dumps(get_embedding(open_image(image_file)))
                db.commit()
                done += 1
            except Exception:
                db.rollback()
                logger.exception("습득물 #%s 임베딩 재계산 실패", item.id)
        if items:
            logger.warning("검색 임베딩 재계산: %d / %d건", done, len(items))
    finally:
        db.close()


def _analysis_worker():
    # 모델을 한 스레드에서만 쓰도록 분석 작업 전에 같은 스레드에서 처리한다
    # baze·mock 검색에서는 로컬 모델(DINOv2)을 불러오지 않으므로 건너뛴다.
    # Gemini 임베딩 백필은 자동 실행하지 않는다 (tools/backfill_gemini_embeddings.py)
    if SEARCH_ANALYZER_MODE == "local":
        try:
            backfill_missing_embeddings()
        except Exception:
            logger.exception("검색 임베딩 재계산 작업 오류")

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
    remote_status = {
        "gemini": gemini_analyzer.config_status,
        "baze": baze_analyzer.config_status,
    }.get(REGISTRATION_ANALYZER_MODE)
    if remote_status is not None:
        status = remote_status()
        if status["ready"]:
            logger.warning(
                "등록 분석: %s %s (프롬프트 %s)",
                REGISTRATION_ANALYZER_MODE,
                status["model"],
                status["prompt_version"],
            )
        else:
            # 서버는 계속 띄우고, 분석 요청만 명확한 에러로 실패시킨다
            logger.error("등록 분석 비활성화 - %s", status["error"])

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
        "text_image_embedding_model": TEXT_IMAGE_MODEL_NAME,
        "query_parser_mode": QUERY_PARSER_MODE,
        "query_llm_model": QUERY_LLM_MODEL_NAME,
        "registration_analyzer_mode": REGISTRATION_ANALYZER_MODE,
        "registration_vlm_model": VLM_MODEL_NAME,
        "registration_gemini": (
            gemini_analyzer.config_status()
            if REGISTRATION_ANALYZER_MODE == "gemini"
            else None
        ),
        "registration_baze": (
            baze_analyzer.config_status()
            if REGISTRATION_ANALYZER_MODE == "baze"
            else None
        ),
        "search_analyzer_mode": SEARCH_ANALYZER_MODE,
        "search_embedding_model": _embedder.model_id if _embedder is not None else MODEL_NAME,
        "search_workflow": "LangGraph" if SEARCH_ANALYZER_MODE == "local" else "embedding+gemini-compare",
    }


@app.post("/compare")
async def compare_images(
    image1: UploadFile = File(...),
    image2: UploadFile = File(...),
):
    img1_bytes = await image1.read()
    img2_bytes = await image2.read()

    img1 = open_image(io.BytesIO(img1_bytes))
    img2 = open_image(io.BytesIO(img2_bytes))

    emb1 = get_embedding(img1)
    emb2 = get_embedding(img2)
    score = cosine_score(emb1, emb2)

    return {
        "similarity_score": round(score, 4),
        "similarity": round(score, 4),  # 이전 이름 (프론트 전환 후 제거 예정)
        # 예전 기준 (cos + 1) / 2 >= 0.8 과 같은 기준 = 코사인 0.6 이상
        "is_same_item": score >= 0.6,
        "scoring_mode": "dinov2+metadata",
    }


@app.post("/items/analyze")
async def analyze_item_image(
    image: UploadFile = File(...),
    extra_images: list[UploadFile] | None = File(None),  # 같은 물품의 다른 각도 사진 (선택)
):
    """
    습득물 사진(1장 이상)을 등록하기 전에 분석해 품명/색상/제조사/기종 등을 추출한다.
    프론트엔드는 check_form으로 체크 폼을 미리 채우고(needs_check 항목 강조),
    습득자가 확인한 뒤 analysis_id와 함께 POST /items로 등록한다.
    """
    pil_images = []
    blobs = []
    for upload in [image, *(extra_images or [])]:
        if upload is None or not upload.filename:
            continue
        image_bytes = await upload.read()
        if not image_bytes:
            continue
        blobs.append(image_bytes)
        try:
            pil_images.append(open_image(io.BytesIO(image_bytes)))
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid image file: {upload.filename}"
            ) from exc

    if not pil_images:
        raise HTTPException(status_code=400, detail="image is required")
    if len(pil_images) > gemini_analyzer.MAX_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"사진은 최대 {gemini_analyzer.MAX_IMAGES}장까지 분석할 수 있습니다.",
        )

    try:
        # Gemini/VLM 호출은 오래 걸리므로 이벤트 루프를 막지 않게 스레드에서 실행
        result = await run_in_threadpool(extract_item_info, pil_images)
    except AnalyzerConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AnalyzerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("등록 분석 실패")
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

    form = check_form.build_check_form(result, image_count=len(pil_images))
    analysis_id = _analysis_cache.put(result, check_form.image_digests(blobs))

    return {
        **result,
        "description": result["features"],
        "analysis_id": analysis_id,
        "check_form": form,
        "photo_hint": form["photo_hint"],
    }


@app.get("/form-schema")
def get_form_schema(category: str = None):
    """
    품목별 체크 폼 항목과 선택지. category를 빼면 전 품목을 한 번에 준다.
    모든 선택형 항목에 "모르겠음"이 있다 (등록: AI 값 사용 / 검색: 거르지 않음).
    """
    try:
        normalized = check_form.validate_category(category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return check_form.form_schema(normalized)


@app.post("/items")
async def register_item(
    item_type: str = Form(...),
    category: str = Form(None),
    color: str = Form(None),
    brand: str = Form(None),
    description: str = Form(None),
    manufacturer: str = Form(None),
    device_model: str = Form(None),
    device_model_candidates: str = Form(None),  # JSON 배열 또는 쉼표 구분 문자열
    identification_level: str = Form(None),     # 확인 / 추정 / 미확인
    has_case: str = Form(None),                 # true / false (빈 값 = 판단 불가)
    wallet_type: str = Form(None),              # 장지갑 / 반지갑 / 카드지갑
    material: str = Form(None),
    verification_needed: str = Form(None),      # JSON 배열 또는 쉼표 구분 문자열
    location: str = Form(None),
    occurred_at: str = Form(None),
    analysis_id: str = Form(None),              # /items/analyze 응답의 analysis_id (선택)
    form_answers: str = Form(None),             # 체크 폼에서 사람이 고른 값 {"color": "검정", ...} (JSON)
    defer_analysis: str = Form(None),           # true: 등록 분석을 부르지 않고 직접 입력값으로 바로 registered
    image: UploadFile = File(...),                        # 대표 사진
    extra_images: list[UploadFile] | None = File(None),   # 같은 물품의 다른 각도 사진 (선택)
    db: Session = Depends(get_db),
):
    if item_type not in {"found", "lost"}:
        raise HTTPException(status_code=400, detail="item_type must be 'found' or 'lost'")

    deferred = labels.parse_optional_bool(defer_analysis)
    if defer_analysis not in (None, "") and deferred is None:
        raise HTTPException(status_code=400, detail="defer_analysis는 true 또는 false여야 합니다.")

    normalized_level = labels.normalize_identification_level(identification_level)
    if identification_level and normalized_level is None:
        raise HTTPException(
            status_code=400,
            detail=f"identification_level must be one of {list(labels.IDENTIFICATION_LEVELS)}",
        )
    normalized_wallet_type = labels.normalize_wallet_type(wallet_type)
    if wallet_type and normalized_wallet_type is None:
        raise HTTPException(
            status_code=400,
            detail=f"wallet_type must be one of {list(labels.WALLET_TYPES)}",
        )

    uploads = []  # (bytes, filename), 첫 번째가 대표 사진
    for upload in [image, *(extra_images or [])]:
        if upload is None or not upload.filename:
            continue
        image_bytes = await upload.read()
        if not image_bytes:
            continue
        try:
            with Image.open(io.BytesIO(image_bytes)) as check:
                check.verify()
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid image file: {upload.filename}"
            ) from exc
        uploads.append((image_bytes, upload.filename))

    if not uploads:
        raise HTTPException(status_code=400, detail="image is required")
    if len(uploads) > gemini_analyzer.MAX_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"사진은 최대 {gemini_analyzer.MAX_IMAGES}장까지 등록할 수 있습니다.",
        )

    # 같은 사진 묶음을 등록 전에 분석했다면 그 결과를 쓴다 (다른 사진이면 무시하고 등록 후 다시 분석)
    cached_analysis = _analysis_cache.get(
        analysis_id, check_form.image_digests([data for data, _ in uploads])
    )
    try:
        human = check_form.resolve_answers(
            check_form.parse_answers(form_answers),
            fallback_category=labels.normalize_category(category)
            or (cached_analysis or {}).get("category"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 검증을 모두 통과한 뒤에 저장한다 (중간에 실패해도 파일이 남지 않도록)
    saved_paths = [save_uploaded_image(data, name) for data, name in uploads]
    saved_path = saved_paths[0]

    # 임베딩·VLM 분석은 기다리지 않고 바로 응답한다 (analyze_registered_item 참고)
    new_item = models.Item(
        item_type=item_type,
        category=labels.normalize_category(category),
        color=labels.normalize_color(color),
        brand=brand,
        description=description,
        manufacturer=(manufacturer or "").strip() or None,
        device_model=(device_model or "").strip() or None,
        device_model_candidates=labels.dump_str_list(device_model_candidates),
        identification_level=normalized_level,
        has_case=labels.parse_optional_bool(has_case),
        wallet_type=normalized_wallet_type,
        material=labels.normalize_material(material),
        verification_needed=labels.dump_str_list(verification_needed),
        image_path=saved_path,
        location=location,
        occurred_at=parse_optional_datetime(occurred_at),
        # 수동 등록은 등록 분석을 부르지 않으므로 바로 registered (검색·목록 대상)
        status=STATUS_REGISTERED if deferred else STATUS_ANALYZING,
        images=[
            models.ItemImage(image_path=path, position=position)
            for position, path in enumerate(saved_paths)
        ],
    )

    # 우선순위: 체크 폼에서 사람이 고른 값 > 기존 입력란 값 > AI 값 (apply_analysis는 빈 칸만 채움)
    sources = check_form.apply_human(new_item, human, cached_analysis)
    legacy_human = {
        key: check_form.SOURCE_HUMAN
        for key, value in (("category", category), ("color", color), ("brand", manufacturer or brand))
        if value and key not in sources
    }
    new_item.field_sources = check_form.merge_sources(None, legacy_human, sources)
    if cached_analysis is not None:
        apply_analysis(new_item, cached_analysis)

    db.add(new_item)
    db.commit()
    db.refresh(new_item)

    # 백그라운드: 등록 분석(analyzing일 때만) + 사진 검색 임베딩 1회 시도.
    # 수동 등록도 임베딩은 시도한다 (등록 분석 호출은 0회, 임베딩 실패는 등록 결과에 영향 없음)
    _analysis_queue.put(new_item.id)

    return serialize_item(new_item)


@app.get("/items")
def list_items(
    item_type: str = None,   # found / lost (없으면 전체)
    category: str = None,    # 스마트폰 / 이어폰 / 지갑 / 기타 (모르겠음이면 거르지 않음)
    location: str = None,    # 부분 일치
    status: str = None,      # analyzing / registered / analysis_failed
    page: str = None,        # 1부터, 기본 1
    page_size: str = None,   # 1~100, 기본 20
    sort: str = None,        # newest(기본) / oldest (등록 시각 기준)
    db: Session = Depends(get_db),
):
    """물품 목록. 필터 + 등록 시각 정렬 + 페이지 나누기 (docs/API.md 참고)."""
    try:
        query = item_list.parse_list_query(
            item_type=item_type, category=category, location=location, status=status,
            page=page, page_size=page_size, sort=sort,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    items, total = item_list.query_items(db, query)
    return {
        "items": [serialize_item(item) for item in items],
        **item_list.page_info(query, total),
        "sort": query.sort,
        "filters": query.applied_filters(),
    }


# /items/{item_id}보다 먼저 선언해야 "locations"가 id로 해석되지 않는다
@app.get("/items/locations")
def list_item_locations(item_type: str = None, db: Session = Depends(get_db)):
    """장소 필터 선택지: 등록된 장소와 물품 수."""
    try:
        return {"locations": item_list.location_options(db, item_type)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    category: str = Form(None),   # 체크 폼 품목 (스마트폰/이어폰/지갑/기타/모르겠음)
    filters: str = Form(None),    # 체크 폼에서 분실자가 고른 값 {"color": "검정", ...} (JSON)
    db: Session = Depends(get_db),
):
    """분실물 검색. FINDYU_SEARCH_ANALYZER_MODE에 따라 게이트웨이(baze·mock) 또는 기존 로컬 검색(local)."""
    if SEARCH_ANALYZER_MODE == "local":
        return await _local_search(
            description=description, location=location, occurred_at=occurred_at, image=image,
            top_k=top_k, category=category, filters=filters, db=db,
        )
    return await _gateway_search(
        description=description, location=location, occurred_at=occurred_at, image=image,
        top_k=top_k, category=category, filters=filters, db=db,
    )


# 구형 점수 필드: 게이트웨이 검색에서는 값을 채우지 않고 전환 기간 동안 null로만 둔다 (docs/API.md)
LEGACY_SCORE_FIELDS = (
    "similarity_score", "matching_score", "similarity",
    "image_similarity", "text_similarity", "location_score", "time_score",
)
GATEWAY_TOP_K_MAX = 5


def _load_candidate_jpeg(item) -> bytes | None:
    """후보 대표 사진 → 비교용 JPEG 바이트. 읽을 수 없으면 None."""
    image_file = resolve_image_path(item.image_path)
    if image_file is None:
        return None
    try:
        return search_adapter.to_jpeg(open_image(image_file))
    except Exception:
        logger.warning("습득물 #%s 대표 사진을 읽을 수 없음: %s", item.id, item.image_path)
        return None


def _gateway_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AnalyzerConfigError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


async def _gateway_search(*, description, location, occurred_at, image, top_k, category, filters, db):
    """
    게이트웨이 검색 (공통 명세 4절).
    1) 체크 폼 필터 (일치·미확인 규칙과 total_candidates 의미는 로컬 검색과 같음)
    2) 비교 후보 최대 10건
       - 사진 검색: 저장된 사진 임베딩 유사도 상위 → 남은 자리는 명세 순서 (장소 일치 → 시각 근접 → 최신)
       - 자연어 검색: 명세 순서
    3) 검색 비교 어댑터 한 번 → ID 검증 → DB 레코드와 결합, Top-5 이내
    후보가 없으면 AI를 부르지 않고 200과 빈 results.
    """
    started = time.perf_counter()
    timings = {}
    top_k = max(1, min(int(top_k), GATEWAY_TOP_K_MAX))

    try:
        filter_category, form_filters = check_form.parse_filters(category, filters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    query_image = None
    if image is not None and image.filename:
        image_bytes = await image.read()
        if image_bytes:
            try:
                query_image = open_image(io.BytesIO(image_bytes))
                query_image.load()
            except Exception as exc:
                raise HTTPException(status_code=400, detail="invalid search image") from exc

    text = (description or "").strip() or None
    query_location = (location or "").strip() or None
    query_time = parse_optional_datetime(occurred_at)
    kind = "image" if query_image is not None else ("text" if text else "filter_only")

    all_candidates = (
        db.query(models.Item)
        .filter(models.Item.item_type == "found")
        .filter(models.Item.status != STATUS_ANALYSIS_FAILED)
        .all()
    )
    filter_checks = {}
    candidates = []
    for item in all_candidates:
        checked = check_form.match_filters(item, filter_category, form_filters)
        if checked is not None:
            filter_checks[item.id] = checked
            candidates.append(item)

    selected = []  # [(item, source, embedding_score, jpeg)]
    ranked = []    # [{"id", "match_reasons"}]
    if candidates and kind == "image":
        query_vector = None
        has_embeddings = any(
            search_candidates.stored_embedding(item, _embedder.model_id) is not None
            for item in candidates
        )
        if has_embeddings:
            t0 = time.perf_counter()
            try:
                query_vector = await run_in_threadpool(_embedder.embed_images, [query_image])
            except (AnalyzerConfigError, AnalyzerError) as exc:
                raise _gateway_error(exc) from exc
            finally:
                timings["embedding_ms"] = round((time.perf_counter() - t0) * 1000)
            query_vector = query_vector[0]
        if query_vector is not None:
            ordered = search_candidates.image_search_order(
                candidates, query_vector, _embedder.model_id, query_location, query_time
            )
        else:
            ordered = [
                (item, search_candidates.SOURCE_ORDER, None)
                for item in search_candidates.spec_order(candidates, query_location, query_time)
            ]
        selected = search_candidates.take_readable(
            ordered, _load_candidate_jpeg, search_adapter.MAX_CANDIDATES, require_image=True
        )
    elif candidates and kind == "text":
        ordered = [
            (item, search_candidates.SOURCE_ORDER, None)
            for item in search_candidates.spec_order(candidates, query_location, query_time)
        ]
        selected = search_candidates.take_readable(
            ordered, _load_candidate_jpeg, search_adapter.MAX_CANDIDATES, require_image=False
        )
    elif candidates:  # 사진·설명 없이 필터만: AI를 부르지 않고 명세 순서
        ranked = [
            {"id": item.id, "match_reasons": []}
            for item in search_candidates.spec_order(candidates, query_location, query_time)[:top_k]
        ]

    if selected:
        query = search_adapter.SearchQuery(
            kind=kind,
            text=text,
            image_jpeg=search_adapter.to_jpeg(query_image) if query_image is not None else None,
            location=query_location,
            occurred_at=query_time.isoformat(timespec="minutes") if query_time else None,
        )
        compare_candidates = [
            search_adapter.SearchCandidate(
                id=item.id,
                category=item.category,
                description=item.description,
                form_values=check_form.item_form_values(item),
                location=item.location,
                occurred_at=item.occurred_at.isoformat(timespec="minutes") if item.occurred_at else None,
                image_jpeg=jpeg,
            )
            for item, _source, _score, jpeg in selected
        ]
        t0 = time.perf_counter()
        try:
            ranked = await run_in_threadpool(
                search_adapter.compare, SEARCH_ANALYZER_MODE, query, compare_candidates
            )
        except (AnalyzerConfigError, AnalyzerError) as exc:
            raise _gateway_error(exc) from exc
        finally:
            timings["compare_ms"] = round((time.perf_counter() - t0) * 1000)

    by_id = {item.id: item for item in candidates}
    source_by_id = {item.id: source for item, source, _score, _jpeg in selected}
    results = []
    for rank, row in enumerate(ranked[:top_k], start=1):
        item = by_id[row["id"]]
        results.append({
            **serialize_item(item),
            **{field: None for field in LEGACY_SCORE_FIELDS},
            "rank": rank,
            "match_reasons": row["match_reasons"],
            "filter_check": filter_checks.get(item.id, {}),
            "selection_source": source_by_id.get(item.id, search_candidates.SOURCE_ORDER),
        })

    timings["total_ms"] = round((time.perf_counter() - started) * 1000)
    return {
        "query_description": description,
        "query_location": query_location,
        "query_occurred_at": occurred_at,
        "search_kind": kind,
        "search_analyzer_mode": SEARCH_ANALYZER_MODE,
        "embedding_model": _embedder.model_id if kind == "image" else None,
        "applied_filters": {
            **({"category": filter_category} if filter_category else {}),
            **{fld.key: fld.choice_from_column(value) or value for fld, value in form_filters},
        },
        "total_found_items": len(all_candidates),
        "total_candidates": len(candidates),
        "evaluated_count": len(selected),
        "selection": {
            "by_embedding": sum(1 for _i, s, _sc, _j in selected if s == search_candidates.SOURCE_EMBEDDING),
            "by_order": sum(1 for _i, s, _sc, _j in selected if s == search_candidates.SOURCE_ORDER),
        },
        "timings": timings,
        "results": results,
    }


async def _local_search(
    *, description, location, occurred_at, image, top_k, category, filters, db,
):
    """
    (FINDYU_SEARCH_ANALYZER_MODE=local) 기존 로컬 모델 검색.
    AI 브랜치의 핵심 검색 구조를 demo FastAPI/SQLite에 통합.

    체크 폼 필터: 분실자가 체크한 항목(category, filters)과 값이 다른 습득물은 후보에서 뺀다.
    습득물 쪽 값이 비어 있으면(모름) 빼지 않고 filter_check에 "미확인"으로 표시한다.
    순위는 남은 후보를 아래 점수로 매긴다.

    - Image -> Image: DINOv2
    - Text -> Image: SigLIP2
    - Location/Time: metadata score
    - Orchestration: LangGraph
    - Ranking weights: AI branch 0.45 / 0.25 / 0.20 / 0.10
    """
    top_k = max(1, min(int(top_k), 20))

    try:
        filter_category, form_filters = check_form.parse_filters(category, filters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    query_image_embedding = None
    if image is not None and image.filename:
        image_bytes = await image.read()
        if image_bytes:
            try:
                query_image = open_image(io.BytesIO(image_bytes))
                query_image_embedding = get_embedding(query_image)
            except Exception as exc:
                raise HTTPException(status_code=400, detail="invalid search image") from exc

    parsed_query = {
        "text": description,
        "location": None,
        "time": None,
    }

    if description:
        try:
            parsed_query = _query_parser.parse(description)
        except Exception:
            # 중간 데모에서는 Query LLM 실패가 전체 검색 실패로 이어지지 않게
            # 원문 description으로 안전하게 fallback한다.
            logger.exception("Query LLM parsing 실패 - 원문으로 fallback")
            parsed_query = {
                "text": description,
                "location": None,
                "time": None,
            }

    retrieval_text = parsed_query.get("text") or description
    effective_location = location or parsed_query.get("location")

    try:
        query_text_embedding = (
            get_text_embedding(retrieval_text)
            if retrieval_text
            else None
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"SigLIP2 text embedding failed: {exc}",
        ) from exc

    # UI에서 datetime-local로 받은 값은 우선 사용한다.
    # Query LLM의 자연어 time은 현재 prototype에서 임의 날짜로 해석하지 않는다.
    query_time = parse_optional_datetime(occurred_at)

    all_candidates = (
        db.query(models.Item)
        .filter(models.Item.item_type == "found")
        .filter(models.Item.status != STATUS_ANALYSIS_FAILED)
        .all()
    )
    filter_checks = {}
    candidates = []
    for item in all_candidates:
        checked = check_form.match_filters(item, filter_category, form_filters)
        if checked is not None:
            filter_checks[item.id] = checked
            candidates.append(item)

    def serialize_with_filters(item):
        return {**serialize_item(item), "filter_check": filter_checks.get(item.id, {})}

    def candidate_image_score(item, query_vector):
        candidate_vector = item_embedding(item)
        return cosine_score(query_vector, candidate_vector)

    def candidate_text_score(item, query_vector):
        candidate_vector = get_siglip_image_embedding(item)
        return cosine_score(query_vector, candidate_vector)

    graph_result = run_search_graph(
        candidates=candidates,
        query_image_embedding=query_image_embedding,
        query_text_embedding=query_text_embedding,
        get_candidate_image_embedding=candidate_image_score,
        get_candidate_text_image_embedding=candidate_text_score,
        location_score_fn=location_similarity,
        time_score_fn=time_similarity,
        serialize_fn=serialize_with_filters,
        query_location=effective_location,
        query_time=query_time,
        top_k=top_k,
        weights={
            "image": 0.45,
            "text": 0.25,
            "location": 0.20,
            "time": 0.10,
        },
    )

    return {
        "query_description": description,
        "parsed_query": parsed_query,
        "query_location": effective_location,
        "query_occurred_at": occurred_at,
        "scoring_mode": "dinov2+siglip2+metadata+langgraph",
        "image_model": MODEL_NAME,
        "text_image_model": TEXT_IMAGE_MODEL_NAME,
        "applied_filters": {
            **({"category": filter_category} if filter_category else {}),
            **{fld.key: fld.choice_from_column(value) or value for fld, value in form_filters},
        },
        "total_found_items": len(all_candidates),
        "total_candidates": len(candidates),
        "results": graph_result.get("results", []) if candidates else [],
    }
