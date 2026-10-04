"""
AI 브랜치(findyu/query_parser.py)를 FastAPI 데모에 맞게 이식한 Query Parser.

query_parser_mode:
- "mock": 입력 문장을 그대로 retrieval text로 사용
- "llm": Qwen LLM으로 text/location/time 구조화
"""

import json
import re
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class QueryParser:
    def __init__(
        self,
        *,
        mode="llm",
        model_name="Qwen/Qwen3-0.6B",
        prompt_path=None,
    ):
        self.mode = mode
        self.model_name = model_name
        self.prompt_path = Path(prompt_path) if prompt_path else None
        self.system_prompt = self._load_prompt()

        self.tokenizer = None
        self.model = None

    def _load_prompt(self):
        if self.prompt_path and self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8").strip()

        return (
            "Convert the user's lost-item description into JSON only with exactly "
            "these keys: text, location, time. "
            "text must contain only visually/product-relevant details for retrieval. "
            "location and time must be null when not explicitly supported. "
            "Do not invent information. No markdown."
        )

    def _load_llm(self):
        if self.model is not None:
            return

        print("[LOAD] Query LLM:", self.model_name)

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)

        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        self.model = (
            AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=dtype,
                device_map="auto",
            )
            .eval()
        )

    @staticmethod
    def _extract_json(text):
        text = re.sub(r"```(?:json)?|```", "", text or "").strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("Query LLM JSON parse 실패: " + text[:300])

        data = json.loads(match.group(0))
        return {
            "text": data.get("text"),
            "location": data.get("location"),
            "time": data.get("time"),
        }

    def parse(self, query):
        query = (query or "").strip()

        if not query:
            return {
                "text": None,
                "location": None,
                "time": None,
            }

        if self.mode == "mock":
            return {
                "text": query,
                "location": None,
                "time": None,
            }

        if self.mode != "llm":
            raise ValueError(
                f"지원하지 않는 query_parser_mode: {self.mode!r} "
                "(mock 또는 llm 사용)"
            )

        self._load_llm()

        messages = [
            {
                "role": "system",
                "content": self.system_prompt,
            },
            {
                "role": "user",
                "content": query,
            },
        ]

        kwargs = dict(
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        )

        try:
            inputs = self.tokenizer.apply_chat_template(
                messages,
                enable_thinking=False,
                **kwargs,
            )
        except TypeError:
            inputs = self.tokenizer.apply_chat_template(
                messages,
                **kwargs,
            )

        inputs = {
            key: value.to(self.model.device)
            for key, value in inputs.items()
        }

        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=160,
                do_sample=False,
            )

        generated = output[
            0,
            inputs["input_ids"].shape[-1]:,
        ]

        raw = self.tokenizer.decode(
            generated,
            skip_special_tokens=True,
        )

        return self._extract_json(raw)
