"""
FindYU 백엔드 - 1주차 스프린트용 최소 서버
실행: uvicorn main:app --reload
브라우저에서 http://localhost:8000/docs 열면 자동으로 API 테스트 화면이 뜸
"""

from fastapi import FastAPI, UploadFile, File
from PIL import Image
import io

app = FastAPI(title="FindYU Backend - Sprint 1")


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
