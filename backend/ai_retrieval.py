"""
AI 브랜치(findyu/models.py)의 retrieval 모델 구조를
FastAPI/SQLite 중간 데모에 맞게 이식한 모듈.

- DINOv2: image -> image
- SigLIP2: text/image shared embedding space
- 두 모델은 각각 lazy-load하여 불필요한 동시 메모리 사용을 줄인다.
"""

import threading

import torch
import torch.nn.functional as F
from transformers import AutoImageProcessor, AutoModel, AutoProcessor


class RetrievalModelManager:
    def __init__(
        self,
        image_model_name="facebook/dinov2-small",
        text_image_model_name="google/siglip2-base-patch16-224",
    ):
        self.image_model_name = image_model_name
        self.text_image_model_name = text_image_model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32

        self._dino_processor = None
        self._dino_model = None
        self._siglip_processor = None
        self._siglip_model = None

        self._dino_lock = threading.Lock()
        self._siglip_lock = threading.Lock()

    def _load_dino(self):
        if self._dino_model is None:
            with self._dino_lock:
                if self._dino_model is None:
                    print("[LOAD] Image encoder:", self.image_model_name)
                    self._dino_processor = AutoImageProcessor.from_pretrained(
                        self.image_model_name
                    )
                    self._dino_model = (
                        AutoModel.from_pretrained(
                            self.image_model_name,
                            torch_dtype=self.dtype,
                        )
                        .to(self.device)
                        .eval()
                    )
        return self._dino_processor, self._dino_model

    def _load_siglip(self):
        if self._siglip_model is None:
            with self._siglip_lock:
                if self._siglip_model is None:
                    print("[LOAD] Text-Image encoder:", self.text_image_model_name)
                    self._siglip_processor = AutoProcessor.from_pretrained(
                        self.text_image_model_name
                    )
                    self._siglip_model = (
                        AutoModel.from_pretrained(
                            self.text_image_model_name,
                            torch_dtype=self.dtype,
                        )
                        .to(self.device)
                        .eval()
                    )
        return self._siglip_processor, self._siglip_model

    def dino_dimension(self):
        _, model = self._load_dino()
        return int(model.config.hidden_size)

    @torch.no_grad()
    def dino_image(self, image):
        processor, model = self._load_dino()
        inputs = processor(images=image.convert("RGB"), return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}

        outputs = model(**inputs)
        embedding = outputs.last_hidden_state[:, 0, :]
        embedding = F.normalize(embedding.float(), p=2, dim=-1)
        return embedding.squeeze(0).cpu().tolist()

    @staticmethod
    def _unwrap_feature_output(output):
        if hasattr(output, "pooler_output"):
            return output.pooler_output
        return output

    @torch.no_grad()
    def siglip_image(self, image):
        processor, model = self._load_siglip()
        inputs = processor(images=image.convert("RGB"), return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}

        embedding = self._unwrap_feature_output(
            model.get_image_features(**inputs)
        )
        embedding = F.normalize(embedding.float(), p=2, dim=-1)
        return embedding.squeeze(0).cpu().tolist()

    @torch.no_grad()
    def siglip_text(self, text):
        processor, model = self._load_siglip()
        inputs = processor(
            text=[text],
            padding="max_length",
            return_tensors="pt",
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}

        embedding = self._unwrap_feature_output(
            model.get_text_features(**inputs)
        )
        embedding = F.normalize(embedding.float(), p=2, dim=-1)
        return embedding.squeeze(0).cpu().tolist()


def cosine_similarity_01(vec1, vec2):
    """
    L2-normalized embedding의 cosine을 metadata 점수와 합치기 쉽도록 [0, 1]로 변환.
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    raw = sum(a * b for a, b in zip(vec1, vec2))
    raw = max(-1.0, min(1.0, float(raw)))
    return (raw + 1.0) / 2.0
