"""The canonical source contract.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 30.4: "Add new vendor integrations
behind canonical source adapter/idempotency/consent contract, beginning
with actual user demand. Existing HealthKit remains supported throughout."

No vendor is added here. That is the point of the step's own wording — a
second nutrition API nobody asked for is work that creates a reconciliation
problem and solves nothing. What this module adds is the shape any future
one has to fit, written down and enforced, so the next integration cannot
repeat what the existing ones did:

* **Several ingest paths with their own timestamp conventions.** There are
  three in this database — `food_log.logged_at` is naive ET wall-clock,
  `created_at` is naive UTC, `health_metric.recorded_at` is aware
  timestamptz. A source that does not declare which it sends lands its data
  4-5 hours out, and the error looks like the athlete logging at odd hours.
* **No idempotency.** A re-sync without a stable per-observation id
  duplicates a year of weigh-ins, and the duplicates are indistinguishable
  from genuine double entries.
* **Silent overwriting.** A later sync from a worse source replacing a
  manual entry is data loss that nothing reports.
* **Consent assumed from installation.** Registering a source is not
  consent to read from it.

`register` writes the contract row; `ingest` is the one write path that
honours it. An adapter that wants to write a metric it did not declare is
refused, which is the whole value of declaring.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    SourceAdapterContract, SourceKind,
)
from app.services.fitness.data_access import (
    FitnessDataError, _require_user, athlete_zone,
)

logger = logging.getLogger(__name__)

UTC = timezone.utc

#: HealthKit is registered as the baseline so the contract describes what
#: already exists rather than only what might. §30.4: "existing HealthKit
#: remains supported throughout" — and the way to keep that true is for it
#: to be described by the same contract everything else is.
HEALTHKIT_CONTRACT = SourceAdapterContract(
    kind=SourceKind.HEALTHKIT,
    vendor="apple_health",
    external_id_field="uuid",
    writes_metrics=[
        "weight", "body_fat", "lean_mass", "hrv_morning", "resting_hr",
        "steps", "sleep_hours", "active_energy", "vo2_max",
    ],
    # HealthKit sends aware timestamps and the ingest path keeps them.
    timestamp_convention="aware_utc",
    requires_consent=True,
    may_overwrite=False,
)


class SourceError(FitnessDataError):
    """A refusal a caller can show."""


def _now() -> datetime:
    return datetime.now(UTC)


#: `ck_health_metric_source_quality` is a closed set — measured, derived,
#: synthesized_stamp, manual — and it is NOT the source kind. A scale
#: measures; a nutrition API derives from a food database; a manual entry
#: is manual. Passing the kind through (which was the first thing I wrote)
#: fails the constraint on every insert.
_QUALITY_BY_KIND = {
    "healthkit": "measured",
    "scale": "measured",
    "wearable": "measured",
    "nutrition_api": "derived",
    "manual": "manual",
}


def _source_quality(kind: str) -> str:
    return _QUALITY_BY_KIND.get(kind, "derived")


def register(
    db: Session,
    user_id: Optional[str],
    contract: SourceAdapterContract,
    *,
    consented_at: Optional[datetime] = None,
    enabled: bool = False,
) -> Dict[str, Any]:
    """Record what a source is allowed to write.

    `enabled` is False by default and a consenting source cannot be enabled
    without `consented_at` — `ck_source_consent` refuses it. Registering is
    describing, not permitting.
    """
    owner = _require_user(user_id) if user_id else None
    if contract.requires_consent and enabled and consented_at is None:
        raise SourceError(
            f"{contract.vendor} requires consent and cannot be enabled "
            f"without it. Registering a source is not consent to read from "
            f"it."
        )

    adapter_id = str(uuid.uuid4())
    try:
        db.execute(text("""
            INSERT INTO fitness_source_adapter (
                id, user_id, kind, vendor, external_id_field,
                writes_metrics, timestamp_convention, requires_consent,
                may_overwrite, consented_at, enabled, created_at, updated_at
            ) VALUES (
                :id, :u, :kind, :vendor, :external_id,
                CAST(:metrics AS JSONB), :convention, :requires_consent,
                :may_overwrite, :consented_at, :enabled, NOW(), NOW()
            )
        """), {
            "id": adapter_id, "u": owner, "kind": contract.kind.value,
            "vendor": contract.vendor,
            "external_id": contract.external_id_field,
            "metrics": json.dumps(list(contract.writes_metrics)),
            "convention": contract.timestamp_convention,
            "requires_consent": contract.requires_consent,
            "may_overwrite": contract.may_overwrite,
            "consented_at": consented_at, "enabled": enabled,
        })
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SourceError(
            f"{contract.vendor} is already registered for this athlete. "
            f"Update it rather than registering a second adapter — two "
            f"contracts for one vendor means two answers to what it may "
            f"write."
        ) from exc
    return {"id": adapter_id, "vendor": contract.vendor, "enabled": enabled}


def get_contract(
    db: Session, user_id: Optional[str], vendor: str,
) -> Dict[str, Any]:
    """The registered contract for this vendor, owner-scoped then global."""
    owner = _require_user(user_id) if user_id else None
    row = db.execute(text("""
        SELECT id, user_id, kind, vendor, external_id_field, writes_metrics,
               timestamp_convention, requires_consent, may_overwrite,
               consented_at, enabled
        FROM fitness_source_adapter
        WHERE vendor = :vendor
          AND (user_id = :u OR user_id IS NULL)
        ORDER BY user_id IS NULL ASC
        LIMIT 1
    """), {"vendor": vendor, "u": owner}).fetchone()
    if row is None:
        raise LookupError(f"no registered adapter for {vendor!r}")
    item = dict(row._mapping)
    if isinstance(item.get("writes_metrics"), str):
        item["writes_metrics"] = json.loads(item["writes_metrics"])
    return item


def set_consent(
    db: Session, user_id: str, vendor: str, consented: bool,
) -> Dict[str, Any]:
    """Grant or withdraw consent for one source.

    Withdrawing disables it in the same statement: a source that keeps
    writing after consent is withdrawn is the failure this field exists to
    prevent, and leaving `enabled` true would allow exactly that.
    """
    owner = _require_user(user_id)
    updated = db.execute(text("""
        UPDATE fitness_source_adapter
        SET consented_at = CASE WHEN :consented THEN NOW() ELSE NULL END,
            enabled = CASE WHEN :consented THEN enabled ELSE FALSE END,
            updated_at = NOW()
        WHERE vendor = :vendor AND (user_id = :u OR user_id IS NULL)
        RETURNING id, enabled
    """), {"consented": consented, "vendor": vendor, "u": owner}).fetchone()
    if updated is None:
        raise LookupError(f"no registered adapter for {vendor!r}")
    db.commit()
    return {
        "vendor": vendor, "consented": consented,
        "enabled": bool(updated.enabled),
    }


@dataclass
class Observation:
    """One incoming reading, as the vendor sends it."""
    metric: str
    value: float
    unit: str
    #: Whatever the vendor's convention is. Converted on the way in,
    #: according to the contract, rather than by guessing from the value.
    observed_at: datetime
    external_id: str


def ingest(
    db: Session,
    user_id: str,
    vendor: str,
    observations: Sequence[Observation],
) -> Dict[str, Any]:
    """Write observations under a registered contract.

    Four refusals, in order, each of which has a failure behind it:

    1. **No contract** — an unregistered source writing to `health_metric`
       is the thing this module exists to stop.
    2. **No consent, or disabled** — registration is not permission.
    3. **An undeclared metric** — a source that can write anything will
       overwrite something. The declaration is the value.
    4. **A missing external id** — without one there is no idempotency, and
       a re-sync duplicates a year of weigh-ins.

    Timestamps are converted according to the contract's declared
    convention. A naive-local stamp becomes aware UTC using the athlete's
    own zone, because this container's clock is not it.
    """
    owner = _require_user(user_id)
    contract = get_contract(db, owner, vendor)

    if contract["requires_consent"] and contract["consented_at"] is None:
        raise SourceError(
            f"{vendor} has no consent on file. Registering a source is not "
            f"consent to read from it."
        )
    if not contract["enabled"]:
        raise SourceError(f"{vendor} is registered but switched off.")

    allowed = set(contract["writes_metrics"])
    tz = athlete_zone(db.execute(text("""
        SELECT timezone FROM fitness_athlete_profile WHERE user_id = :u
    """), {"u": owner}).scalar())

    written = 0
    skipped: List[str] = []
    for observation in observations:
        if observation.metric not in allowed:
            skipped.append(
                f"{observation.metric}: not declared by {vendor} "
                f"(declared: {', '.join(sorted(allowed))})"
            )
            continue
        if not observation.external_id or not str(observation.external_id).strip():
            skipped.append(
                f"{observation.metric}: no external id, so a re-sync could "
                f"not tell this reading from a new one"
            )
            continue

        recorded_at = _to_aware_utc(
            observation.observed_at, contract["timestamp_convention"], tz,
        )
        # Two unique indexes can stop this insert and they mean different
        # things:
        #
        #   `uq_health_metric_external_sample (user_id, source, external_id)`
        #       — this exact reading again. A re-sync. Always a no-op.
        #   `ix_health_metric_dedup (user_id, metric_type, recorded_at)`
        #       — a DIFFERENT reading for an instant that already has one.
        #       A genuine collision, and whether to take it is what
        #       `may_overwrite` decides.
        #
        # `ON CONFLICT` can only name one of them, so the second is checked
        # first. Letting it raise instead (which is what the first version
        # of this did) aborts the whole batch on one collision and the
        # reason never reaches the caller.
        occupant = db.execute(text("""
            SELECT source, external_id FROM health_metric
            WHERE user_id = :u AND metric_type = :metric
              AND recorded_at = :recorded_at
        """), {
            "u": owner, "metric": observation.metric,
            "recorded_at": recorded_at,
        }).fetchone()

        if occupant is not None:
            same_sample = (
                occupant.source == vendor
                and occupant.external_id == str(observation.external_id).strip()
            )
            if same_sample:
                # A re-sync of a reading already stored. Silent on purpose:
                # this is the normal case every time a vendor backfills.
                continue
            if not contract["may_overwrite"]:
                skipped.append(
                    f"{observation.metric} at {recorded_at.isoformat()}: an "
                    f"observation from {occupant.source} already holds that "
                    f"instant, and {vendor} may not overwrite it"
                )
                continue
            # Permitted to overwrite: supersede rather than delete, so the
            # replaced value stays queryable and the correction is
            # attributable. `health_metric` already has the columns for
            # this, and a DELETE would lose what was there.
            superseding = str(uuid.uuid4())
            db.execute(text("""
                INSERT INTO health_metric (
                    id, user_id, metric_type, value, unit, recorded_at,
                    logical_date, source, source_quality, external_id,
                    correction_reason, metadata, created_at
                ) VALUES (
                    :id, :u, :metric, :value, :unit,
                    :recorded_at + INTERVAL '1 millisecond',
                    DATE(:recorded_at), :source, :quality, :external_id,
                    :reason, CAST(:metadata AS JSONB), NOW()
                )
            """), {
                "id": superseding, "u": owner,
                "metric": observation.metric, "value": observation.value,
                "unit": observation.unit, "recorded_at": recorded_at,
                "source": vendor, "quality": _source_quality(contract["kind"]),
                "external_id": str(observation.external_id).strip(),
                "reason": f"superseded a {occupant.source} reading",
                "metadata": json.dumps({
                    "adapter_id": contract["id"],
                    "timestamp_convention": contract["timestamp_convention"],
                    "superseded_source": occupant.source,
                }),
            })
            db.execute(text("""
                UPDATE health_metric SET superseded_by_id = :new
                WHERE user_id = :u AND metric_type = :metric
                  AND recorded_at = :recorded_at
            """), {
                "new": superseding, "u": owner,
                "metric": observation.metric, "recorded_at": recorded_at,
            })
            written += 1
            continue

        result = db.execute(text("""
            INSERT INTO health_metric (
                id, user_id, metric_type, value, unit, recorded_at,
                logical_date, source, source_quality, external_id,
                metadata, created_at
            ) VALUES (
                :id, :u, :metric, :value, :unit, :recorded_at,
                DATE(:recorded_at), :source, :quality, :external_id,
                CAST(:metadata AS JSONB), NOW()
            )
            ON CONFLICT (user_id, source, external_id)
                WHERE external_id IS NOT NULL
            DO NOTHING
            RETURNING id
        """), {
            "id": str(uuid.uuid4()), "u": owner,
            "metric": observation.metric, "value": observation.value,
            "unit": observation.unit, "recorded_at": recorded_at,
            "source": vendor, "quality": _source_quality(contract["kind"]),
            "external_id": str(observation.external_id).strip(),
            "metadata": json.dumps({
                "adapter_id": contract["id"],
                "timestamp_convention": contract["timestamp_convention"],
            }),
        })
        if result.rowcount:
            written += 1

    db.commit()
    return {
        "vendor": vendor, "written": written,
        "skipped": skipped, "received": len(observations),
    }


def _to_aware_utc(
    moment: datetime, convention: str, tz: ZoneInfo,
) -> datetime:
    """A vendor timestamp into aware UTC, by declared convention.

    Not by inspecting the value: a naive datetime is naive whichever
    convention produced it, and guessing from the hour is how an evening
    weigh-in becomes a 4am one.
    """
    if convention == "aware_utc":
        if moment.tzinfo is None:
            raise SourceError(
                "the contract declares aware_utc and this timestamp is "
                "naive; one of the two is wrong and guessing would put the "
                "reading on the wrong day"
            )
        return moment.astimezone(UTC)
    if convention == "naive_utc":
        if moment.tzinfo is not None:
            return moment.astimezone(UTC)
        return moment.replace(tzinfo=UTC)
    if convention == "naive_local":
        if moment.tzinfo is not None:
            return moment.astimezone(UTC)
        # `fold=0` on the ambiguous hour, matching every other local-time
        # conversion in this subsystem.
        return moment.replace(tzinfo=tz, fold=0).astimezone(UTC)
    raise SourceError(f"unknown timestamp convention {convention!r}")


def ensure_healthkit(db: Session, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Register the HealthKit contract if it is not there.

    Idempotent, and it does NOT enable anything: the existing HealthKit
    ingest path keeps working exactly as it does today, and this row
    describes it so a future source has something to be consistent with.
    """
    try:
        return get_contract(db, user_id, HEALTHKIT_CONTRACT.vendor)
    except LookupError:
        pass
    try:
        return register(db, user_id, HEALTHKIT_CONTRACT, enabled=False)
    except SourceError:
        return get_contract(db, user_id, HEALTHKIT_CONTRACT.vendor)
