// Recovery / readiness scoring is computed server-side (the single source of
// truth: backend/app/services/recovery_score.py, surfaced on every recovery log
// via the /recovery API). This module is now display-only — it reads the
// server-provided score/label/status/color. No weights live here anymore, so
// the app and the morning brief can't drift apart.
import { RecoveryLog } from '../services/fitness';

// Kept for call-site compatibility; the baseline is computed on the server now.
export interface RecoveryBaseline {
  avgHrv: number | null;
  avgHr: number | null;
  avgSleep: number | null;
  avgWeight: number | null;
}

export interface RecoveryScore {
  score: number;            // 0-100
  label: string;            // Excellent / Good / Low / Poor
  status: string;           // human sentence
  color: 'success' | 'primary' | 'warning' | 'error';
}

/** Mean of the defined (non-null) numeric values, or null if none. */
function mean(values: Array<number | null | undefined>): number | null {
  const nums = values.filter((v): v is number => typeof v === 'number' && !Number.isNaN(v));
  if (!nums.length) return null;
  return nums.reduce((s, v) => s + v, 0) / nums.length;
}

/**
 * Retained for call-site compatibility (FitnessScreen / ProgressView still pass
 * a baseline into computeReadinessScore, which now ignores it). The real
 * baseline lives server-side.
 */
export function computeBaseline(logs: RecoveryLog[], excludeId?: string): RecoveryBaseline {
  const pool = excludeId ? logs.filter(l => l.id !== excludeId) : logs;
  return {
    avgHrv: mean(pool.map(l => l.hrv)),
    avgHr: mean(pool.map(l => l.heart_rate)),
    avgSleep: mean(pool.map(l => l.sleep_hours)),
    avgWeight: mean(pool.map(l => l.body_weight)),
  };
}

// Presentational fallback only — used if a log predates the server score.
// This is display bucketing, NOT the scoring weights (those are server-side).
function labelFor(score: number): Pick<RecoveryScore, 'label' | 'status' | 'color'> {
  if (score >= 85) return { label: 'Excellent', status: 'Well recovered — good to push it today', color: 'success' };
  if (score >= 70) return { label: 'Good', status: 'Moderate recovery — train but listen to your body', color: 'primary' };
  if (score >= 50) return { label: 'Low', status: 'Low recovery — consider lighter weights', color: 'warning' };
  return { label: 'Poor', status: 'Poor recovery — rest day recommended', color: 'error' };
}

/**
 * Read the server-computed readiness for a recovery log. The `_baseline` arg is
 * ignored (kept for signature compatibility); scoring happens on the server.
 */
export function computeReadinessScore(
  recovery: RecoveryLog | null | undefined,
  _baseline?: RecoveryBaseline,
): RecoveryScore | null {
  if (!recovery || recovery.readiness_score == null) return null;
  const score = recovery.readiness_score;
  const fallback = labelFor(score);
  return {
    score,
    label: recovery.readiness_label ?? fallback.label,
    status: recovery.readiness_status ?? fallback.status,
    color: recovery.readiness_color ?? fallback.color,
  };
}

export interface RecoveryScorePoint {
  date: string;       // YYYY-MM-DD
  score: number;
}

/** Chronological series of daily readiness scores (server-provided). */
export function buildScoreSeries(logs: RecoveryLog[]): RecoveryScorePoint[] {
  return [...logs]
    .filter(l => l.log_date && l.readiness_score != null)
    .sort((a, b) => (a.log_date < b.log_date ? -1 : 1))
    .map(l => ({ date: l.log_date, score: l.readiness_score as number }));
}

/** Format sleep hours (e.g. 8.2) as "8h 12m". */
export function formatSleep(hours?: number | null): string | null {
  if (hours == null) return null;
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}
