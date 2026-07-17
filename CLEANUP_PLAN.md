# Repo Cleanup Plan

Goal: remove bloat (stale docs, dead scripts, tracked data/junk), sanitize the public-facing
docs of private info, and push a clean tree. Everything deleted here remains recoverable in
git history — deletion from HEAD is not data loss.

Ground rules:
- Only cleanup changes are committed. The ~180 in-progress code changes (cardio, fleet,
  one-mind, surfaces work) stay uncommitted and untouched.
- A doc survives only if it is (a) current truth, (b) a live plan for unfinished work, or
  (c) read by running code. "Completed phase" reports and superseded plans are bloat.
- Data files (DB dumps, backups, uploaded PDFs) are untracked from git but left on disk.
- Design docs that are untracked and contain internal IPs stay untracked (local-only).

## Phase 1 — Root doc purge (~40 files deleted)

**Keep (live):** README.md, CLAUDE.md, DEV_SETUP.md, REFACTORING_PLAN.md,
ASSISTANT_EXPERIENCE_PLAN.md, THE_SYSTEM_DESIGN.md, THE_SYSTEM_ACTIVATION_PLAN.md,
CODE_MODE_DESIGN.md, GEOLOCATION_PLAN.md, SARA_100_PLAN.md, DESKTOP_JARVIS_OVERHAUL_PLAN.md,
PHENOMENAL_ASSISTANT_PLAN.md, CLEANUP_PLAN.md (this file).

**Keep (local-only, untracked — contain internal addresses):** ONE_MIND.md,
BRAIN_ALIGNMENT_PLAN.md, FLEET_DESIGN.md, SYSTEM_AUDIT_FIX_PLAN.md, SURFACES_DESIGN.md,
APP_AWARENESS_AND_RECIPE_LOOKUP_PLAN.md.

**Delete:** everything else at root — demo-era setup docs (READY, FINAL-SETUP, STATUS,
DEPLOYMENT, PRODUCTION_DEPLOYMENT, tasks, planning), completed-initiative reports
(all 6 FITNESS_*, PHASE_* summaries, SARA_UNLEASHED_*, VERIFICATION_RESULTS,
RATING_SYSTEM_IMPLEMENTATION, SESSION_CACHE_IMPLEMENTATION, AFTERNOON/SHORT_TERM summaries),
superseded plans (SARA_ENHANCEMENT_PLAN/ROADMAP, IMPLEMENTATION_ROADMAP,
ANTICIPATORY_INTELLIGENCE_PLAN, INTELLIGENCE_REDESIGN_TASKS, MEMORY_SYSTEM,
TASKS_HUMAN_MEMORY_STACK, TASKS_PLAN, SPRITE_HUD_SPEC, JARVIS_PHASE_SUMMARY,
JARVIS_DEPLOYMENT_GUIDE, TECHNICAL_README, OLLAMA_API_MIGRATION_NOTES,
DREAM_INSIGHTS_ANALYSIS, DATA_CONSISTENCY_INVESTIGATION_REPORT, HABIT_TRACKER_* — the
Habits vertical itself was deleted), and stale agent guidance duplicating CLAUDE.md
(AGENTS.md, IMPORTANT_DEVELOPMENT_NOTES.md).

## Phase 2 — docs/ purge

Delete completion reports: PHASE_2/3/4/5-style *_COMPLETE.md (9 files),
assistant-redesign-checklist.md. Keep reference/design docs and everything read by code
(`backend/app/tools/self_knowledge.py` loads the `sara_self_model_*.md` files — untouched).

## Phase 3 — Dead scripts and junk files (delete from repo and disk)

One-off investigation/migration scripts long since run: check_notes_db.py,
clean_dream_insights.py, inspect_dream_insights.py, verify_dream_cleaning.py,
cleanup_orphaned_neo4j_data.py, data_consistency_check.py, monitor_data_consistency.py,
fix_neo4j_init.py, setup_test_notes.py, frontend_habit_test.py (dead vertical).
Demo-era launchers: simple-demo.py, start-demo.sh, start-final.sh, start-sara.sh,
run-local.sh (contradicts the Docker-only rule), get-docker.sh.
Stray artifacts: temp.html, notes-temp.html, IMG_8706.jpg (personal photo),
hey_sara.onnx (root copy — the real one deploys to the Jetson, already gitignored there).
Relocate: test_acs_api_contracts.py, test_acs_directive_aliases.py → tests/.

## Phase 4 — Untrack data files (keep on disk)

sara_hub.db (pre-Postgres relic), dream_insights_backup_*.json, episodes_backup_*.json,
uploads/*.pdf (personal documents), logs/*.log, the whole tracked .tmp/ tree (41 files,
already deleted from the working tree). These were committed before the matching
.gitignore rules existed; tracked files ignore gitignore.

## Phase 5 — .gitignore hardening

Add: `.tmp/`, `/uploads/`, `/*.onnx`, `*_backup_*.json`, `/sara_hub.db` (belt-and-braces —
`*.db` exists but the file predated it).

## Phase 6 — README rewrite

Full rewrite: reflect the actual current system (One Mind kernel, episodic memory + PKG,
fitness/cardio, surfaces & artifacts studio, fleet agents, iOS app, Jetson voice, ACS
daemon), drop deleted features (habit tracker), keep every endpoint/credential as a
placeholder. Zero internal IPs, hostnames, or credentials.

## Phase 7 — CLAUDE.md sanitize

Replace internal IPs, the Postgres connection string, and the dead gpt-oss/LLM-endpoint
references with placeholders or env-var pointers. Real values live in .env (untracked)
and local memory, not in the repo.

## Phase 8 — Commit & push

Two commits, staging only cleanup paths, pushed to origin/assistant-experience-jarvis:
1. `chore: purge stale docs, dead scripts, and tracked data/junk`
2. `docs: rewrite README + sanitize CLAUDE.md (no private info)`

## Flagged, deliberately NOT done (needs David's call)

1. **Git history still contains everything** — the DB password, internal IPs, personal
   PDFs, sara_hub.db, and .git is 713MB. Removing files from HEAD does not remove them
   from history on GitHub. Real remediation: rotate the Postgres password + JWT secret,
   keep the repo private, and optionally rewrite history with `git filter-repo`
   (destructive force-push — do not do casually).
2. **~250 other tracked files still reference internal IPs** (docs/, deploy scripts,
   config defaults). A full sweep risks breaking runtime config and should be its own
   pass, starting with anything that ships in an image.
3. **forge-data/** (980 files, 5.8MB) kept — it's the synthetic-conversation training
   harness with its generation/validation tooling, not junk.
4. The 189-file in-progress working set needs committing on its own merits soon; this
   branch is ~320k lines ahead of main.
