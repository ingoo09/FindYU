# FindYU Frontend - Midterm Demo

중간발표용 통합 데모 프론트엔드입니다.

## 실행

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

첫 이미지 검색/등록 시 `facebook/dinov2-small`, 첫 자동 정보 추출 시 `HuggingFaceTB/SmolVLM-500M-Instruct` 모델 가중치를 내려받을 수 있습니다.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

브라우저: http://localhost:5173

## API 연동

### POST /items/analyze

습득물 사진을 먼저 Vision-Language 모델로 분석합니다.

- 입력: `image`
- 출력: `category`, `color`, `brand`, `features`
- 모델: `HuggingFaceTB/SmolVLM-500M-Instruct`
- 프론트엔드는 분석 결과를 등록 입력란에 자동 채우며 사용자가 수정할 수 있습니다.

### POST /items

프론트엔드는 `multipart/form-data`로 다음 필드를 전송합니다.

- `item_type=found`
- `image`
- `category`
- `color`
- `brand`
- `description`
- `location`
- `occurred_at`

### POST /search

- `image` (선택)
- `description` (선택)
- `location` (선택)
- `occurred_at` (선택)
- `top_k=5`

검색 응답의 `results[].image_url`은 Backend의 `/uploads` 정적 파일 경로를 사용하며,
Vite 개발 서버가 해당 경로를 Backend로 proxy하므로 Top-5 후보 이미지가 카드에 표시됩니다.

## 현재 검색 점수

- 이미지: DINOv2 (`facebook/dinov2-small`) embedding cosine similarity
- 텍스트→이미지: SigLIP2 (`google/siglip2-base-patch16-224`) embedding cosine similarity
- 위치: 문자열 유사도
- 시간: 시간 차이 기반 점수

검색 흐름은 AI 브랜치의 DINOv2 + SigLIP2 + metadata 가중 랭킹 구조를 LangGraph로 연결합니다.
