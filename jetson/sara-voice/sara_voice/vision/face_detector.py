"""Face detection and recognition using InsightFace buffalo_sc with TensorRT.

Detects faces in camera frames and identifies David using a pre-computed
face embedding. Runs on GPU every N seconds (configurable).
"""

import logging
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class FaceDetector:
    """InsightFace-based face detection and David recognition."""

    def __init__(self, config: dict):
        face_cfg = config.get("vision", {}).get("face_detection", {})
        self._interval = face_cfg.get("interval_seconds", 5)
        self._model_name = face_cfg.get("model", "buffalo_sc")
        self._use_trt = face_cfg.get("tensorrt", True)
        self._confidence_threshold = face_cfg.get("confidence_threshold", 0.5)
        self._david_embedding_path = face_cfg.get("david_embedding_path", "models/david_face.npy")
        self._similarity_threshold = face_cfg.get("similarity_threshold", 0.4)

        self._app = None
        self._david_embedding: np.ndarray | None = None
        self._last_run: float = 0
        self._loaded = False

    def load(self, gpu_lock=None):
        """Load InsightFace model and David's face embedding.

        Args:
            gpu_lock: Optional asyncio.Lock to coordinate GPU access.
        """
        from insightface.app import FaceAnalysis

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if self._use_trt:
            providers = ["TensorrtExecutionProvider"] + providers

        self._app = FaceAnalysis(
            name=self._model_name,
            providers=providers,
        )
        self._app.prepare(ctx_id=0, det_size=(640, 640))
        logger.info("InsightFace model loaded: %s (TRT=%s)", self._model_name, self._use_trt)

        # Load David's face embedding
        embed_path = Path(self._david_embedding_path)
        if embed_path.exists():
            self._david_embedding = np.load(str(embed_path))
            logger.info("David face embedding loaded: shape=%s", self._david_embedding.shape)
        else:
            logger.warning("David face embedding not found at %s — recognition disabled", embed_path)

        self._loaded = True

    def should_run(self) -> bool:
        """Check if enough time has passed for the next detection cycle."""
        return time.monotonic() - self._last_run >= self._interval

    def detect(self, frame: np.ndarray) -> list[dict]:
        """Run face detection on a BGR frame.

        Returns list of detected faces with:
        - bbox: [x1, y1, x2, y2]
        - confidence: float
        - is_david: bool
        - similarity: float (cosine similarity to David's embedding)
        """
        if not self._loaded or self._app is None:
            return []

        self._last_run = time.monotonic()

        try:
            faces = self._app.get(frame)
        except Exception as e:
            logger.error("Face detection failed: %s", e)
            return []

        results = []
        for face in faces:
            if face.det_score < self._confidence_threshold:
                continue

            result = {
                "bbox": face.bbox.tolist(),
                "confidence": float(face.det_score),
                "is_david": False,
                "similarity": 0.0,
            }

            # Check if this is David
            if self._david_embedding is not None and face.embedding is not None:
                similarity = self._cosine_similarity(face.embedding, self._david_embedding)
                result["similarity"] = float(similarity)
                result["is_david"] = similarity >= self._similarity_threshold

            results.append(result)

        return results

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two embeddings."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def save_embedding(self, frame: np.ndarray, output_path: str) -> bool:
        """Detect face in frame and save embedding (for enrollment)."""
        if not self._loaded or self._app is None:
            return False

        faces = self._app.get(frame)
        if not faces:
            logger.warning("No face found for embedding save")
            return False

        # Use highest confidence face
        best_face = max(faces, key=lambda f: f.det_score)
        if best_face.embedding is None:
            logger.warning("Face detected but no embedding generated")
            return False

        np.save(output_path, best_face.embedding)
        logger.info("Face embedding saved to %s", output_path)
        return True

    @property
    def is_loaded(self) -> bool:
        return self._loaded
