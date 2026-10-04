import json
import re

import torch
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
)


class QueryParser:
    """
    검색 문장 -> structured query.

    mode:
    - mock: LLM 없이 바로 테스트
    - llm : Qwen 등 실제 LLM 사용

    시스템 프롬프트는 Python 코드가 아니라
    prompts/query_parser_system.txt 에서 읽는다.
    """

    def __init__(
        self,
        config,
        prompt_loader,
    ):
        self.cfg = config

        self.system_prompt = (
            prompt_loader.load(
                "query_parser_system.txt"
            )
        )

        self.tokenizer = None
        self.model = None

    def _load_llm(self):
        if self.model is not None:
            return

        print(
            "[LOAD] Query LLM:",
            self.cfg.query_llm_model_name,
        )

        self.tokenizer = (
            AutoTokenizer.from_pretrained(
                self.cfg.query_llm_model_name
            )
        )

        self.model = (
            AutoModelForCausalLM
            .from_pretrained(
                self.cfg.query_llm_model_name,
                torch_dtype=
                    self.cfg.dtype,
                device_map="auto",
            )
            .eval()
        )

    @staticmethod
    def _extract_json(text):
        text = re.sub(
            r"```(?:json)?|```",
            "",
            text,
        ).strip()

        match = re.search(
            r"\{.*\}",
            text,
            re.DOTALL,
        )

        if not match:
            raise ValueError(
                "JSON parse 실패:\n"
                + text
            )

        return json.loads(
            match.group(0)
        )

    def parse(self, query):
        # -----------------------------
        # 초경량 로직 테스트
        # -----------------------------
        if (
            self.cfg
            .query_parser_mode
            == "mock"
        ):
            return {
                "text": query,
                "location": None,
                "time": None,
            }

        # -----------------------------
        # 실제 LLM parser
        # -----------------------------
        self._load_llm()

        messages = [
            {
                "role": "system",
                "content":
                    self.system_prompt,
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
            inputs = (
                self.tokenizer
                .apply_chat_template(
                    messages,
                    enable_thinking=False,
                    **kwargs,
                )
            )
        except TypeError:
            inputs = (
                self.tokenizer
                .apply_chat_template(
                    messages,
                    **kwargs,
                )
            )

        inputs = {
            k: v.to(
                self.model.device
            )
            for k, v
            in inputs.items()
        }

        with torch.no_grad():
            output = (
                self.model.generate(
                    **inputs,
                    max_new_tokens=160,
                    do_sample=False,
                )
            )

        generated = output[
            0,
            inputs["input_ids"]
            .shape[-1]:
        ]

        raw = (
            self.tokenizer.decode(
                generated,
                skip_special_tokens=True,
            )
        )

        return (
            self._extract_json(
                raw
            )
        )
