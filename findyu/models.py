from PIL import Image

import torch
import torch.nn.functional as F

from transformers import (
    AutoImageProcessor,
    AutoProcessor,
    AutoModel,
)


class ModelManager:
    """
    FindYU retrieval 모델 관리 객체.

    현재 역할:
    - DINO 계열: Image -> Image retrieval embedding
    - SigLIP 계열: Image/Text embedding

    중요한 점:
    모델 이름을 코드에 하드코딩하지 않는다.
    모든 모델 이름은 FindYUConfig에서 전달받는다.
    """

    def __init__(self, config):
        self.cfg = config

        self.dino_processor = None
        self.dino_model = None

        self.siglip_processor = None
        self.siglip_model = None

    def load(self):
        """
        retrieval에 필요한 모델을 lazy-load한다.

        이미 로드된 모델은 다시 로드하지 않기 때문에
        여러 객체에서 embedding을 요청해도 중복 메모리 사용을 피한다.
        """

        if self.dino_model is None:
            print(
                "[LOAD] Image encoder:",
                self.cfg.image_encoder_model_name,
            )

            self.dino_processor = (
                AutoImageProcessor
                .from_pretrained(
                    self.cfg.image_encoder_model_name
                )
            )

            self.dino_model = (
                AutoModel
                .from_pretrained(
                    self.cfg.image_encoder_model_name,
                    torch_dtype=self.cfg.dtype,
                )
                .to(self.cfg.device)
                .eval()
            )

        if self.siglip_model is None:
            print(
                "[LOAD] Text-Image encoder:",
                self.cfg.text_image_encoder_model_name,
            )

            self.siglip_processor = (
                AutoProcessor
                .from_pretrained(
                    self.cfg.text_image_encoder_model_name
                )
            )

            self.siglip_model = (
                AutoModel
                .from_pretrained(
                    self.cfg.text_image_encoder_model_name,
                    torch_dtype=self.cfg.dtype,
                )
                .to(self.cfg.device)
                .eval()
            )

    @torch.no_grad()
    def dino_image(self, image_path):
        """
        Image -> normalized image embedding.

        현재 default는 DINOv2-small.

        embedding을 L2 normalize하고,
        FAISS IndexFlatIP를 사용하므로
        Inner Product가 cosine similarity로 동작한다.
        """
        self.load()

        image = Image.open(
            image_path
        ).convert("RGB")

        inputs = self.dino_processor(
            images=image,
            return_tensors="pt",
        )

        inputs = {
            k: v.to(self.cfg.device)
            for k, v
            in inputs.items()
        }

        outputs = self.dino_model(
            **inputs
        )

        # DINO 계열에서는 첫 token(CLS)의 hidden state를
        # 이미지 전체 representation으로 사용.
        embedding = (
            outputs
            .last_hidden_state[:, 0, :]
        )

        embedding = F.normalize(
            embedding.float(),
            dim=-1,
        )

        return (
            embedding
            .cpu()
            .numpy()
            .astype("float32")
        )

    @torch.no_grad()
    def siglip_image(self, image_path):
        """
        Image -> normalized SigLIP image embedding.
        """
        self.load()

        image = Image.open(
            image_path
        ).convert("RGB")

        inputs = self.siglip_processor(
            images=image,
            return_tensors="pt",
        )

        inputs = {
            k: v.to(self.cfg.device)
            for k, v
            in inputs.items()
        }

        embedding = (
            self.siglip_model
            .get_image_features(**inputs)
        )

        if hasattr(
            embedding,
            "pooler_output",
        ):
            embedding = (
                embedding.pooler_output
            )

        embedding = F.normalize(
            embedding.float(),
            dim=-1,
        )

        return (
            embedding
            .cpu()
            .numpy()
            .astype("float32")
        )

    @torch.no_grad()
    def siglip_text(self, text):
        """
        Text -> normalized SigLIP text embedding.

        이미지 DB는 SigLIP image embedding,
        검색 문장은 SigLIP text embedding을 사용하므로
        같은 multimodal space에서 cosine similarity를 계산할 수 있다.
        """
        self.load()

        inputs = self.siglip_processor(
            text=[text],
            padding="max_length",
            return_tensors="pt",
        )

        inputs = {
            k: v.to(self.cfg.device)
            for k, v
            in inputs.items()
        }

        embedding = (
            self.siglip_model
            .get_text_features(**inputs)
        )

        if hasattr(
            embedding,
            "pooler_output",
        ):
            embedding = (
                embedding.pooler_output
            )

        embedding = F.normalize(
            embedding.float(),
            dim=-1,
        )

        return (
            embedding
            .cpu()
            .numpy()
            .astype("float32")
        )
