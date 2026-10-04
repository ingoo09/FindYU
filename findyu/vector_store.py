import numpy as np
import faiss


class VectorStore:
    """
    DINO / SigLIP FAISS index 관리.

    현재 prototype에서는 등록 후 전체 DB를 rebuild한다.
    실제 서비스에서는 incremental add로 변경 가능하다.
    """

    IMAGE_EXTS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }

    def __init__(
        self,
        paths,
        models,
        config,
    ):
        self.paths = paths
        self.models = models
        self.cfg = config

        self.dino_index = None
        self.siglip_index = None

        self.item_ids = []

    def _image_paths(self):
        return sorted(
            p
            for p in self.paths.db_dir.iterdir()
            if (
                p.is_file()
                and p.suffix.lower()
                in self.IMAGE_EXTS
            )
        )

    def build(self):
        paths = self._image_paths()

        if not paths:
            self.dino_index = None
            self.siglip_index = None
            self.item_ids = []

            print(
                "[VectorStore] DB image 없음"
            )
            return

        dino_vectors = []
        siglip_vectors = []
        item_ids = []

        for path in paths:
            item_ids.append(
                path.stem
            )

            dino_vectors.append(
                self.models
                .dino_image(str(path))[0]
            )

            siglip_vectors.append(
                self.models
                .siglip_image(str(path))[0]
            )

        dino_matrix = np.asarray(
            dino_vectors,
            dtype="float32",
        )

        siglip_matrix = np.asarray(
            siglip_vectors,
            dtype="float32",
        )

        self.dino_index = (
            faiss.IndexFlatIP(
                dino_matrix.shape[1]
            )
        )

        self.siglip_index = (
            faiss.IndexFlatIP(
                siglip_matrix.shape[1]
            )
        )

        self.dino_index.add(
            dino_matrix
        )

        self.siglip_index.add(
            siglip_matrix
        )

        self.item_ids = item_ids

        print(
            "[VectorStore] indexed:",
            len(item_ids),
        )

    def search_image(
        self,
        image_path,
    ):
        if (
            not image_path
            or self.dino_index is None
        ):
            return {}

        query = (
            self.models
            .dino_image(image_path)
        )

        k = min(
            self.cfg.retrieval_k,
            self.dino_index.ntotal,
        )

        scores, indices = (
            self.dino_index.search(
                query,
                k,
            )
        )

        return {
            self.item_ids[idx]:
                float(score)

            for score, idx
            in zip(
                scores[0],
                indices[0],
            )

            if idx >= 0
        }

    def search_text(
        self,
        text,
    ):
        if (
            not text
            or self.siglip_index is None
        ):
            return {}

        query = (
            self.models
            .siglip_text(text)
        )

        k = min(
            self.cfg.retrieval_k,
            self.siglip_index.ntotal,
        )

        scores, indices = (
            self.siglip_index.search(
                query,
                k,
            )
        )

        return {
            self.item_ids[idx]:
                float(score)

            for score, idx
            in zip(
                scores[0],
                indices[0],
            )

            if idx >= 0
        }
