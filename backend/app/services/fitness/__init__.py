"""Fitness Coach services (FITNESS_COACH_IMPLEMENTATION_PLAN §6).

This package deliberately re-exports nothing and imports nothing at module
load. The modules under it reach into `app.services.*`, `app.models.*` and
the database; importing them eagerly from here would make
`import app.services.fitness` a transitive import of half the backend, and
would give `data_access` a connection before any caller asked for one.

The directory existed before this work with no `__init__.py` and exactly one
orphaned module, `conversational.py` — an LLM-backed fitness-onboarding
question generator that nothing imported. Step 3 of the plan required an
explicit decision before adding this file, because creating the package is
what would have made the orphan importable. It was deleted: it had no
callers, it predated the structured athlete profile that now owns onboarding
data, and the plan's Step 23 explicitly removes "blanket repetitive check-in
questions" of the kind it generated.
"""
