#!/usr/bin/env node
/**
 * Workout wire-contract parity check (plan §5, §14.2).
 *
 * The cross-device workout contract is written out four times — Swift on the
 * Watch, the same Swift copied into the iPhone Expo module, TypeScript in the
 * React Native app, Python in the backend. They cannot share code: different
 * languages, different processes, different devices.
 *
 * That makes drift the single most likely way this feature breaks, and the
 * failure is silent: rename `approved_weight` in one place and the Watch shows
 * a blank weight, or logs the wrong one, with nothing raising an error.
 *
 * So this script compares them. It is deliberately dependency-free and runs on
 * the Linux repo host — no Xcode, no jest, no install step:
 *
 *     node scripts/check-workout-contract-parity.mjs
 *
 * Exit code 1 means the copies have diverged. Fix the source, not this script.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const repo = join(root, '..');

const PATHS = {
  swiftWatch: join(root, 'targets/watch/WorkoutWireModels.swift'),
  swiftPhone: join(root, 'modules/sara-workout-native/ios/WorkoutWireModels.swift'),
  ts: join(root, 'src/services/workoutContracts.ts'),
  pyService: join(repo, 'backend/app/services/workout_command_service.py'),
  pyRoutes: join(repo, 'backend/app/routes/workout_v2.py'),
};

const failures = [];
const read = (p) => readFileSync(p, 'utf8');

function check(label, actual, expected) {
  const a = [...actual].sort();
  const b = [...expected].sort();
  const missing = b.filter((x) => !a.includes(x));
  const extra = a.filter((x) => !b.includes(x));
  if (missing.length || extra.length) {
    failures.push(
      `${label}\n` +
        (missing.length ? `    missing: ${missing.join(', ')}\n` : '') +
        (extra.length ? `    extra:   ${extra.join(', ')}\n` : '')
    );
    return false;
  }
  return true;
}

// ── 1. The two Swift copies must be identical ─────────────────────────────
// They are one file duplicated because the Watch app and the Expo module are
// separate compilation units. Any difference is by definition a mistake.
{
  const watch = read(PATHS.swiftWatch);
  const phone = read(PATHS.swiftPhone);
  if (watch !== phone) {
    failures.push(
      'Swift wire models differ between the Watch target and the iPhone module.\n' +
        '    Copy targets/watch/WorkoutWireModels.swift over\n' +
        '    modules/sara-workout-native/ios/WorkoutWireModels.swift.'
    );
  }
}

// ── 2. Schema version ─────────────────────────────────────────────────────
{
  const swift = read(PATHS.swiftWatch).match(/saraWorkoutSchemaVersion\s*=\s*(\d+)/)?.[1];
  const ts = read(PATHS.ts).match(/WORKOUT_SCHEMA_VERSION\s*=\s*(\d+)/)?.[1];
  const py = read(PATHS.pyService).match(/^SCHEMA_VERSION\s*=\s*(\d+)/m)?.[1];
  if (!(swift && ts && py)) {
    failures.push(`Could not read schema version (swift=${swift} ts=${ts} py=${py}).`);
  } else if (!(swift === ts && ts === py)) {
    failures.push(`Schema version mismatch: swift=${swift} ts=${ts} python=${py}.`);
  }
}

// ── 3. Command kinds ──────────────────────────────────────────────────────
{
  const swiftBlock = read(PATHS.swiftWatch).match(
    /enum WorkoutCommandKind: String, Codable \{([\s\S]*?)\n\}/
  )?.[1];
  // `case logSet = "log_set"` and bare `case complete` (raw value == name).
  const swiftKinds = [...(swiftBlock ?? '').matchAll(/case\s+(\w+)(?:\s*=\s*"([^"]+)")?/g)].map(
    (m) => m[2] ?? m[1]
  );

  const tsBlock = read(PATHS.ts).match(/export type WorkoutCommandKind =([\s\S]*?);/)?.[1];
  const tsKinds = [...(tsBlock ?? '').matchAll(/'([a-z_]+)'/g)].map((m) => m[1]);

  const pyBlock = read(PATHS.pyService).match(/MUTATING_KINDS = \{([\s\S]*?)\}/)?.[1];
  const pyKinds = [...(pyBlock ?? '').matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);

  check('Command kinds: Swift vs TypeScript', swiftKinds, tsKinds);
  check('Command kinds: TypeScript vs Python', tsKinds, pyKinds);
}

// ── 4. Wire message kinds ─────────────────────────────────────────────────
// Device-to-device only, so the backend has no copy to compare against.
{
  const swiftBlock = read(PATHS.swiftWatch).match(
    /public init\?\(rawValue: String\) \{([\s\S]*?)\n {8}\}/
  )?.[1];
  const swiftKinds = [...(swiftBlock ?? '').matchAll(/case "([a-z_]+)":/g)].map((m) => m[1]);

  const tsSource = read(PATHS.ts);
  const tsKinds = ['WATCH_TO_PHONE_KINDS', 'PHONE_TO_WATCH_KINDS'].flatMap((name) => {
    const block = tsSource.match(new RegExp(`${name} = \\[([\\s\\S]*?)\\]`))?.[1] ?? '';
    return [...block.matchAll(/'([a-z_]+)'/g)].map((m) => m[1]);
  });

  check('Wire message kinds: Swift vs TypeScript', swiftKinds, tsKinds);
}

// ── 5. Projection field names ─────────────────────────────────────────────
// The keys actually crossing the wire — where a silent rename hurts most.
{
  const swiftBlock = read(PATHS.swiftWatch).match(
    /public struct WorkoutProjection[\s\S]*?enum CodingKeys: String, CodingKey \{([\s\S]*?)\n {4}\}/
  )?.[1] ?? '';
  const swiftKeys = [];
  for (const line of swiftBlock.split('\n')) {
    const explicit = line.match(/case\s+\w+\s*=\s*"([^"]+)"/);
    if (explicit) {
      swiftKeys.push(explicit[1]);
      continue;
    }
    const bare = line.match(/case\s+([\w,\s]+)$/);
    if (bare) swiftKeys.push(...bare[1].split(',').map((s) => s.trim()).filter(Boolean));
  }

  const tsBlock = read(PATHS.ts).match(
    /export interface WorkoutProjection \{([\s\S]*?)\n\}/
  )?.[1] ?? '';
  // Track brace depth: `healthkit?: { state: ... }` is an inline object type,
  // and its members are not projection fields.
  const tsKeys = [];
  let depth = 0;
  for (const raw of tsBlock.split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('//') || line.startsWith('*') || line.startsWith('/*')) continue;
    const key = depth === 0 ? line.match(/^([a-z_]+)\??:/)?.[1] : null;
    if (key) tsKeys.push(key);
    depth += (line.match(/\{/g) ?? []).length - (line.match(/\}/g) ?? []).length;
  }

  // Python builds the projection as a dict literal; take its top-level keys.
  const pySource = read(PATHS.pyService);
  const pyStart = pySource.indexOf('proj: Dict[str, Any] = {');
  const pyBlock = pyStart >= 0 ? pySource.slice(pyStart, pySource.indexOf('\n        }', pyStart)) : '';
  const pyKeys = [...pyBlock.matchAll(/^ {12}"([a-z_]+)":/gm)].map((m) => m[1]);
  // `exercises` is attached conditionally after the literal (compact form).
  if (/proj\["exercises"\]/.test(pySource)) pyKeys.push('exercises');

  check('Projection fields: Swift vs TypeScript', swiftKeys, tsKeys);
  check('Projection fields: TypeScript vs Python', tsKeys, pyKeys);
}

// ── 6. Exercise field names ───────────────────────────────────────────────
// approved_weight vs calculated_suggestion IS the approval boundary (§6.8):
// a rename here would leave the UI reading `undefined` and lifting whatever
// the fallback happened to be. All three copies are compared.
{
  const swiftBlock = read(PATHS.swiftWatch).match(
    /public struct WorkoutExercise[\s\S]*?enum CodingKeys: String, CodingKey \{([\s\S]*?)\n {4}\}/
  )?.[1] ?? '';
  const swiftKeys = [];
  for (const line of swiftBlock.split('\n')) {
    const explicit = line.match(/case\s+\w+\s*=\s*"([^"]+)"/);
    if (explicit) {
      swiftKeys.push(explicit[1]);
      continue;
    }
    const bare = line.match(/case\s+([\w,\s]+)$/);
    if (bare) swiftKeys.push(...bare[1].split(',').map((s) => s.trim()).filter(Boolean));
  }

  const tsBlock = read(PATHS.ts).match(
    /export interface ProjectionExercise \{([\s\S]*?)\n\}/
  )?.[1] ?? '';
  const tsKeys = tsBlock
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('//') && !l.startsWith('*') && !l.startsWith('/*'))
    .map((l) => l.match(/^([a-z_]+)\??:/)?.[1])
    .filter(Boolean);

  const pySource = read(PATHS.pyService);
  const pyStart = pySource.indexOf('def _exercise_view');
  const pyBlock = pyStart >= 0 ? pySource.slice(pyStart) : '';
  const pyKeys = [...pyBlock.matchAll(/^ {8}"([a-z_]+)":/gm)].map((m) => m[1]);

  // TypeScript is the superset the phone renders from; Swift may legitimately
  // omit fields the Watch has no room for (e.g. metric_type). So: TS must match
  // Python exactly, and Swift must be a subset of both.
  check('Exercise fields: TypeScript vs Python', tsKeys, pyKeys);

  const swiftOnly = swiftKeys.filter((k) => !pyKeys.includes(k) || !tsKeys.includes(k));
  if (swiftOnly.length) {
    failures.push(
      `Exercise fields declared in Swift but absent from TypeScript/Python: ${swiftOnly.join(', ')}`
    );
  }

  for (const required of ['approved_weight', 'calculated_suggestion']) {
    const where = [
      swiftKeys.includes(required) ? null : 'Swift',
      tsKeys.includes(required) ? null : 'TypeScript',
      pyKeys.includes(required) ? null : 'Python',
    ].filter(Boolean);
    if (where.length) {
      failures.push(`Approval-boundary field "${required}" is missing from: ${where.join(', ')}.`);
    }
  }
}

// ── 7. Conflict codes the clients branch on ───────────────────────────────
{
  const pySource = read(PATHS.pyService);
  const tsSource = read(PATHS.ts);
  const tsBlock = tsSource.match(/export type WorkoutConflictCode =([\s\S]*?);/)?.[1] ?? '';
  const tsCodes = [...tsBlock.matchAll(/'([a-z_]+)'/g)].map((m) => m[1]);

  const pyCodes = [...pySource.matchAll(/WorkoutConflict\(\s*\n?\s*"([a-z_]+)"/g)].map((m) => m[1]);
  const routeCodes = [...read(PATHS.pyRoutes).matchAll(/"code": "([a-z_]+)"/g)].map((m) => m[1]);
  const allPy = [...new Set([...pyCodes, ...routeCodes])];

  const unhandled = allPy.filter((c) => !tsCodes.includes(c));
  if (unhandled.length) {
    failures.push(
      `Backend raises conflict codes the client does not declare: ${unhandled.join(', ')}`
    );
  }
}

// ── Report ────────────────────────────────────────────────────────────────
if (failures.length) {
  console.error('\n✗ Workout wire contract has drifted:\n');
  for (const f of failures) console.error('  ' + f);
  console.error('');
  process.exit(1);
}

console.log('✓ Workout wire contract is consistent across Swift, TypeScript and Python.');
