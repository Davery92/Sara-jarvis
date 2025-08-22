# Habit Tracker Implementation Tasks

## Architecture Analysis & Integration Points

Your habit tracker spec aligns perfectly with Sara's existing architecture:

### ✅ Existing Infrastructure We Can Leverage
- **PostgreSQL + pgvector**: Already set up for habits tables
- **Neo4j**: Already integrated for knowledge graph
- **NTFY**: Already configured for vulnerability notifications
- **FastAPI + SQLAlchemy**: Existing patterns to follow
- **React + TypeScript + Tailwind**: UI framework ready
- **JWT Authentication**: Already implemented
- **Tool System**: Can integrate habits as AI tools
- **Streaming Chat**: Can provide habit coaching
- **Timer System**: Already exists for time-bound habits

### 🔧 New Components Needed
- Habit-specific database tables
- RRULE parsing and scheduling
- Streak calculation algorithms
- Background workers for automation
- React components for habit UI
- Neo4j schema extensions

---

## Implementation Task Breakdown

### Phase 1: Database Foundation (1-2 days)

#### Task 1.1: PostgreSQL Schema & Migrations
- [ ] Create Alembic migration for core habit tables:
  - `habits` (main habit definitions)
  - `habit_items` (checklist sub-items)
  - `habit_instances` (daily materialized instances)
  - `habit_logs` (completion entries)
  - `habit_streaks` (streak tracking)
  - `habit_links` (connections to notes/docs)
  - `event_outbox` (Neo4j sync queue)
- [ ] Add indexes for performance
- [ ] Create PostgreSQL functions for streak calculations

#### Task 1.2: SQLAlchemy Models
- [ ] Add habit models to `main_simple.py`
- [ ] Create Pydantic schemas for API requests/responses
- [ ] Add relationship mappings

#### Task 1.3: Neo4j Schema Setup
- [ ] Create Neo4j constraints for habit entities
- [ ] Design relationship patterns with existing Note/Document nodes
- [ ] Create Cypher templates for upsert operations

### Phase 2: Core Backend Logic (2-3 days)

#### Task 2.1: RRULE & Scheduling Engine
- [ ] Install `python-dateutil` for RRULE parsing
- [ ] Create `HabitScheduler` class:
  - Parse RRULE strings
  - Generate daily instances for next 30 days
  - Handle time windows and weekly frequency
  - Support pause/vacation periods
- [ ] Create background worker for nightly instance generation

#### Task 2.2: Progress & Logging System
- [ ] Implement progress calculation for each habit type:
  - Binary: simple done/not done
  - Quantitative: sum amounts vs target
  - Checklist: completed items / total items
  - Time-bound: integration with existing Timer system
- [ ] Create idempotent logging endpoint
- [ ] Add undo/edit functionality

#### Task 2.3: Streak Calculation Engine
- [ ] Implement streak algorithm with grace days
- [ ] Handle vacation/pause periods
- [ ] Add retro-logging within time windows
- [ ] Create streak update triggers

### Phase 3: API Endpoints (1-2 days)

#### Task 3.1: CRUD Operations
- [ ] `POST /habits` - Create habit with full validation
- [ ] `GET /habits` - List user's habits with filters
- [ ] `GET /habits/{id}` - Habit detail with streak/links
- [ ] `PATCH /habits/{id}` - Update habit configuration
- [ ] `DELETE /habits/{id}` - Delete with cascade cleanup

#### Task 3.2: Daily Operations
- [ ] `GET /habits/today` - Today's instances with progress
- [ ] `POST /habits/{id}/log` - Log completion with idempotency
- [ ] `DELETE /habit_logs/{log_id}` - Undo last log entry

#### Task 3.3: Management Operations
- [ ] `POST /habits/{id}/pause` - Pause habit for period
- [ ] `POST /habits/{id}/resume` - Resume paused habit
- [ ] `POST /habits/{id}/link` - Link to notes/documents
- [ ] `GET /habits/{id}/streak` - Current streak stats

#### Task 3.4: Insights & Analytics
- [ ] `GET /insights/habits` - Adherence stats and recommendations
- [ ] Add habit data to existing analytics dashboard

### Phase 4: Background Workers (1-2 days)

#### Task 4.1: Scheduler Worker
- [ ] Nightly job to generate habit instances
- [ ] Lazy creation for on-demand access
- [ ] Handle RRULE expansion and window assignment

#### Task 4.2: Streak Worker
- [ ] Real-time streak updates on logging
- [ ] Nightly streak maintenance at 23:55
- [ ] Grace period calculations

#### Task 4.3: NTFY Nudge Worker
- [ ] Nudge candidate identification:
  - Risk notifications (window closing)
  - Momentum notifications (streak continuation)
  - Accountability notifications (weekly goals)
- [ ] Throttling and quiet hours
- [ ] Witty message templates

#### Task 4.4: Neo4j Sync Worker
- [ ] Outbox pattern implementation
- [ ] Idempotent Neo4j upserts
- [ ] Habit-to-graph linking

### Phase 5: Frontend Components (2-3 days)

#### Task 5.1: Core Habit Components
- [ ] `HabitCardBinary` - Simple checkbox completion
- [ ] `HabitCardQuantitative` - Progress bar with quick-add buttons
- [ ] `HabitCardChecklist` - Sub-item checkboxes
- [ ] `HabitCardTime` - Timer integration with start button
- [ ] `ProgressRing` - Circular progress indicator
- [ ] `StreakPill` - Streak display with fire/ice indicators

#### Task 5.2: Today View Page
- [ ] `/habits/today` route in App-interactive.tsx
- [ ] Group habits by time windows
- [ ] Quick-add functionality (+8, +12, +16 buttons)
- [ ] Overall progress summary
- [ ] Integration with existing sidebar navigation

#### Task 5.3: Habit Management
- [ ] `HabitCreateWizard` - Multi-step creation flow:
  - Basic info (title, type)
  - Scheduling (RRULE builder)
  - Target/units/windows
  - Review and create
- [ ] `HabitDetail` page with:
  - History sparkline
  - Streak timeline
  - Linked notes/documents
  - Mini knowledge graph
- [ ] `HabitEdit` functionality

#### Task 5.4: RRULE Builder Component
- [ ] Visual weekly schedule picker
- [ ] X per week frequency selector
- [ ] Monthly options (by date/weekday)
- [ ] Time window configuration
- [ ] RRULE string preview

### Phase 6: Insights & Analytics (1 day)

#### Task 6.1: Insights Dashboard
- [ ] `/habits/insights` page
- [ ] Adherence charts (7/30/90 day views)
- [ ] Window success rate analysis
- [ ] Best/worst performing habits
- [ ] Streak leaderboards

#### Task 6.2: Recommendations Engine
- [ ] Rules-based suggestion system:
  - Window time adjustments
  - Target modifications
  - Habit bundling suggestions
- [ ] Weekly review digest generation

### Phase 7: Integration Features (1-2 days)

#### Task 7.1: Timer Integration
- [ ] Auto-complete time-bound habits when timer finishes
- [ ] Start timer from habit card
- [ ] Link existing timers to habits

#### Task 7.2: AI Chat Integration
- [ ] Add habit tools to existing AI tool registry:
  - Create habit
  - Log completion
  - Check today's progress
  - Get habit insights
- [ ] Habit coaching in chat conversations

#### Task 7.3: Knowledge Graph Integration
- [ ] Extend existing KnowledgeGraph component for habits
- [ ] Habit-to-note linking UI
- [ ] Graph queries for habit relationships

### Phase 8: NTFY & Notifications (1 day)

#### Task 8.1: NTFY Integration
- [ ] Extend existing NTFY service for habits
- [ ] Action button configuration
- [ ] Message template system with witty personality

#### Task 8.2: Notification Management
- [ ] User preference settings
- [ ] Quiet hours configuration
- [ ] Throttling controls

### Phase 9: Testing & Polish (1-2 days)

#### Task 9.1: Unit Tests
- [ ] RRULE parsing and scheduling
- [ ] Streak calculation algorithms
- [ ] Progress computation
- [ ] Nudge scoring logic

#### Task 9.2: Integration Tests
- [ ] API endpoint testing
- [ ] Timer completion → habit logging
- [ ] NTFY action → log endpoint
- [ ] Neo4j sync verification

#### Task 9.3: E2E Testing
- [ ] Complete user workflow testing
- [ ] Mobile responsiveness
- [ ] Performance optimization

---

## Configuration Decisions Needed

### Default Configurations (Can Modify Before Implementation)

1. **Instance Generation**: Single instance per day with window hint ✅
2. **Checklist Completion**: All items required by default ✅
3. **Retro Logging Window**: 24 hours ✅
4. **Grace Days Default**: 0 days ✅
5. **Weekly Frequency**: Treat as additional goal alongside RRULE ✅

### Custom Configurations for Your Environment

1. **Default Time Windows**: 
   - Morning: 06:00-12:00
   - Afternoon: 12:00-17:00  
   - Evening: 17:00-22:00

2. **NTFY Settings**:
   - Max 3 nudges/day total
   - Max 2 nudges/day per habit
   - Quiet hours: 22:00-07:00

3. **Witty Personality**: Maintain Sara's playful tone ✅

---

## Integration Points with Existing Sara Features

### Synergies
- **Memory System**: Habits create episodic memories for coaching
- **Notes**: Link habits to related notes for context
- **Documents**: Connect habits to research/guides
- **Timers**: Seamless integration for time-bound habits
- **Analytics**: Habit data enhances dashboard insights
- **Chat**: AI coaching based on habit patterns

### Minimal Conflicts
- **Navigation**: Add "Habits" to existing sidebar
- **Database**: New tables won't impact existing features
- **Worker Processes**: Isolated background jobs

---

## Questions for Clarification

1. **Priority Level**: Is this urgent for production or can we implement methodically?

2. **Migration Strategy**: Should we implement all habit types at once or start with binary habits?

3. **Neo4j Schema**: Do you want habits to connect to existing vulnerability reports and calendar events?

4. **AI Integration**: Should Sara proactively suggest habits based on notes/conversations?

5. **Mobile Experience**: Any specific mobile optimizations needed beyond responsive design?

6. **Health Integrations**: Priority level for step/sleep/water bridges mentioned in spec?

---

## Estimated Timeline

**Total Implementation**: 10-14 working days

- **Backend Core**: 4-5 days
- **Frontend UI**: 3-4 days  
- **Workers & Integration**: 2-3 days
- **Testing & Polish**: 1-2 days

**Parallel Development**: Backend and Frontend can be developed simultaneously after Phase 1 is complete.

Would you like me to start with the **database migrations and core models**, or would you prefer to adjust any of these tasks/priorities first?