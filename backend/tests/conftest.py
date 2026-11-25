import os
import sys
import tempfile
from pathlib import Path

# backend/ 모듈(paths, labels, migrations ...)을 바로 import할 수 있게 한다
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 테스트는 실제 backend/findyu.db와 uploads/를 건드리지 않는다.
# database·paths·main을 import하기 전에(= 이 파일에서) 임시 경로와 mock 모드를 정한다.
_TMP = Path(tempfile.mkdtemp(prefix="findyu-test-"))
os.environ["FINDYU_DB_PATH"] = str(_TMP / "findyu.db")
os.environ["FINDYU_UPLOAD_DIR"] = str(_TMP / "uploads")
(_TMP / "uploads").mkdir()
# 실제 AI·게이트웨이를 부르지 않도록 (main.py가 .env를 읽어도 이미 설정된 값이 우선)
os.environ["FINDYU_REGISTRATION_ANALYZER_MODE"] = "mock"
os.environ["FINDYU_SEARCH_ANALYZER_MODE"] = "mock"
os.environ["FINDYU_QUERY_PARSER_MODE"] = "mock"
