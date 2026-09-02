#!/usr/bin/env node
/**
 * Food item wire-contract parity check
 * (SARA_INTELLIGENT_FOOD_LOGGING_PLAN_2026_08_16 §3.1, Stage A).
 *
 * The canonical food item v2 shape is written out three times — Python in the
 * backend, TypeScript in the iOS app, TypeScript on the web. They cannot
 * share code: different languages, different processes. That makes drift the
 * most likely way this silently breaks — rename a field in one copy and a
 * client either drops data or renders undefined with no error anywhere.
 *
 * Same discipline as check-workout-contract-parity.mjs: dependency-free, runs
 * on the Linux repo host, no Xcode/jest/install step.
 *
 *     node scripts/check-food-contract-parity.mjs
 *
 * Exit code 1 means the copies have diverged. Fix the source, not this script.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const repo = join(root, '..');

const PATHS = {
  py: join(repo, 'backend/app/schemas/food_item.py'),
  tsIos: join(root, 'src/services/foodContracts.ts'),
  tsWeb: join(repo, 'frontend/src/types/foodContracts.ts'),
  fixtures: join(repo, 'backend/app/schemas/fixtures/food_item_v2_examples.json'),
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

// ── 1. Schema version ──────────────────────────────────────────────────────
{
  const py = read(PATHS.py).match(/^FOOD_ITEM_SCHEMA_VERSION\s*=\s*(\d+)/m)?.[1];
  const tsIos = read(PATHS.tsIos).match(/FOOD_ITEM_SCHEMA_VERSION\s*=\s*(\d+)/)?.[1];
  const tsWeb = read(PATHS.tsWeb).match(/FOOD_ITEM_SCHEMA_VERSION\s*=\s*(\d+)/)?.[1];
  if (!(py && tsIos && tsWeb)) {
    failures.push(`Could not read schema version (python=${py} ios=${tsIos} web=${tsWeb}).`);
  } else if (!(py === tsIos && tsIos === tsWeb)) {
    failures.push(`Schema version mismatch: python=${py} ios=${tsIos} web=${tsWeb}.`);
  }
}

// ── 2. Field names ─────────────────────────────────────────────────────────
{
  // Python: class body lines shaped `field_name: Type = default` or
  // `field_name: Type` (Pydantic model), stopping at the closing of the
  // class (next top-level `class`/EOF).
  const pySource = read(PATHS.py);
  const pyClassStart = pySource.indexOf('class CanonicalFoodItemV2');
  const pyClassBody = pySource.slice(pyClassStart).split(/\nclass \w/)[0];
  const pyFields = [...pyClassBody.matchAll(/^ {4}(\w+):\s*[\w\[\]"' ,.]+/gm)]
    .map((m) => m[1])
    .filter((name) => name !== 'schema_version'); // compared separately above

  // TypeScript: `export interface CanonicalFoodItemV2 { ... }` member names.
  const extractTsFields = (source) => {
    const block = source.match(/export interface CanonicalFoodItemV2 \{([\s\S]*?)\n\}/)?.[1] ?? '';
    return block
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('//') && !l.startsWith('*'))
      .map((l) => l.match(/^(\w+)\??:/)?.[1])
      .filter(Boolean)
      .filter((name) => name !== 'schema_version');
  };

  const tsIosFields = extractTsFields(read(PATHS.tsIos));
  const tsWebFields = extractTsFields(read(PATHS.tsWeb));

  check('CanonicalFoodItemV2 fields: Python vs iOS TypeScript', pyFields, tsIosFields);
  check('CanonicalFoodItemV2 fields: iOS TypeScript vs web TypeScript', tsIosFields, tsWebFields);

  // ── 3. Fixtures use exactly the schema's fields ─────────────────────────
  const fixtures = JSON.parse(read(PATHS.fixtures));
  const allFields = new Set(['schema_version', ...pyFields]);
  for (const [key, value] of Object.entries(fixtures)) {
    if (key.startsWith('_') || key === 'schema_version') continue;
    const items = Array.isArray(value) ? value : [value];
    for (const item of items) {
      const itemFields = Object.keys(item);
      check(`Fixture "${key}" keys vs schema fields`, itemFields, [...allFields]);
    }
  }
}

// ── Report ────────────────────────────────────────────────────────────────
if (failures.length) {
  console.error('\n✗ Food item contract has drifted:\n');
  for (const f of failures) console.error('  ' + f);
  console.error('');
  process.exit(1);
}

console.log('✓ Food item v2 contract is consistent across Python, iOS TypeScript, and web TypeScript.');
