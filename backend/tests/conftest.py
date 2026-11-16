import sys
from pathlib import Path

# backend/ 모듈(paths, labels, migrations ...)을 바로 import할 수 있게 한다
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
