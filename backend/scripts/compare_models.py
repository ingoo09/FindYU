"""
/items/analyze 모델 비교 스크립트.
사용법 (backend/에서, --reload 없이 띄운 서버 대상):
  FINDYU_GEMINI_MODEL=<모델> .venv/bin/uvicorn main:app --port 8821
  .venv/bin/python scripts/compare_models.py 8821 <모델> ../test_photos out.json

504가 나면 사진을 긴 변 1024px로 줄여(EXIF 회전 반영) 한 번 재시도하고 resized_retry=True로 기록한다.
참고: 서버도 Gemini로 보내기 전에 항상 1024px로 줄이므로, 재시도는 업로드 크기만 줄어든다.
"""
import io
import json
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageOps

port, label, photos_dir, out_path = sys.argv[1], sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])

COMBOS = [
    ("iPhone 15 Pro", "후면만", ["15pro_back.jpeg"]),
    ("iPhone 15 Pro", "후면+전면", ["15pro_back.jpeg", "15pro_front.jpeg"]),
    ("iPhone 15 Pro", "후면+측면(side2)", ["15pro_back.jpeg", "15pro_side2.jpeg"]),
    ("iPhone 15 Pro", "5장 전체", ["15pro_back.jpeg", "15pro_back_hand.jpeg", "15pro_front.jpeg", "15pro_side1.jpeg", "15pro_side2.jpeg"]),
    ("iPhone 12", "후면만", ["iphone12_back.jpeg"]),
    ("iPhone 12", "후면+전면", ["iphone12_back.jpeg", "iphone12_front.jpeg"]),
]


def file_bytes(name, resize):
    path = photos_dir / name
    if not resize:
        return path.read_bytes()
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")  # 회전 반영 후 축소 (EXIF가 사라지므로)
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
        return buf.getvalue()


def call(names, resize):
    files = [("image", (names[0], file_bytes(names[0], resize), "image/jpeg"))]
    files += [("extra_images", (n, file_bytes(n, resize), "image/jpeg")) for n in names[1:]]
    start = time.time()
    resp = httpx.post(f"http://127.0.0.1:{port}/items/analyze", files=files, timeout=900)
    return resp.status_code, resp.json(), round(time.time() - start, 1)


results = []
for truth, combo, names in COMBOS:
    attempts = []
    status, body, elapsed = call(names, resize=False)
    attempts.append({"resized": False, "status": status, "elapsed": elapsed})
    resized = False
    if status == 502 and "504" in str(body.get("detail", "")):
        resized = True
        status, body, elapsed = call(names, resize=True)
        attempts.append({"resized": True, "status": status, "elapsed": elapsed})
    row = {"model": label, "truth": truth, "combo": combo, "photos": names,
           "resized_retry": resized, "attempts": attempts, "status": status, "body": body}
    results.append(row)
    print(label, truth, combo, status, body.get("device_model") if status == 200 else body.get("detail", "")[:120], attempts, flush=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

print("DONE", label, flush=True)
