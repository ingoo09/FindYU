"""
DB 테이블(모델) 정의.
분실물/습득물을 같은 테이블에 저장하고, item_type으로 구분함.
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from database import Base


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)

    # "lost"(분실물) 또는 "found"(습득물)
    item_type = Column(String, nullable=False)

    # AI가 사진 보고 추정하거나, 사용자가 자연어로 입력한 정보
    category = Column(String, nullable=True)       # 종류 (예: 이어폰 케이스)
    color = Column(String, nullable=True)           # 색상
    brand = Column(String, nullable=True)           # 브랜드
    description = Column(Text, nullable=True)       # 자유 설명 텍스트

    # 이미지
    image_path = Column(String, nullable=True)      # 서버에 저장된 이미지 경로
    embedding = Column(Text, nullable=True)          # 임베딩 벡터 (JSON 문자열로 저장)

    # 위치·시간
    location = Column(String, nullable=True)
    occurred_at = Column(DateTime, nullable=True)    # 분실/습득 발생 시각

    # 등록 상태
    status = Column(String, default="registered")    # registered, matched 등

    created_at = Column(DateTime, server_default=func.now())
