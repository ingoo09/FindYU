# FindYU Frontend - Midterm Demo

중간발표용 통합 데모 프론트엔드입니다.

## 실행

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

첫 실행 시 `facebook/dinov2-small` 모델 가중치를 내려받을 수 있습니다.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

브라우저: http://localhost:5173

## API 연동

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
- 텍스트: 중간발표용 문자열/토큰 기반 점수
- 위치: 문자열 유사도
- 시간: 시간 차이 기반 점수

텍스트 부분은 이후 SigLIP/CLIP 계열 멀티모달 embedding으로 교체할 수 있습니다.
