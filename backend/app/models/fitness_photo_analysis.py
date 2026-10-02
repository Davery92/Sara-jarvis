"""`fitness_photo_analysis` — immutable structured observations about a photo.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 27 / §5.5.

The shape is driven by what must NOT be possible:

* **No body-fat, weight or lean-mass column.** §5.5: "no body-fat
  percentage field or diagnosis". The validated output schema has no field
  for one either, and its validator rejects a number smuggled into prose —
  because a model with nowhere to put a composition estimate will put it in
  the summary, where it reads as an observation that `health_metric` never
  sees and cannot contradict.
* **No image bytes and no hidden reasoning.** §27 is explicit: nothing here
  stores the photo or a `reasoning_content` chain. The photo lives in object
  storage behind an owner check; a copy in a text column would be a second
  place to leak it from.
* **A comparison cannot cross owners.** `source_photo_id` and
  `compare_photo_id` both carry the owner, and a trigger checks all three
  agree. An FK to a UUID alone does not enforce ownership (§5), and a pair
  spanning two athletes would describe one person's body in the other's
  record.
* **Immutable once terminal.** The versions, the model and the output are
  frozen the same way a `fitness_coach_review` is: a stored observation
  whose output could be rewritten is not an observation, it is a cache.

`capture_hash` is the fingerprint of the exact bytes analysed. A photo whose
source is deleted or replaced invalidates its analyses rather than leaving a
result that describes an image nobody can see.
"""
import uuid

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base


class FitnessPhotoAnalysis(Base):
    __tablename__ = "fitness_photo_analysis"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'failed', "
            "'inconclusive', 'source_gone')",
            name="ck_photo_analysis_status",
        ),
        CheckConstraint(
            "kind IN ('single', 'pair')", name="ck_photo_analysis_kind",
        ),
        # A pair analysis needs a second photo; a single must not have one.
        CheckConstraint(
            "(kind = 'pair' AND compare_photo_id IS NOT NULL) OR "
            "(kind = 'single' AND compare_photo_id IS NULL)",
            name="ck_photo_analysis_pair_shape",
        ),
        # A completed analysis has output. A failed one has a reason. Neither
        # may be silent about which it is.
        CheckConstraint(
            "status <> 'complete' OR output IS NOT NULL",
            name="ck_photo_analysis_complete_has_output",
        ),
        CheckConstraint(
            "status <> 'failed' OR failure_category IS NOT NULL",
            name="ck_photo_analysis_failed_has_reason",
        ),
        Index(
            "ix_photo_analysis_user_recent",
            "user_id", "created_at",
        ),
        {"extend_existing": True},
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False,
    )

    kind = Column(String(8), nullable=False, default="single")
    source_photo_id = Column(
        String, ForeignKey("progress_photo.id", ondelete="CASCADE"),
        nullable=False,
    )
    compare_photo_id = Column(
        String, ForeignKey("progress_photo.id", ondelete="CASCADE"),
    )

    #: Captured so a result is traceable to the shot, not just its row.
    view = Column(String(16))
    source_captured_at = Column(DateTime(timezone=True))
    compare_captured_at = Column(DateTime(timezone=True))

    #: The fingerprint of the exact bytes analysed. A replaced or deleted
    #: source invalidates the result rather than leaving a description of an
    #: image nobody can see.
    capture_hash = Column(String(64))

    status = Column(String(20), nullable=False, default="pending")

    #: The model that ACTUALLY answered, and the endpoint it answered on. A
    #: fallback that answered as the primary makes every later comparison
    #: between runs meaningless — and for vision it also hides the case
    #: where a server without `--mmproj` answered the text prompt alone.
    model_requested = Column(String(120))
    model_actual = Column(String(120))
    provider = Column(String(60))
    endpoint = Column(String(200))
    #: Whether the probe confirmed this endpoint actually sees images. A
    #: result from an unverified endpoint is not evidence of anything.
    vision_verified = Column(Boolean, nullable=False, default=False)

    prompt_version = Column(String(40), nullable=False)
    prompt_hash = Column(String(64))
    output_schema_version = Column(Integer)

    #: The VALIDATED structured observation. Never raw model text, never a
    #: reasoning chain, never image bytes.
    output = Column(JSONB)
    summary = Column(Text)

    failure_category = Column(String(40))
    failure_detail = Column(String(500))

    attempts = Column(Integer, nullable=False, default=0)
    evaluated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return (
            f"<FitnessPhotoAnalysis id={self.id} kind={self.kind} "
            f"status={self.status}>"
        )
