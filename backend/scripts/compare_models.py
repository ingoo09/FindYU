"""
/items/analyze 모델 비교 스크립트.

사용법 (backend/에서, --reload 없이 띄운 서버 대상):
  FINDYU_GEMINI_MODEL=<모델> .venv/bin/uvicorn main:app --port 8821
  .venv/bin/python scripts/compare_models.py 8821 <모델> ../test_photos out.json --repeat 3

- 조합마다 --repeat번 반복한다 (기본 1).
- 504가 나면 사진을 긴 변 1024px로 줄여(EXIF 회전 반영) 한 번 재시도하고 resized_retry=True로 기록한다.
  참고: 서버도 Gemini로 보내기 전에 항상 1024px로 줄이므로, 재시도는 업로드 크기만 줄어든다.
- 할당량 초과(429)가 나면 즉시 멈추고, 그때까지의 결과와 중단 위치를 out.json에 남긴다 (종료 코드 2).
- --resume <기존 결과 json>: 기존 결과에서 성공(200)한 (회차, 조합)은 그대로 가져오고 실패·미측정분만 돈다.
  가져온 결과에는 source(기존 파일명, 측정 경로)를 남긴다. 서버 기록이 없는 옛 파일은 gemini 직접 호출로 본다.
- 한 바퀴를 돈 뒤 503/504 등 일시적 오류로 실패한 (회차, 조합)은 --retry-failed번(기본 1)까지 다시 돌려
  조합당 --repeat회를 채운다. 429는 재시도하지 않고 멈춘다.
"""
import argparse
import io
import json
import time
from pathlib import Path

import httpx
from PIL import Image, ImageOps

COMBOS = [
    ("iPhone 15 Pro", "후면만", ["15pro_back.jpeg"]),
    ("iPhone 15 Pro", "후면+전면", ["15pro_back.jpeg", "15pro_front.jpeg"]),
    ("iPhone 15 Pro", "후면+측면(side2)", ["15pro_back.jpeg", "15pro_side2.jpeg"]),
    ("iPhone 15 Pro", "5장 전체", ["15pro_back.jpeg", "15pro_back_hand.jpeg", "15pro_front.jpeg", "15pro_side1.jpeg", "15pro_side2.jpeg"]),
    ("iPhone 12", "후면만", ["iphone12_back.jpeg"]),
    ("iPhone 12", "후면+전면", ["iphone12_back.jpeg", "iphone12_front.jpeg"]),
]


def file_bytes(photos_dir, name, resize):
    path = photos_dir / name
    if not resize:
        return path.read_bytes()
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")  # 회전 반영 후 축소 (EXIF가 사라지므로)
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
        return buf.getvalue()


def call(port, photos_dir, names, resize):
    files = [("image", (names[0], file_bytes(photos_dir, names[0], resize), "image/jpeg"))]
    files += [
        ("extra_images", (n, file_bytes(photos_dir, n, resize), "image/jpeg")) for n in names[1:]
    ]
    start = time.time()
    resp = httpx.post(f"http://127.0.0.1:{port}/items/analyze", files=files, timeout=900)
    return resp.status_code, resp.json(), round(time.time() - start, 1)


def is_quota_error(status, body):
    return status == 502 and "429" in str(body.get("detail", ""))


def is_timeout_error(status, body):
    return status == 502 and "504" in str(body.get("detail", ""))


def result_key(result):
    return (result["run"], result["truth"], result["combo"])


def load_resume(path):
    """기존 결과 중 성공(200)한 것만 {(회차, 정답, 조합): 결과}로 돌려준다."""
    previous = json.loads(path.read_text(encoding="utf-8"))
    kept = {}
    for result in previous.get("results", []):
        if result.get("status") == 200:
            source = result.get("source") or {
                "file": path.name,
                "server": previous.get("server") or {"registration_analyzer_mode": "gemini"},
            }
            kept[result_key(result)] = {**result, "source": source}
    return previous, kept


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("port")
    parser.add_argument("label")
    parser.add_argument("photos_dir", type=Path)
    parser.add_argument("out_path", type=Path)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--resume", type=Path, help="이어서 측정할 기존 결과 json")
    parser.add_argument("--retry-failed", type=int, default=1, help="일시적 오류 실패분 재시도 바퀴 수")
    args = parser.parse_args()

    output = {"model": args.label, "repeat": args.repeat, "stopped": None, "results": []}
    # 어떤 경로(gemini 직접 / baze 게이트웨이)로 측정했는지 남긴다
    health = httpx.get(f"http://127.0.0.1:{args.port}/", timeout=30).json()
    mode = health.get("registration_analyzer_mode")
    output["server"] = {
        "registration_analyzer_mode": mode,
        "analyzer": health.get(f"registration_{mode}"),
    }
    done = {}
    if args.resume:
        previous, done = load_resume(args.resume)
        if previous.get("model") != args.label:
            print(f"warning: 기존 결과 모델({previous.get('model')})과 label({args.label})이 다름", flush=True)
        output["resumed_from"] = args.resume.name
        print(f"resume: 기존 성공 {len(done)}건 재사용", flush=True)

    order = {
        (run, truth, combo): i
        for i, (run, (truth, combo, _)) in enumerate(
            (run, c) for run in range(1, args.repeat + 1) for c in COMBOS
        )
    }

    def save():
        output["results"] = sorted(done.values(), key=lambda r: order.get(result_key(r), 1 << 30))
        args.out_path.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")

    def pending():
        return [
            (run, truth, combo, names)
            for run in range(1, args.repeat + 1)
            for truth, combo, names in COMBOS
            if done.get((run, truth, combo), {}).get("status") != 200
        ]

    for pass_no in range(0, args.retry_failed + 1):
        todo = pending()
        if not todo:
            break
        if pass_no:
            print(f"retry pass {pass_no}: 실패 {len(todo)}건 재측정", flush=True)
        for run, truth, combo, names in todo:
            attempts = []
            status, body, elapsed = call(args.port, args.photos_dir, names, resize=False)
            attempts.append({"resized": False, "status": status, "elapsed": elapsed})
            resized = False
            if is_timeout_error(status, body):
                resized = True
                status, body, elapsed = call(args.port, args.photos_dir, names, resize=True)
                attempts.append({"resized": True, "status": status, "elapsed": elapsed})

            previous_failures = done.get((run, truth, combo), {}).get("failed_attempts", [])
            if (run, truth, combo) in done:
                old = done[(run, truth, combo)]
                previous_failures = previous_failures + [{"status": old["status"], "body": old["body"], "attempts": old["attempts"]}]
            done[(run, truth, combo)] = {
                "run": run, "truth": truth, "combo": combo, "photos": names,
                "resized_retry": resized, "attempts": attempts, "status": status, "body": body,
                **({"failed_attempts": previous_failures} if previous_failures else {}),
            }
            summary = (
                (body.get("device_model"), body.get("identification_level"), body.get("generation_evidence"))
                if status == 200
                else body.get("detail", "")[:120]
            )
            print(f"run {run} | {truth} | {combo} | {status} | {summary} | {attempts}", flush=True)
            save()

            if is_quota_error(status, body):
                output["stopped"] = {"run": run, "truth": truth, "combo": combo, "reason": "429 할당량 초과"}
                save()
                print("STOPPED: quota exceeded at", output["stopped"], flush=True)
                raise SystemExit(2)

    print("DONE", args.label, flush=True)


if __name__ == "__main__":
    main()
