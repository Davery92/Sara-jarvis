"""notification_value model (§4.2.5 / D1 fix) — trained in-process, stored in the DB.

The audit's D1: infrastructure existed (feature store, labeled outcomes, model
registry) but **no worker ever trained anything** — 88 jobs queued into a void,
`ml_model_version` empty forever. This replaces the phantom Redis/MinIO plane
with the simplest thing that actually learns: a logistic-regression over the
~90 labeled `ml_notification_outcome` rows, serialized *into* the DB row itself
(no artifact store), cross-validated, and promoted only if it beats the current
model on held-out data.

Predicts P(a notification is valuable) = P(David acts on or opens it), from
{hour-bucket, day-of-week, activity_state, interruptibility, category}. Runs in
**shadow mode** inside the delivery policy (§3.6) first — logs its opinion next
to the heuristic decision so we can see it win before it ever gates anything.
"""
import hashlib
import json
import logging
import math
from typing import Optional, Dict, Any, Tuple

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

FAMILY = "notification_value"
_MIN_SAMPLES = 40          # cold-start floor
_PROMOTE_MIN_AUC = 0.55    # must beat coin-flip by a margin


# ---- featurization (shared by train + inference) ----

def _hour_bucket(hour) -> str:
    try:
        h = int(hour)
    except (TypeError, ValueError):
        return "unknown"
    if 5 <= h < 11:
        return "morning"
    if 11 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"


def featurize(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a notification's context to model features. Categorical values become
    "<field>=<value>" one-hot keys; interruptibility stays numeric."""
    feats: Dict[str, Any] = {}
    feats[f"hourb={_hour_bucket(row.get('hour'))}"] = 1.0
    feats[f"dow={row.get('day_of_week')}"] = 1.0
    feats[f"activity={row.get('activity_state') or 'unknown'}"] = 1.0
    feats[f"category={row.get('category') or 'general'}"] = 1.0
    feats[f"device={row.get('device') or 'unknown'}"] = 1.0
    try:
        feats["interruptibility"] = float(row.get("interruptibility_score") or 0.5)
    except (TypeError, ValueError):
        feats["interruptibility"] = 0.5
    return feats


def _label(outcome: str) -> Optional[int]:
    if outcome in ("acted", "opened"):
        return 1
    if outcome in ("dismissed", "ignored"):
        return 0
    return None  # unlabeled → excluded


# ---- training ----

async def train(db, user_id: Optional[str] = None) -> dict:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import roc_auc_score

    rows = (await db.execute(text("""
        SELECT hour, day_of_week, activity_state, interruptibility_score,
               device, category, location, outcome
        FROM ml_notification_outcome
        WHERE outcome IS NOT NULL
    """))).fetchall()

    samples, labels = [], []
    for r in rows:
        y = _label(r.outcome)
        if y is None:
            continue
        samples.append(featurize({
            "hour": r.hour, "day_of_week": r.day_of_week,
            "activity_state": r.activity_state,
            "interruptibility_score": r.interruptibility_score,
            "device": r.device, "category": r.category,
        }))
        labels.append(y)

    n = len(labels)
    if n < _MIN_SAMPLES:
        logger.info(f"ml.notification_value: cold start — only {n} labeled samples (<{_MIN_SAMPLES})")
        return {"effect": "skipped_cold_start", "samples": n}
    if len(set(labels)) < 2:
        return {"effect": "skipped_single_class", "samples": n}

    dvec = DictVectorizer(sparse=False)
    X = dvec.fit_transform(samples)
    y = np.array(labels)

    # Cross-validated AUC (honest held-out estimate).
    aucs = []
    try:
        skf = StratifiedKFold(n_splits=min(5, int(y.sum()), int((1 - y).sum())), shuffle=True, random_state=42)
        for tr, te in skf.split(X, y):
            if len(set(y[tr])) < 2 or len(set(y[te])) < 2:
                continue
            m = LogisticRegression(max_iter=1000, class_weight="balanced")
            m.fit(X[tr], y[tr])
            p = m.predict_proba(X[te])[:, 1]
            aucs.append(roc_auc_score(y[te], p))
    except Exception as e:
        logger.debug(f"CV failed: {e}")
    cv_auc = float(sum(aucs) / len(aucs)) if aucs else None
    base_rate = float(y.mean())

    # Fit final model on all data.
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X, y)

    # Serialize the whole model into JSON (the model IS the DB row).
    payload = {
        "spec": "logreg_v1",
        "feature_names": dvec.get_feature_names_out().tolist(),
        "coef": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
    }
    metrics = {"cv_auc": cv_auc, "base_rate": base_rate, "n_samples": n,
               "n_positive": int(y.sum())}

    version = local_now().strftime("%Y%m%d_%H%M%S")

    # Promotion: beat coin-flip AND beat the current active model's CV-AUC.
    current = (await db.execute(text("""
        SELECT metrics FROM ml_model_version
        WHERE family = :f AND status = 'active'
        ORDER BY activated_at DESC NULLS LAST LIMIT 1
    """), {"f": FAMILY})).first()
    current_auc = None
    if current and current[0]:
        cm = current[0] if isinstance(current[0], dict) else json.loads(current[0])
        current_auc = cm.get("cv_auc")

    promote = (cv_auc is not None and cv_auc >= _PROMOTE_MIN_AUC and
               (current_auc is None or cv_auc >= current_auc))
    status = "active" if promote else "shadow"

    import uuid
    if promote:
        # Demote the previous active model.
        await db.execute(text(
            "UPDATE ml_model_version SET status='archived' WHERE family=:f AND status='active'"
        ), {"f": FAMILY})

    await db.execute(text("""
        INSERT INTO ml_model_version
          (id, family, version, artifact_key, metrics, metadata_json, status, created_at, activated_at)
        VALUES
          (:id, :f, :v, NULL, CAST(:met AS jsonb), CAST(:meta AS jsonb), :st, NOW(),
           CASE WHEN CAST(:st AS varchar) = 'active' THEN NOW() ELSE NULL END)
    """), {
        "id": str(uuid.uuid4()), "f": FAMILY, "v": version,
        "met": json.dumps(metrics), "meta": json.dumps(payload), "st": status,
    })
    await db.commit()

    logger.info(f"🧠 Trained {FAMILY}@{version}: cv_auc={cv_auc} base_rate={base_rate:.2f} "
                f"n={n} → status={status} (prev_active_auc={current_auc})")
    return {"effect": "trained", "family": FAMILY, "version": version,
            "status": status, "metrics": metrics}


# ---- inference (pure numpy from the stored JSON model) ----

_cache: Dict[str, Any] = {"version": None, "model": None}


async def predict(db, features: Dict[str, Any], *, user_id: str, mode: str = "shadow") -> Optional[Tuple[float, str]]:
    """Return (P(valuable), version) from the active model, logging to
    ml_prediction_log. None if no active model."""
    row = (await db.execute(text("""
        SELECT version, metadata_json FROM ml_model_version
        WHERE family = :f AND status = 'active'
        ORDER BY activated_at DESC NULLS LAST LIMIT 1
    """), {"f": FAMILY})).first()
    if not row:
        return None
    version, meta = row
    meta = meta if isinstance(meta, dict) else json.loads(meta)

    feats = featurize(features)
    names = meta["feature_names"]
    coef = meta["coef"]
    z = meta["intercept"]
    for name, w in zip(names, coef):
        z += w * float(feats.get(name, 0.0))
    p = 1.0 / (1.0 + math.exp(-z))

    try:
        await _log_prediction(db, user_id, version, features, p, mode)
    except Exception as e:
        logger.debug(f"prediction log skipped: {e}")
    return p, version


async def _log_prediction(db, user_id, version, features, score, mode):
    import uuid
    fh = hashlib.sha1(json.dumps(features, sort_keys=True, default=str).encode()).hexdigest()[:16]
    await db.execute(text("""
        INSERT INTO ml_prediction_log
          (id, user_id, model_family, model_version, features_hash, features, prediction, mode, created_at)
        VALUES
          (:id, :uid, :f, :v, :fh, CAST(:feat AS jsonb), CAST(:pred AS jsonb), :mode, NOW())
    """), {
        "id": str(uuid.uuid4()), "uid": user_id, "f": FAMILY, "v": version, "fh": fh,
        "feat": json.dumps(features, default=str),
        "pred": json.dumps({"p_valuable": round(score, 4)}), "mode": mode,
    })
    await db.commit()
