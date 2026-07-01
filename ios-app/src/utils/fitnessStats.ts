// fitnessStats — client-side derivations over logged workout/food data. There is
// no backend PR or volume endpoint, so the Train and Progress views compute these
// from the WorkoutSession rows we already load.
import { WorkoutSession, WorkoutSet, FoodLog } from '../services/fitness';

export interface PersonalRecord {
  exercise: string;
  weight: number;
  reps: number;
  est1rm: number;       // Epley estimate
  date?: string;
}

/** Epley estimated 1-rep max. */
export function est1rm(weight: number, reps: number): number {
  if (!weight) return 0;
  if (reps <= 1) return weight;
  return Math.round(weight * (1 + reps / 30));
}

function setName(set: WorkoutSet): string {
  return (set.exercise_name || set.exercise_id || 'Exercise').trim();
}

/**
 * Best lift per exercise across the given sessions, ranked by estimated 1RM.
 * Compound lifts (squat/bench/deadlift) are floated to the top when present so
 * the Train view shows the "big three" first, like the mockup.
 */
export function computePRs(sessions: WorkoutSession[], limit = 3): PersonalRecord[] {
  const best = new Map<string, PersonalRecord>();
  for (const s of sessions) {
    for (const set of s.exercises || []) {
      if (!set.weight) continue;
      const name = setName(set);
      const e = est1rm(set.weight, set.reps || 1);
      const prev = best.get(name);
      if (!prev || e > prev.est1rm) {
        best.set(name, {
          exercise: name,
          weight: set.weight,
          reps: set.reps || 1,
          est1rm: e,
          date: set.session_date || s.session_date,
        });
      }
    }
  }

  const COMPOUND = ['squat', 'bench', 'deadlift'];
  const rank = (pr: PersonalRecord) => {
    const i = COMPOUND.findIndex(c => pr.exercise.toLowerCase().includes(c));
    return i === -1 ? COMPOUND.length : i;
  };

  return [...best.values()]
    .sort((a, b) => {
      const ra = rank(a);
      const rb = rank(b);
      if (ra !== rb) return ra - rb;
      return b.est1rm - a.est1rm;
    })
    .slice(0, limit);
}

/** Total volume (Σ weight × reps) for a single session. */
export function sessionVolume(session: WorkoutSession): number {
  return (session.exercises || []).reduce(
    (sum, set) => sum + (set.weight || 0) * (set.reps || 0),
    0,
  );
}

export interface DayBucket<T> {
  date: string;       // YYYY-MM-DD
  items: T[];
}

/** Group rows by a YYYY-MM-DD date accessor, chronological. */
export function groupByDay<T>(rows: T[], dateOf: (row: T) => string | undefined): DayBucket<T>[] {
  const map = new Map<string, T[]>();
  for (const row of rows) {
    const d = dateOf(row);
    if (!d) continue;
    const key = d.slice(0, 10);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(row);
  }
  return [...map.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([date, items]) => ({ date, items }));
}

/** Daily calorie totals over a window, chronological. */
export function dailyCalories(foods: FoodLog[]): { date: string; calories: number }[] {
  return groupByDay(foods, f => (f.logged_at ? f.logged_at.slice(0, 10) : undefined)).map(b => ({
    date: b.date,
    calories: Math.round(b.items.reduce((s, f) => s + (f.calories || 0), 0)),
  }));
}
