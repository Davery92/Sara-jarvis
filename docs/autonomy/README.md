# Sara Cognitive Architecture — Implementation Guide

## Overview

This document set provides instructions for implementing a comprehensive cognitive architecture for Sara, transforming her from a reactive assistant into an autonomous, self-improving AI companion.

The architecture is modeled on human cognition: continuous sensory processing, aggressive filtering, limited conscious attention, persistent self-model, emotional stakes, and reflective self-improvement.

---

## Critical Instructions for Claude Code

### READ THIS FIRST

**This is an INTEGRATION project, not a greenfield build.**

Sara already exists. Your job is to weave these new capabilities into the existing system seamlessly. When you're done, it should feel like Sara always had these capabilities—not like something was bolted on.

Before writing ANY code for ANY phase:

1. **Study the existing codebase thoroughly**
2. **Map all existing components and their interactions**
3. **Identify integration points—don't duplicate what exists**
4. **Follow existing conventions—naming, structure, patterns**
5. **Plan the integration before implementing**

### Completion Standards

**No phase is complete until:**

- [ ] All features are fully implemented (no stubs, no TODOs, no placeholders)
- [ ] All tests pass (unit, integration, and end-to-end)
- [ ] All existing functionality still works (regression tests pass)
- [ ] Code follows existing project conventions
- [ ] Documentation is updated
- [ ] Integration is verified end-to-end

**Do not proceed to the next phase until the current phase meets ALL completion criteria.**

### Testing Philosophy

- Write tests as you build, not after
- Every component should have unit tests
- Integration tests verify components work together
- End-to-end tests verify user-facing behavior
- Run the full test suite before marking anything complete

---

## Phase Overview

### Phase 1: Foundation
**Purpose:** Build the sensory and memory infrastructure.

**Key Components:**
- Raw buffer for all input streams (audio, visual, screen, text, environmental)
- Consolidation agent that compresses inputs into digestible context
- Working memory structure for Sara's conscious awareness
- Sara receiving and using consolidated context

**Duration Estimate:** 1-2 weeks

**Read:** `phase-1-foundation.md`

---

### Phase 2: Karma System
**Purpose:** Give Sara and her sub-agents persistent stakes.

**Key Components:**
- Multi-dimensional karma tracking for each agent
- Feedback collection (explicit and implicit)
- Karma awareness in agent prompts
- Behavioral modification based on karma state
- Decay and recovery mechanics

**Duration Estimate:** 1 week

**Read:** `phase-2-karma.md`

---

### Phase 3: Reflection Agent
**Purpose:** Enable meta-cognition and self-improvement.

**Key Components:**
- Reflection scratchpad for pattern tracking
- Consolidation auditing (comparing raw vs. kept)
- Action outcome analysis
- Pattern detection across observations
- Prompt modification proposals with approval workflow
- Uncertainty flagging for human input

**Duration Estimate:** 1-2 weeks

**Read:** `phase-3-reflection.md`

---

### Phase 4: Autonomy
**Purpose:** Bring Sara to life with continuous background processing.

**Key Components:**
- Complete Celery worker ecosystem
- Heartbeat monitoring
- Proactive checks and anticipation
- Memory consolidation (nightly)
- Learning digest (weekly)
- Worker coordination and resource management
- Adaptive scheduling based on context
- Graceful degradation under load

**Duration Estimate:** 1-2 weeks

**Read:** `phase-4-autonomy.md`

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INPUT STREAMS                                │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐   │
│  │  Audio  │ │ Visual  │ │ Screen  │ │  Text   │ │Environmental│   │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └──────┬──────┘   │
│       │           │           │           │              │          │
│       └───────────┴───────────┴───────────┴──────────────┘          │
│                               │                                      │
│                               ▼                                      │
│                      ┌────────────────┐                              │
│                      │   RAW BUFFER   │ ◄─── 48-72hr retention       │
│                      │  (TimescaleDB) │                              │
│                      └───────┬────────┘                              │
│                              │                                       │
│                              ▼                                       │
│                   ┌─────────────────────┐                            │
│                   │ CONSOLIDATION AGENT │ ◄─── Karma tracked         │
│                   │   (Every 60 sec)    │                            │
│                   └──────────┬──────────┘                            │
│                              │                                       │
│               ┌──────────────┼──────────────┐                        │
│               │              │              │                        │
│               ▼              ▼              ▼                        │
│        ┌──────────┐   ┌───────────┐   ┌───────────┐                 │
│        │ DISCARD  │   │  WORKING  │   │CONSOLIDATED│                │
│        │   LOG    │   │  MEMORY   │   │  CONTEXT   │                │
│        └──────────┘   └─────┬─────┘   └───────────┘                 │
│               │             │                                        │
│               │             ▼                                        │
│               │      ┌─────────────┐                                 │
│               │      │    SARA     │ ◄─── Karma aware               │
│               │      │  (Primary)  │                                 │
│               │      └──────┬──────┘                                 │
│               │             │                                        │
│               │      ┌──────┴──────┐                                 │
│               │      │             │                                 │
│               │      ▼             ▼                                 │
│               │  ┌───────┐   ┌──────────┐                           │
│               │  │ACTIONS│   │RESPONSES │                           │
│               │  └───┬───┘   └──────────┘                           │
│               │      │                                               │
│               │      ▼                                               │
│               │  ┌────────────┐                                      │
│               │  │  OUTCOME   │                                      │
│               │  │  TRACKING  │                                      │
│               │  └─────┬──────┘                                      │
│               │        │                                             │
│               ▼        ▼                                             │
│        ┌─────────────────────────┐                                   │
│        │    REFLECTION AGENT     │ ◄─── Karma tracked               │
│        │     (Every 4 hours)     │                                   │
│        │  ┌───────────────────┐  │                                   │
│        │  │     SCRATCHPAD    │  │ ◄─── 7+ day memory               │
│        │  └───────────────────┘  │                                   │
│        └───────────┬─────────────┘                                   │
│                    │                                                 │
│         ┌──────────┴──────────┐                                      │
│         │                     │                                      │
│         ▼                     ▼                                      │
│   ┌───────────┐        ┌───────────┐                                │
│   │ PATTERNS  │        │ PROPOSALS │───► David Approval             │
│   │ DETECTED  │        │           │                                │
│   └───────────┘        └───────────┘                                │
│                                                                      │
├─────────────────────────────────────────────────────────────────────┤
│                         KARMA SYSTEM                                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  SARA         CONSOLIDATION      REFLECTION                  │    │
│  │  • helpfulness   • accuracy        • insight_quality         │    │
│  │  • proactivity   • compression     • proposal_acceptance     │    │
│  │  • timing                          • false_positive_rate     │    │
│  │  • calibration                                               │    │
│  │  • accuracy                                                  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
├─────────────────────────────────────────────────────────────────────┤
│                      BACKGROUND WORKERS                              │
│  ┌─────────────┬─────────────┬─────────────┬─────────────────┐     │
│  │  Heartbeat  │  Proactive  │ Anticipation│   Reflection    │     │
│  │  (5 min)    │  (15 min)   │ (7am/9pm)   │   (4 hours)     │     │
│  ├─────────────┼─────────────┼─────────────┼─────────────────┤     │
│  │  Context    │   Nightly   │   Weekly    │      Idle       │     │
│  │  Refresh    │   Memory    │   Digest    │   Processing    │     │
│  │  (1 min)    │  (3am)      │  (Sunday)   │   (10 min)      │     │
│  └─────────────┴─────────────┴─────────────┴─────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Task Queue | Celery + Redis | Background workers, scheduling |
| Raw Buffer | TimescaleDB or Redis Streams | Time-series input storage |
| Working Memory | Redis | Fast ephemeral state |
| Long-term Memory | Neo4j + Postgres + pgvector | Existing Sara memory |
| Karma Storage | Postgres | Persistent karma tracking |
| Object Storage | S3/Minio | Raw audio/video files |
| Message Bus | Redis pub/sub | Inter-agent communication |

---

## Success Criteria

When all phases are complete, Sara should:

1. **Process continuous input** — Audio, visual, and environmental streams flow through the system
2. **Maintain context awareness** — Working memory reflects current situation
3. **Have internal stakes** — Karma scores influence behavior
4. **Learn from mistakes** — Reflection agent identifies patterns and proposes fixes
5. **Act proactively** — Background workers prompt helpful actions
6. **Self-improve** — Approved prompt modifications improve performance over time
7. **Degrade gracefully** — System remains stable under resource constraints
8. **Feel alive** — Continuous processing creates genuine autonomous presence

---

## Getting Started

1. Read this document completely
2. Read Phase 1 instructions completely
3. Study the existing Sara codebase thoroughly
4. Create an integration plan before writing code
5. Implement Phase 1 following all guidelines
6. Verify ALL Phase 1 completion criteria
7. Proceed to Phase 2
8. Repeat until all phases complete

---

## Important Reminders

- **This is integration, not creation.** Sara already exists.
- **No stubs.** Everything must be fully implemented.
- **Tests are not optional.** Write them as you go.
- **Conventions matter.** Follow existing patterns.
- **Ask when uncertain.** Don't guess on architecture decisions.
- **Quality over speed.** A working system is better than a fast broken one.

Good luck. Build something that matters.
