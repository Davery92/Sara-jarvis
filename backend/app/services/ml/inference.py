"""In-backend model serving (Desktop Jarvis Overhaul C2).

Models are small (tabular, LightGBM/sklearn) — loaded from MinIO into
process memory rather than adding a network hop in the hot notification/
interruptibility path. Call `refresh()` on startup and periodically
(the nightly retrain task calls it after activation); `predict()` is a
plain in-memory function call.
"""
import io
import logging
import pickle
import threading
import uuid
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_loaded_models: Dict[str, Dict[str, Any]] = {}  # model_family -> {"version": ..., "artifact": ...}


def _minio_client():
    from minio import Minio
    from app.core.config import settings

    endpoint = settings.minio_url.replace("http://", "").replace("https://", "")
    return Minio(
        endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_url.startswith("https://"),
    )


def refresh(model_family: Optional[str] = None) -> Dict[str, str]:
    """Reload the active version of one family (or all) from the ML control
    plane registry + MinIO. Best-effort — a family with no active version
    or a fetch failure just stays unloaded (predict() then returns None,
    the caller's heuristic fallback keeps running)."""
    import os
    from app.services.ml.control_plane import get_model_registry, ML_MODEL_FAMILIES

    bucket = os.getenv("ML_MODEL_BUCKET", "sara-ml-models")
    registry = get_model_registry()
    families = [model_family] if model_family else ML_MODEL_FAMILIES
    loaded: Dict[str, str] = {}

    for family in families:
        family_entry = registry.get(family) or {}
        active_version = family_entry.get("active_version")
        if not active_version:
            continue
        with _lock:
            if _loaded_models.get(family, {}).get("version") == active_version:
                loaded[family] = active_version
                continue
        try:
            versions = {v["version"]: v for v in family_entry.get("versions", [])}
            metadata = (versions.get(active_version) or {}).get("metadata", {})
            artifact_key = metadata.get("artifact_key")
            if not artifact_key:
                continue
            client = _minio_client()
            response = client.get_object(bucket, artifact_key)
            artifact = pickle.load(io.BytesIO(response.read()))
            with _lock:
                _loaded_models[family] = {"version": active_version, "artifact": artifact}
            loaded[family] = active_version
        except Exception as e:
            logger.warning(f"ml.inference: failed to load {family}@{active_version}: {e}")

    return loaded


def _vectorize(artifact: Dict[str, Any], features: Dict[str, Any]):
    import numpy as np

    numeric_cols = artifact["numeric_cols"]
    categorical_cols = artifact["categorical_cols"]
    vocab = artifact["categorical_vocab"]

    vec = [float(features.get(col) or 0) for col in numeric_cols]
    for col in categorical_cols:
        value = str(features.get(col))
        vec.extend(1.0 if value == option else 0.0 for option in vocab[col])
    return np.array([vec])


def predict(model_family: str, features: Dict[str, Any], *, user_id: Optional[str] = None, mode: str = "shadow") -> Optional[Tuple[float, str]]:
    """Returns (score, version) or None if no model is loaded for this
    family — callers must have a heuristic fallback for the None case."""
    with _lock:
        entry = _loaded_models.get(model_family)
    if not entry:
        return None

    try:
        artifact = entry["artifact"]
        model = artifact["model"]
        X = _vectorize(artifact, features)
        score = float(model.predict_proba(X)[0][1]) if hasattr(model, "predict_proba") else float(model.predict(X)[0])
    except Exception as e:
        logger.warning(f"ml.inference: predict failed for {model_family}: {e}")
        return None

    if user_id:
        _log_prediction(user_id, model_family, entry["version"], features, score, mode)

    return score, entry["version"]


def _log_prediction(user_id: str, model_family: str, version: str, features: Dict[str, Any], score: float, mode: str) -> None:
    try:
        from app.db.base import SessionLocal
        from sqlalchemy import text
        import json

        with SessionLocal() as db:
            db.execute(text("""
                INSERT INTO ml_prediction_log (id, user_id, model_family, model_version, features, prediction, mode, created_at)
                VALUES (:id, :user_id, :model_family, :model_version, CAST(:features AS jsonb), CAST(:prediction AS jsonb), :mode, NOW())
            """), {
                "id": str(uuid.uuid4()), "user_id": user_id, "model_family": model_family,
                "model_version": version, "features": json.dumps(features),
                "prediction": json.dumps({"score": score}), "mode": mode,
            })
            db.commit()
    except Exception as e:
        logger.debug(f"ml.inference: prediction logging failed: {e}")


def predict_multiclass(model_family: str, features: Dict[str, Any], *, user_id: Optional[str] = None, mode: str = "shadow") -> Optional[Tuple[str, float, str]]:
    """Multiclass variant for next_block-style families — returns
    (predicted_label, confidence, version) or None if unloaded. Separate
    from predict() because these artifacts carry a class-label vocabulary
    instead of a single positive-class probability."""
    with _lock:
        entry = _loaded_models.get(model_family)
    if not entry:
        return None

    try:
        artifact = entry["artifact"]
        model = artifact["model"]
        class_labels = artifact["class_labels"]
        X = _vectorize(artifact, features)
        proba = model.predict_proba(X)[0]
        best_idx = int(proba.argmax())
        label, confidence = class_labels[best_idx], float(proba[best_idx])
    except Exception as e:
        logger.warning(f"ml.inference: multiclass predict failed for {model_family}: {e}")
        return None

    if user_id:
        _log_prediction(user_id, model_family, entry["version"], features, confidence, mode)

    return label, confidence, entry["version"]


def loaded_families() -> Dict[str, str]:
    with _lock:
        return {family: entry["version"] for family, entry in _loaded_models.items()}
