"""
DB 테이블(모델) 정의.
분실물/습득물을 같은 테이블에 저장하고, item_type으로 구분함.
"""

from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, Text
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

    # 휴대폰·지갑 전용 필드 (허용값은 labels.py 참고)
    # 새 컬럼을 추가하면 migrations.py에 컬럼 추가 단계도 새로 만들어야 기존 DB에 반영됨
    device_model = Column(String, nullable=True)             # 기종 (예: 아이폰 15 Pro)
    device_model_candidates = Column(Text, nullable=True)    # 기종 대안 후보 (JSON 배열)
    identification_level = Column(String, nullable=True)     # 확인 / 추정 / 미확인
    has_case = Column(Boolean, nullable=True)                # 케이스 유무 (NULL=판단 불가)
    wallet_type = Column(String, nullable=True)              # 장지갑 / 반지갑 / 카드지갑
    material = Column(String, nullable=True)                 # 소재
    verification_needed = Column(Text, nullable=True)        # 추가 확인 필요 사항 (JSON 배열)
    manufacturer = Column(String, nullable=True)             # 제조사 (brand와 다를 수 있음)

    # AI 확신도 (높음 0.9 / 보통 0.6 / 낮음 0.3). AI가 채운 값에만 저장, 사람이 입력한 값은 NULL
    category_confidence = Column(Float, nullable=True)
    manufacturer_confidence = Column(Float, nullable=True)
    device_model_confidence = Column(Float, nullable=True)
    color_confidence = Column(Float, nullable=True)

    # 이미지
    image_path = Column(String, nullable=True)      # 서버에 저장된 이미지 경로
    embedding = Column(Text, nullable=True)          # 임베딩 벡터 (JSON 문자열로 저장)

    # 위치·시간
    location = Column(String, nullable=True)
    occurred_at = Column(DateTime, nullable=True)    # 분실/습득 발생 시각

    # 등록 상태
    status = Column(String, default="registered")    # registered, matched 등

    created_at = Column(DateTime, server_default=func.now())
