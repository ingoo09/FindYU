from pathlib import Path


class PromptLoader:
    """
    prompts/*.txt 파일을 읽는 객체.

    LLM prompt를 Python 코드 안에 직접 넣지 않기 때문에
    prompt 수정과 코드 수정이 분리된다.
    """

    def __init__(self, prompt_dir: str):
        self.prompt_dir = Path(prompt_dir)

    def load(self, filename: str) -> str:
        path = self.prompt_dir / filename

        if not path.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {path}"
            )

        return path.read_text(
            encoding="utf-8"
        ).strip()
