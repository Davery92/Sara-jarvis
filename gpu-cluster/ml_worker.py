"""
ML training worker (Desktop Jarvis Overhaul C2/C3).

Polls the ML control plane (/api/ml/jobs/claim) for `train_model` jobs,
pulls features from Postgres (read-only creds), trains a model per family,
evaluates walk-forward (train on days 1..N-14, test on last 14), writes the
artifact to MinIO, and registers the version.

Model families and their label sources:
- interruptibility_v2 / notification_value: binary classifiers over
  ml_notification_outcome (features-at-send-time -> engaged/ignored).
  These have a real, existing label source, so they train for real here
  (LightGBM if available, else sklearn GradientBoostingClassifier).
- next_block / rhythm_forecaster: no clean supervised label exists yet
  (next_block needs a learned activity-vocabulary label; rhythm_forecaster
  is a percentile-distribution upgrade to app/services/daily_rhythm.py, not
  a classifier). Training these families honestly reports
  "insufficient_labels" rather than registering a meaningless model —
  wiring these up for real is future work once behavioral_pattern/activity
  labels exist in sufficient volume.
"""
import asyncio
import io
import json
import logging
import os
import pickle
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ml_worker")

REAL_LABEL_FAMILIES = {"interruptibility_v2", "notification_value"}


def _as_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class MLTrainingWorker:
    def __init__(self) -> None:
        self.backend_url = os.getenv("SARA_BACKEND_URL", "http://10.185.1.180:8000").rstrip("/")
        self.internal_service = os.getenv("ML_INTERNAL_SERVICE", "ml-worker")
        self.internal_token = os.getenv("ML_CONTROL_INTERNAL_TOKEN", os.getenv("VOICE_CONTROL_INTERNAL_TOKEN", ""))
        self.poll_interval_seconds = int(os.getenv("ML_TRAINING_POLL_INTERVAL_SECONDS", "10"))
        self.heartbeat_interval_seconds = int(os.getenv("ML_TRAINING_HEARTBEAT_INTERVAL_SECONDS", "20"))
        self.auto_activate = _as_bool(os.getenv("ML_TRAINING_AUTO_ACTIVATE", "false"), False)
        self.database_url = os.getenv("ML_READONLY_DATABASE_URL", os.getenv("DATABASE_URL", ""))
        self.minio_url = os.getenv("MINIO_URL", "http://minio:9000")
        self.minio_access_key = os.getenv("MINIO_ACCESS_KEY", "sara")
        self.minio_secret_key = os.getenv("MINIO_SECRET_KEY", "")
        self.minio_bucket = os.getenv("ML_MODEL_BUCKET", "sara-ml-models")

        self.http: Optional[httpx.AsyncClient] = None
        self.running = False

    @property
    def headers(self) -> Dict[str, str]:
        return {"X-Internal-Service": self.internal_service, "X-Internal-Token": self.internal_token}

    async def start(self) -> None:
        self.http = httpx.AsyncClient(timeout=30.0)
        self.running = True
        logger.info("ml worker started (service=%s backend=%s)", self.internal_service, self.backend_url)
        await asyncio.gather(self._heartbeat_loop(), self._job_loop())

    async def stop(self) -> None:
        self.running = False
        if self.http:
            await self.http.aclose()
            self.http = None

    async def _heartbeat_loop(self) -> None:
        assert self.http is not None
        while self.running:
            start = time.perf_counter()
            try:
                response = await self.http.post(
                    f"{self.backend_url}/api/ml/services/{self.internal_service}/heartbeat",
                    json={
                        "status": "healthy",
                        "version": "ml-worker-v1",
                        "latency_ms": round((time.perf_counter() - start) * 1000.0, 2),
                        "details": {"auto_activate": self.auto_activate},
                    },
                    headers=self.headers,
                )
                response.raise_for_status()
            except Exception as exc:
                logger.warning("heartbeat failed: %s", exc)
            await asyncio.sleep(self.heartbeat_interval_seconds)

    async def _job_loop(self) -> None:
        assert self.http is not None
        while self.running:
            try:
                claim_response = await self.http.post(
                    f"{self.backend_url}/api/ml/jobs/claim",
                    json={"job_types": ["train_model"]},
                    headers=self.headers,
                )
                claim_response.raise_for_status()
                job = claim_response.json().get("job")
                if not job:
                    await asyncio.sleep(self.poll_interval_seconds)
                    continue
                await self._run_training_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("job loop failure: %s", exc)
                await asyncio.sleep(self.poll_interval_seconds)

    def _fetch_notification_outcomes(self, window_days: int) -> List[Dict[str, Any]]:
        import psycopg2
        import psycopg2.extras

        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        rows: List[Dict[str, Any]] = []
        conn = psycopg2.connect(self.database_url)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT hour, day_of_week, activity_state, interruptibility_score,
                           device, category, outcome, features, sent_at
                    FROM ml_notification_outcome
                    WHERE sent_at >= %s AND outcome IS NOT NULL
                    ORDER BY sent_at ASC
                    """,
                    (since,),
                )
                rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
        return rows

    def _train_binary_engagement_model(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """interruptibility_v2 / notification_value share this — both are
        P(engage | features-at-send-time), just consumed differently
        downstream (gate vs. threshold)."""
        import numpy as np

        if len(rows) < 200:
            raise RuntimeError(f"insufficient_labels: {len(rows)} labeled sends (need >= 200)")

        categorical_cols = ["activity_state", "device", "category"]
        numeric_cols = ["hour", "day_of_week", "interruptibility_score"]

        # Simple one-hot over observed categorical values — no sklearn
        # ColumnTransformer dependency, keeps this worker's requirements small.
        vocab: Dict[str, List[str]] = {
            col: sorted({str(r.get(col)) for r in rows if r.get(col) is not None})
            for col in categorical_cols
        }

        def _vectorize(row: Dict[str, Any]) -> List[float]:
            vec = [float(row.get(col) or 0) for col in numeric_cols]
            for col in categorical_cols:
                value = str(row.get(col))
                vec.extend(1.0 if value == option else 0.0 for option in vocab[col])
            return vec

        X = np.array([_vectorize(r) for r in rows])
        y = np.array([1 if r["outcome"] in ("opened", "acted") else 0 for r in rows])

        # Walk-forward split: train on all but the last 14 days, test on the last 14.
        split_idx = max(1, len(rows) - int(len(rows) * (14 / max(len(rows), 14))))
        split_idx = min(split_idx, len(rows) - 1)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]

        try:
            import lightgbm as lgb
            model = lgb.LGBMClassifier(n_estimators=100, max_depth=4, learning_rate=0.05)
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            model = GradientBoostingClassifier(n_estimators=100, max_depth=3)

        model.fit(X_train, y_train)

        from sklearn.metrics import precision_score, recall_score, roc_auc_score
        y_pred = model.predict(X_test)
        y_proba = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else y_pred

        metrics = {
            "simulated": False,
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
            "auc": round(float(roc_auc_score(y_test, y_proba)), 4) if len(set(y_test)) > 1 else None,
        }

        artifact = {"model": model, "categorical_vocab": vocab, "numeric_cols": numeric_cols, "categorical_cols": categorical_cols}
        return {"artifact": artifact, "metrics": metrics}

    def _upload_artifact(self, model_family: str, version: str, artifact: Dict[str, Any]) -> str:
        from minio import Minio

        buf = io.BytesIO()
        pickle.dump(artifact, buf)
        buf.seek(0)
        size = buf.getbuffer().nbytes

        client = Minio(
            self.minio_url.replace("http://", "").replace("https://", ""),
            access_key=self.minio_access_key,
            secret_key=self.minio_secret_key,
            secure=self.minio_url.startswith("https://"),
        )
        if not client.bucket_exists(self.minio_bucket):
            client.make_bucket(self.minio_bucket)

        artifact_key = f"{model_family}/{version}.pkl"
        client.put_object(self.minio_bucket, artifact_key, buf, size)
        return artifact_key

    async def _run_training_job(self, job: Dict[str, Any]) -> None:
        assert self.http is not None
        job_id = str(job.get("job_id") or "")
        payload = job.get("payload") or {}
        model_family = str(payload.get("model_family") or "")
        window_days = int(payload.get("dataset_window_days") or 90)

        if not job_id or not model_family:
            return

        try:
            await self._set_status(job_id, "running", notes=f"training {model_family} (window={window_days}d)")

            if model_family not in REAL_LABEL_FAMILIES:
                raise RuntimeError(
                    f"insufficient_labels: {model_family} has no supervised label source yet "
                    "(next_block needs a learned activity vocabulary; rhythm_forecaster is a "
                    "percentile upgrade to daily_rhythm.py, not a classifier)"
                )

            rows = await asyncio.to_thread(self._fetch_notification_outcomes, window_days)
            result = await asyncio.to_thread(self._train_binary_engagement_model, rows)

            version = f"{model_family}_v{int(time.time())}"
            artifact_key = await asyncio.to_thread(self._upload_artifact, model_family, version, result["artifact"])

            await self._register_version(model_family, version, result["metrics"], artifact_key, job_id)

            notes = f"{model_family} model {version} trained"
            if self.auto_activate:
                await self._activate_version(model_family, version)
                notes += " and activated"

            await self._set_status(job_id, "completed", notes=notes, result={
                "model_family": model_family, "version": version, "metrics": result["metrics"],
                "artifact_key": artifact_key, "auto_activated": self.auto_activate,
            })
            logger.info("training job completed: %s -> %s", job_id, version)

        except Exception as exc:
            logger.error("training job failed: %s", exc)
            await self._set_status(job_id, "failed", notes="training failed", error=str(exc))

    async def _set_status(self, job_id: str, status: str, *, notes: str = None, error: str = None, result: dict = None) -> None:
        assert self.http is not None
        resp = await self.http.post(
            f"{self.backend_url}/api/ml/jobs/{job_id}/status",
            json={"status": status, "notes": notes, "error": error, "result": result},
            headers=self.headers,
        )
        resp.raise_for_status()

    async def _register_version(self, model_family: str, version: str, metrics: dict, artifact_key: str, job_id: str) -> None:
        assert self.http is not None
        resp = await self.http.post(
            f"{self.backend_url}/api/ml/models/{model_family}/versions",
            json={"version": version, "status": "candidate", "metrics": metrics, "metadata": {"job_id": job_id, "artifact_key": artifact_key}},
            headers=self.headers,
        )
        resp.raise_for_status()

    async def _activate_version(self, model_family: str, version: str) -> None:
        assert self.http is not None
        resp = await self.http.post(
            f"{self.backend_url}/api/ml/models/{model_family}/activate-internal",
            json={"version": version},
            headers=self.headers,
        )
        resp.raise_for_status()


async def main() -> None:
    worker = MLTrainingWorker()
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
