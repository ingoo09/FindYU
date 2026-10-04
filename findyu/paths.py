from pathlib import Path


class ProjectPaths:
    """프로젝트에서 사용하는 모든 경로를 관리한다."""

    def __init__(self, config):
        self.root = Path(config.root)

        self.db_dir = self.root / "data" / "database"
        self.query_dir = self.root / "data" / "query"
        self.upload_dir = self.root / "data" / "uploads"

        self.metadata_path = self.root / "data" / "metadata.csv"

        for path in [
            self.db_dir,
            self.query_dir,
            self.upload_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)
