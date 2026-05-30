"""Narrator — Sara's "System AI" persona module.

The narrator observes David's life via existing observation streams (git
webhooks, error logs, fitness/calendar tables, ACS daemon signals) and
emits short, in-character utterances on the SYSTEM_NARRATION_EMITTED
EventBus channel. Surfaces (desktop popup, iOS push, webapp ticker)
consume those events.

This module is intentionally distinct from conversational Sara: it
broadcasts, it does not converse.
"""
