"""Thin helper for queueing ML training jobs — used by the nightly
app.tasks.ml.retrain_all task and by the Settings > Intelligence panel's
"Retrain now" action."""
from typing import Any, Dict, Optional

from app.services.ml.control_plane import create_training_job


def create_ml_training_job(model_family: str, *, requested_by: str, dataset_window_days: int = 90, notes: Optional[str] = None) -> Dict[str, Any]:
    return create_training_job(
        "train_model",
        {
            "model_family": model_family,
            "dataset_window_days": dataset_window_days,
            "notes": notes,
        },
        requested_by=requested_by,
    )
