# Fitness Module - Full Implementation Tasks

## Overview
Complete implementation plan for Sara's Fitness module with chat-first onboarding, adaptive planning, calendar sync, daily readiness assessment, and comprehensive in-workout tracking.

## Phase 1: Foundation & Data Layer

### 1.1 Database Schema
- [ ] Create Alembic migration for core fitness tables
  - `fitness_profiles` - user demographics, equipment, preferences, constraints
  - `fitness_goals` - goal types, targets, timeframes, status
  - `fitness_plans` - plan metadata, phases, weekly structure
  - `workouts` - session prescriptions with exercises, sets, reps, intensity
  - `workout_logs` - per-set actuals, timestamps, notes, flags
  - `morning_readiness` - HRV/RHR/sleep data, scores, recommendations
  - `exercise_library` - movement patterns, equipment requirements, substitutions
  - `movement_patterns` - categorization for substitution logic

### 1.2 Calendar Service Foundation
- [ ] Create calendar tables migration
  - `calendar_events` - id, user_id, title, start, end, rrule, source, metadata
  - Add foreign key relationship to workouts
- [ ] Implement calendar service endpoints
  - POST /calendar/events (single and bulk creation)
  - PATCH /calendar/events/:id (move/update)
  - POST /calendar/events/:id/complete
  - GET /calendar/events?source=fitness
- [ ] Add calendar integration to existing Sara system

### 1.3 Model Layer
- [ ] Create SQLAlchemy models in `backend/app/models/fitness_extended.py`
  - FitnessProfile, FitnessGoal, FitnessPlan
  - Workout, WorkoutLog, ExerciseLog
  - MorningReadiness, ReadinessAdjustment
  - CalendarEvent with workout relationship
- [ ] Add relationships and constraints
  - User → FitnessProfile (one-to-one)
  - FitnessPlan → Workouts (one-to-many)
  - Workout → CalendarEvent (one-to-one)

## Phase 2: LLM Tools & Onboarding

### 2.1 LLM Tool Implementation
- [ ] Create fitness tools in `backend/app/tools/fitness_advanced.py`
  - `save_profile(data)` - validate and persist user stats
  - `save_goals(data)` - persist fitness goals
  - `propose_plan(profile, goals)` - generate draft plan
  - `commit_plan(plan_id)` - finalize and schedule
  - `adjust_today(readiness)` - daily workout adjustments
- [ ] Add JSON schema validation for all tool inputs/outputs
- [ ] Register tools in tool registry

### 2.2 Onboarding Chat Flow
- [ ] Implement stateful chat handler for fitness onboarding
  - Redis session state management
  - Branching question logic based on responses
  - Progress checkpointing to database
- [ ] Create onboarding entry points
  - Settings → Start New Journey
  - Settings → Change Goals
- [ ] Implement plan review/edit UI before commit

### 2.3 Plan Templates Library
- [ ] Create plan template JSON structures
  - 3-day full body, 4-day upper/lower splits
  - 5-6 day PPL, kettlebell-only programs
  - Hybrid endurance programs
- [ ] Build phase progression patterns
  - Base → Build → Peak → Deload cycles
  - Microcycle patterns (3+1, 5+1)
- [ ] Implement substitution matrix
  - Movement pattern mappings
  - Equipment-based alternatives
  - Injury/constraint accommodations

## Phase 3: Daily Readiness System

### 3.1 Readiness Data Collection
- [ ] Create morning readiness intake endpoints
  - POST /fitness/readiness/daily
  - GET /fitness/readiness/history
- [ ] Implement HealthKit bridge (iOS)
  - HRV/RHR overnight collection
  - Sleep duration/quality metrics
  - Permission management UI
- [ ] Build manual entry fallback (web/Android)
  - Survey forms for energy/soreness/stress
  - Time availability input

### 3.2 Readiness Scoring Engine
- [ ] Implement baseline learning algorithm
  - 14-day EWMA for personal baselines
  - Normalization bands for HRV/RHR
- [ ] Create scoring calculation
  - 40% HRV, 20% RHR, 20% sleep, 20% subjective
  - Green (≥80), Yellow (60-79), Red (<60) thresholds
- [ ] Build adjustment rules engine
  - Green: normal progression
  - Yellow: -20-30% accessory volume
  - Red: swap to recovery or reschedule

### 3.3 Workout Adjustment Logic
- [ ] Implement adjustment application
  - Modify today's workout prescription
  - Update calendar event description
  - Generate adjustment changelog
- [ ] Create notification triggers
  - Morning readiness summary
  - Adjustment notifications
  - Pre-workout reminders

## Phase 4: In-Workout Experience

### 4.1 Workout State Machine
- [ ] Implement server-side state management
  - States: idle → warmup → working_set → resting → summary → completed
  - Transitions: skip, substitute, fail, pause/resume
  - Redis session storage with TTL
- [ ] Create state sync protocol
  - WebSocket or SSE for real-time updates
  - Optimistic UI with reconciliation
  - Offline queue with sync on reconnect

### 4.2 Core Workout UI Components
- [ ] Build Now Card component
  - Current exercise display
  - Set/rep/weight/RPE targets
  - Progress indicators
- [ ] Implement logging micro-sheet
  - Quick weight/reps input
  - RPE slider (1-10)
  - Pain/form/time flags
- [ ] Create rest timer system
  - Auto-start option
  - Adjustable duration (-30/+30)
  - Visual/haptic/audio cues

### 4.3 Advanced Workout Features
- [ ] Implement superset/circuit handling
  - A1/A2 stacked display
  - Circuit round tracking
  - Appropriate rest patterns
- [ ] Build substitution interface
  - Pattern-based filtering
  - Equipment availability
  - Quick one-tap selection
- [ ] Create autoregulation prompts
  - Triggered by high RPE trends
  - Failure handling
  - Time-based adjustments

### 4.4 Workout Summary
- [ ] Design summary screen
  - Sets completed vs planned
  - Personal records achieved
  - Total volume/time metrics
  - Readiness vs performance
- [ ] Implement post-workout actions
  - Add recovery session
  - Reschedule missed work
  - Share summary (future)

## Phase 5: Scheduling & Auto-Reflow

### 5.1 Push/Skip Handling
- [ ] Create push/skip endpoints
  - POST /fitness/workouts/:id/push
  - POST /fitness/workouts/:id/skip
- [ ] Implement constraint solver
  - 24-48h spacing rules
  - Pattern stacking avoidance
  - User blackout times
- [ ] Build reflow algorithm
  - 7-day search window
  - Constraint satisfaction
  - Floating workout handling

### 5.2 Schedule Management
- [ ] Create schedule view endpoints
  - GET /fitness/schedule/week
  - GET /fitness/schedule/month
- [ ] Implement deload cadence maintenance
  - Track phase progression
  - Allow ±1 week flexibility
  - Auto-adjust after multiple misses
- [ ] Build conflict resolution
  - Calendar conflict detection
  - Alternative slot suggestions
  - User approval workflow

## Phase 6: Integration & Polish

### 6.1 Notification System
- [ ] Integrate with ntfy service
  - Morning readiness alerts
  - Pre-workout reminders (45 min)
  - Missed session follow-ups
  - Adjustment notifications
- [ ] Create notification templates
  - Contextual messaging
  - Readiness-based content
  - Actionable CTAs

### 6.2 Neo4j Knowledge Graph
- [ ] Create fitness node types
  - User → Goal → Plan → Workout relationships
  - Movement pattern graph
  - Progress tracking nodes
- [ ] Implement graph analytics
  - Pattern detection
  - Performance correlations
  - Substitution recommendations

### 6.3 Privacy & Data Management
- [ ] Implement data export
  - JSON/CSV export formats
  - Workout history exports
  - Plan backup/restore
- [ ] Create deletion workflows
  - Clear fitness data
  - Reset onboarding
  - Disconnect HealthKit
- [ ] Add audit logging
  - Track data access
  - Log modifications
  - Privacy compliance

## Phase 7: Analytics & Insights

### 7.1 Performance Metrics
- [ ] Build analytics endpoints
  - GET /fitness/analytics/compliance
  - GET /fitness/analytics/performance
  - GET /fitness/analytics/readiness
- [ ] Implement metric calculations
  - Estimated 1RM tracking
  - Volume by pattern/muscle
  - Time variance analysis
- [ ] Create trend detection
  - 4-week rolling averages
  - Performance trajectories
  - Readiness correlations

### 7.2 Automatic Adjustments
- [ ] Build deload triggers
  - Elevated RPE patterns
  - HRV trend detection
  - Missed session thresholds
- [ ] Implement plan modifications
  - Automatic phase adjustments
  - Frequency recommendations
  - Intensity modulation

## Phase 8: Mobile & Voice (Future-Ready)

### 8.1 Apple Watch Companion
- [ ] Design watch app architecture
  - Mirror Now Card display
  - Crown weight/rep adjustment
  - Haptic feedback system
- [ ] Implement core features
  - Set logging
  - Rest timer
  - Quick notes via dictation

### 8.2 Voice Commands
- [ ] Define voice intent catalog
  - "Start workout"
  - "Log X kilos, Y reps, RPE Z"
  - "Start rest timer"
  - "Substitute exercise"
- [ ] Create voice processing pipeline
  - Intent recognition
  - Parameter extraction
  - Action execution

## Integration Points with Existing Sara

### Memory System
- [ ] Store workout completions as episodes
- [ ] Index exercise performance for RAG
- [ ] Link readiness patterns to memory

### Calendar Integration
- [ ] Extend existing calendar with fitness events
- [ ] Add workout-specific event metadata
- [ ] Sync with external calendars (future)

### Notification System
- [ ] Use existing ntfy integration
- [ ] Add fitness-specific topics
- [ ] Maintain notification preferences

### Frontend Architecture
- [ ] Add Fitness to main navigation
- [ ] Create fitness-specific routes
- [ ] Integrate with existing auth/state

### LLM Integration
- [ ] Extend dialogue worker for fitness
- [ ] Add fitness context to conversations
- [ ] Enable fitness-aware responses

## Testing Requirements

### Unit Tests
- [ ] Readiness scoring algorithms
- [ ] Adjustment rule engine
- [ ] Reflow constraint solver
- [ ] Plan template generation

### Integration Tests
- [ ] Onboarding flow end-to-end
- [ ] Calendar event creation/updates
- [ ] Workout state transitions
- [ ] Push/skip reflow scenarios

### Acceptance Tests
- [ ] AT-1: Complete onboarding → plan created
- [ ] AT-2: Green readiness → normal workout
- [ ] AT-3: Yellow readiness → reduced volume
- [ ] AT-4: Red readiness → session swap
- [ ] AT-5: Push/skip → successful reflow
- [ ] AT-6: Complete workout with all features
- [ ] AT-7: Offline logging → sync
- [ ] AT-8: Export/delete data

## Performance Requirements

### Latency Targets
- [ ] Set logging < 150ms
- [ ] Rest timer updates < 50ms
- [ ] Plan generation < 3s
- [ ] Reflow calculation < 1s

### Offline Support
- [ ] Queue workout logs locally
- [ ] Maintain timer state
- [ ] Sync on reconnection
- [ ] Conflict resolution

## Security & Compliance

### Data Protection
- [ ] Encrypt fitness data at rest
- [ ] Secure HealthKit credentials
- [ ] Audit data access
- [ ] GDPR compliance

### Permission Management
- [ ] Granular HealthKit permissions
- [ ] Revocable access tokens
- [ ] Clear consent flows
- [ ] Data retention policies

## Deployment Strategy

### Migration Plan
1. Deploy database migrations
2. Roll out calendar service
3. Enable onboarding flow
4. Activate readiness system
5. Launch workout tracking
6. Enable auto-reflow
7. Add analytics

### Feature Flags
- [ ] fitness_onboarding_enabled
- [ ] fitness_readiness_enabled
- [ ] fitness_workout_tracking_enabled
- [ ] fitness_auto_reflow_enabled
- [ ] fitness_analytics_enabled

### Rollback Strategy
- [ ] Database migration rollback scripts
- [ ] Feature flag kill switches
- [ ] Data export before changes
- [ ] User communication plan

## Documentation Requirements

### User Documentation
- [ ] Onboarding guide
- [ ] Workout tracking tutorial
- [ ] Readiness explanation
- [ ] Privacy/data guide

### Technical Documentation
- [ ] API documentation
- [ ] State machine diagrams
- [ ] Database schema docs
- [ ] Integration guides

## Success Metrics

### Key Metrics to Track
- [ ] Onboarding completion rate
- [ ] Daily active workout users
- [ ] Readiness check compliance
- [ ] Workout completion rate
- [ ] Plan adherence percentage
- [ ] User satisfaction scores

### Monitoring & Alerting
- [ ] Set up fitness-specific dashboards
- [ ] Configure performance alerts
- [ ] Track error rates
- [ ] Monitor API latencies