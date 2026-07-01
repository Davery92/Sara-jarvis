-- Replace "The Forge — Periodized Recomp Plan" (program fb8866a2) with the
-- DUP 4-day Upper/Lower 8-week block, chest-emphasis variant. Start Mon 2026-06-15.
-- In-place rebuild: repurposes existing 4 phase rows + 16 template rows (no deletes).

BEGIN;

-- ── Program ───────────────────────────────────────────────────────────────
UPDATE fitness_program SET
  name='The Forge — Periodized Recomp Plan',
  goal='recomp',
  start_date='2026-06-15',
  end_date='2026-08-09',
  notes='DUP on a 4-day Upper/Lower split, 8-week block (accumulate, intensify, peak, deload). Chest-building emphasis: chest trained on both upper days, pre-exhaust on Upper B (flye first), full-ROM stretch work. Knee rule: hinge-biased, no leg curls, no high-impact, tempo squats over deep grinders. Each lift has a home option (barbell/rack/bench/DB/pull-up bar) so the session runs at home or the gym. Guardrails: ~240g protein daily, carb-cycled (rice-heavy on training days); leave reps in the tank in a deficit, save grinders for peak week; chest first when fresh. Cardio on-ramp: wk1-2 2-3 easy flat walks 15-20min; wk3-4 stretch to 25-35min; wk5-8 add gentle hills or a light 10-15lb pack (one variable), building a rucking base - slot on off-days or after upper work, never on leg days.',
  updated_at=now()
WHERE id='fb8866a2-2249-4dd9-9914-e34160aacb56';

-- ── Phases (repurpose the 4 existing rows, ordered by current start_date) ──
UPDATE fitness_phase SET
  name='Accumulate (Weeks 1-3)', goal='recomp',
  start_date='2026-06-15', end_date='2026-07-05', duration_weeks=3,
  status='active', deload_week=NULL, order_index=0,
  protein_target=240, training_days_per_week=4,
  notes='Weeks 1-3. Build volume. Reps at the higher end of each range, RPE ~7. Add a rep or a small load each week.',
  updated_at=now()
WHERE id='bae277be-4ad1-401f-b8fe-8c648ca918d4';

UPDATE fitness_phase SET
  name='Intensify (Weeks 4-6)', goal='recomp',
  start_date='2026-07-06', end_date='2026-07-26', duration_weeks=3,
  status='planned', deload_week=NULL, order_index=1,
  protein_target=240, training_days_per_week=4,
  notes='Weeks 4-6. Push the heavy 5s and 6s up in load, trim a touch of accessory volume. RPE ~8.',
  updated_at=now()
WHERE id='f808f6fa-8eee-44cf-bdb0-d1ee305eadbd';

UPDATE fitness_phase SET
  name='Peak (Week 7)', goal='recomp',
  start_date='2026-07-27', end_date='2026-08-02', duration_weeks=1,
  status='planned', deload_week=NULL, order_index=2,
  protein_target=240, training_days_per_week=4,
  notes='Week 7. Heaviest top sets of the cycle on the main lifts.',
  updated_at=now()
WHERE id='2403128a-d386-4689-a4cd-99c1ed4039e0';

UPDATE fitness_phase SET
  name='Deload (Week 8)', goal='recomp',
  start_date='2026-08-03', end_date='2026-08-09', duration_weeks=1,
  status='planned', deload_week=1, order_index=3,
  protein_target=240, training_days_per_week=4,
  notes='Week 8. ~60% of normal volume, easy loads. Recover, then restart the block heavier.',
  updated_at=now()
WHERE id='df7464c7-b3f2-45d3-9444-94e57dafadca';

-- ── Templates ─────────────────────────────────────────────────────────────
-- Upper A — Heavy Press (Mon) → one template per phase
UPDATE fitness_template SET
  name='Upper A — Heavy Press', scheduled_days='["monday"]', order_in_phase=0,
  notes='Heavy press day, chest lead. Chest movement comes first while fresh.',
  exercises='[{"name":"Barbell or Machine Chest Press","reps":"5","sets":4,"notes":"Chest lead - hit it first while fresh. Home: barbell bench press or heavy DB press. Leave 2-3 reps in reserve early in the block.","rpe_target":7,"is_per_side":false,"metric_type":"reps","rest_seconds":180,"rep_range_low":5,"set_technique":null,"rep_range_high":5,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Weighted Pull-Up or Lat Pulldown","reps":"6","sets":4,"notes":"Home: pull-ups, add a plate on a dip belt or between the feet once bodyweight is easy.","rpe_target":7,"is_per_side":false,"metric_type":"reps","rest_seconds":150,"rep_range_low":6,"set_technique":null,"rep_range_high":6,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Incline DB or Machine Press","reps":"8","sets":3,"notes":"Home: incline DB press. Deep stretch at the bottom, full ROM.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":120,"rep_range_low":8,"set_technique":null,"rep_range_high":8,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Seated Cable or Machine Row","reps":"10","sets":3,"notes":"Home: DB row or barbell row.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":90,"rep_range_low":10,"set_technique":null,"rep_range_high":10,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Cable Lateral Raise","reps":"15","sets":3,"notes":"Home: DB lateral raise.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":60,"rep_range_low":15,"set_technique":null,"rep_range_high":15,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Cable or Machine Triceps Pushdown","reps":"12","sets":3,"notes":"Home: DB skull-crusher or close-grip press.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":60,"rep_range_low":12,"set_technique":null,"rep_range_high":12,"superset_group":null,"progression_rule":"LINEAR"}]',
  updated_at=now()
WHERE id IN ('65f104e8-9f37-4dbf-9a7d-2e8d25b00cbc','2fe2258f-88d6-4f16-9ce6-765e6688ac8b','d323af39-5f56-4795-88cd-19a879516164','bc4329af-f30d-481a-a2d5-c07df4d0808d');

-- Lower A — Heavy Hinge (Tue)
UPDATE fitness_template SET
  name='Lower A — Heavy Hinge', scheduled_days='["tuesday"]', order_in_phase=1,
  notes='Heavy hinge day. Hinge is the engine; tempo squats over deep grinders.',
  exercises='[{"name":"Deadlift","reps":"5","sets":4,"notes":"2-3 reps in the tank. The hinge is your engine - lean on it.","rpe_target":7,"is_per_side":false,"metric_type":"reps","rest_seconds":180,"rep_range_low":5,"set_technique":null,"rep_range_high":5,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Tempo Back Squat","reps":"6","sets":3,"notes":"3-second descent, no deep grinders. Knee option: hack squat or leg press.","rpe_target":7,"is_per_side":false,"metric_type":"reps","rest_seconds":150,"rep_range_low":6,"set_technique":null,"rep_range_high":6,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Barbell Good Morning","reps":"8","sets":3,"notes":"Light. Machine option: cable pull-through or back extension.","rpe_target":7,"is_per_side":false,"metric_type":"reps","rest_seconds":120,"rep_range_low":8,"set_technique":null,"rep_range_high":8,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Reverse Lunge","reps":"8","sets":3,"notes":"Per leg. Machine option: single-leg leg press.","rpe_target":8,"is_per_side":true,"metric_type":"reps","rest_seconds":90,"rep_range_low":8,"set_technique":null,"rep_range_high":8,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Standing or Seated Calf Raise","reps":"15","sets":4,"notes":"","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":60,"rep_range_low":15,"set_technique":null,"rep_range_high":15,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Hanging Leg Raise or Plank","reps":"12","sets":3,"notes":"Core. 10-15 reps, or 30-45s plank hold.","rpe_target":null,"is_per_side":false,"metric_type":"reps","rest_seconds":60,"rep_range_low":10,"set_technique":null,"rep_range_high":15,"superset_group":null,"progression_rule":"LINEAR"}]',
  updated_at=now()
WHERE id IN ('efc82005-6c95-4959-9f6d-566a8f304b1e','5e281c13-8349-4367-92cf-63f1ff38dd8f','33449f29-bfdd-4a5f-b84a-73e26f9a2d4b','b4405119-9290-4d78-95fb-162db1ab6364');

-- Upper B — Chest Pre-Exhaust + Volume (Thu)
UPDATE fitness_template SET
  name='Upper B — Chest Pre-Exhaust', scheduled_days='["thursday"]', order_in_phase=2,
  notes='Chest pre-exhaust + volume. Isolate the pec FIRST so it limits the press that follows.',
  exercises='[{"name":"Pec-Deck or Cable Flye","reps":"15","sets":3,"notes":"PRE-EXHAUST - do this FIRST so the pec is the limiting factor on the press that follows. Home: flat or incline DB flye. Big stretch, hard squeeze.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":60,"rep_range_low":15,"set_technique":null,"rep_range_high":15,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Incline Barbell or Machine Press","reps":"8","sets":4,"notes":"Follows the flye pre-exhaust - chest should be the limiter. Home: incline DB press.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":150,"rep_range_low":8,"set_technique":null,"rep_range_high":8,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Flat DB or Machine Press","reps":"10","sets":3,"notes":"Home: flat DB press. Deep stretch, full ROM.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":120,"rep_range_low":10,"set_technique":null,"rep_range_high":10,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Chest-Supported Machine or Cable Row","reps":"10","sets":4,"notes":"Home: chest-supported DB row.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":120,"rep_range_low":10,"set_technique":null,"rep_range_high":10,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Cable Lateral Raise","reps":"15","sets":3,"notes":"Home: DB lateral raise.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":60,"rep_range_low":15,"set_technique":null,"rep_range_high":15,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Chest-Supported Rear-Delt Flye","reps":"20","sets":3,"notes":"Home: chest-supported DB rear-delt fly.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":45,"rep_range_low":20,"set_technique":null,"rep_range_high":20,"superset_group":null,"progression_rule":"LINEAR"},{"name":"DB or Cable Curl","reps":"12","sets":3,"notes":"","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":60,"rep_range_low":12,"set_technique":null,"rep_range_high":12,"superset_group":null,"progression_rule":"LINEAR"}]',
  updated_at=now()
WHERE id IN ('afdc09d1-39f1-4736-bb7c-cc0faf963a45','3d9d8d06-ce7f-4cdb-ab83-c86ca9c6b252','0bf5e100-a1f0-43a7-ab55-147df4c9770f','c72ea9b6-a125-4459-8380-2979c0c84efd');

-- Lower B — Volume Hinge (Fri)
UPDATE fitness_template SET
  name='Lower B — Volume Hinge', scheduled_days='["friday"]', order_in_phase=3,
  notes='Volume hinge day. Higher reps, controlled, big stretch.',
  exercises='[{"name":"Romanian Deadlift","reps":"10","sets":4,"notes":"Big hamstring stretch, controlled. The hinge is your engine.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":150,"rep_range_low":10,"set_technique":null,"rep_range_high":10,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Front Squat or Tempo Goblet Squat","reps":"10","sets":3,"notes":"Lighter. Machine option: leg press or hack squat if the knee prefers.","rpe_target":7,"is_per_side":false,"metric_type":"reps","rest_seconds":120,"rep_range_low":10,"set_technique":null,"rep_range_high":10,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Cable Pull-Through or Back Extension","reps":"12","sets":3,"notes":"Home: light barbell good morning.","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":90,"rep_range_low":12,"set_technique":null,"rep_range_high":12,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Reverse Lunge or Step-Back","reps":"10","sets":3,"notes":"Per leg. Machine option: single-leg leg press.","rpe_target":8,"is_per_side":true,"metric_type":"reps","rest_seconds":90,"rep_range_low":10,"set_technique":null,"rep_range_high":10,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Standing Calf Raise","reps":"15","sets":4,"notes":"","rpe_target":8,"is_per_side":false,"metric_type":"reps","rest_seconds":60,"rep_range_low":15,"set_technique":null,"rep_range_high":15,"superset_group":null,"progression_rule":"LINEAR"},{"name":"Side Plank or Floor Core","reps":"12","sets":3,"notes":"Core. Per side, or 30-45s hold.","rpe_target":null,"is_per_side":false,"metric_type":"reps","rest_seconds":45,"rep_range_low":10,"set_technique":null,"rep_range_high":15,"superset_group":null,"progression_rule":"LINEAR"}]',
  updated_at=now()
WHERE id IN ('7c34d162-cf42-4e26-a046-0b3cbf394fbc','fc518e4e-48ae-483c-9397-352ad3ce7124','bdf82db0-cd75-4894-8a9f-9daf54cfc247','2031bbec-c440-4891-8451-987222d5f93a');

COMMIT;
