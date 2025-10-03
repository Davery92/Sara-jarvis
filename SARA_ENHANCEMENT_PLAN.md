# Sara Living AI Assistant Enhancement Plan

**Goal**: Transform Sara from a reactive chatbot into a proactive, contextually-aware AI companion similar to Cortana, with full mobile support.

---

## Phase 1: Foundation & Mobile Support (Week 1-2)

### 1.1 Mobile-First Responsive Design
**Priority**: HIGH | **Complexity**: Medium

**Implementation:**
- [ ] Audit current components for mobile responsiveness
- [ ] Implement mobile navigation (hamburger menu, bottom nav bar)
- [ ] Optimize sprite for mobile (smaller, corner placement, tap interactions)
- [ ] Add touch gestures (swipe, long-press, pinch-to-zoom for graphs)
- [ ] Create mobile-optimized layouts for:
  - Chat interface (full screen, keyboard-aware)
  - Notes (mobile editor, markdown preview toggle)
  - Calendar (week/day views for small screens)
  - Jarvis mode (collapsible panels, swipeable sections)
  - Knowledge graph (pinch-zoom, tap to expand nodes)

**Technical Details:**
```typescript
// Frontend: Add mobile detection and responsive hooks
// src/hooks/useMobileDetection.ts
export const useMobileDetection = () => {
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [isTablet, setIsTablet] = useState(window.innerWidth >= 768 && window.innerWidth < 1024);
  // Listen for resize, orientation change
}

// src/components/MobileNav.tsx - Bottom navigation bar
// src/components/SpriteInteractive.tsx - Mobile sprite interactions
```

**Files to modify:**
- `frontend/src/App-interactive.tsx` - Add mobile layout switching
- `frontend/src/components/*` - Make all components responsive
- `frontend/src/styles/` - Add mobile-first CSS utilities
- Add PWA manifest updates for better mobile install experience

---

### 1.2 Conversation Threading System
**Priority**: HIGH | **Complexity**: Medium

**Implementation:**
- [ ] Database schema: Add `conversation_thread` table
- [ ] Thread management: Create, resume, archive, search threads
- [ ] UI: Thread sidebar, thread switching, thread history
- [ ] Context preservation: Load thread context into chat
- [ ] Thread intelligence: Auto-naming based on content

**Database Schema:**
```sql
CREATE TABLE conversation_thread (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR NOT NULL REFERENCES app_user(id),
    title VARCHAR NOT NULL,
    summary TEXT,
    auto_generated BOOLEAN DEFAULT false,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    message_count INTEGER DEFAULT 0,
    tags TEXT[],
    archived BOOLEAN DEFAULT false,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE CASCADE
);

CREATE TABLE episode_thread_mapping (
    episode_id VARCHAR REFERENCES episode(id),
    thread_id VARCHAR REFERENCES conversation_thread(id),
    PRIMARY KEY (episode_id, thread_id)
);

CREATE INDEX idx_thread_user_activity ON conversation_thread(user_id, last_activity DESC);
CREATE INDEX idx_thread_tags ON conversation_thread USING GIN(tags);
```

**Backend API:**
```python
# app/routes/threads.py
POST   /threads                    # Create new thread
GET    /threads                    # List threads (with pagination, filters)
GET    /threads/{id}               # Get thread details + episodes
PUT    /threads/{id}               # Update thread (rename, add tags)
DELETE /threads/{id}               # Archive/delete thread
POST   /threads/{id}/resume        # Load thread context into chat
GET    /threads/search             # Search across all threads
POST   /threads/{id}/summarize     # AI-generated thread summary
```

**Frontend Components:**
```typescript
// src/components/ThreadSidebar.tsx - Thread list and management
// src/components/ThreadHeader.tsx - Current thread display
// src/components/ThreadSearch.tsx - Search interface
// src/hooks/useThreadContext.tsx - Thread state management
```

---

## Phase 2: Proactive Intelligence (Week 3-4)

### 2.1 Enhanced Contextual Awareness Service
**Priority**: HIGH | **Complexity**: High

**Current state**: Basic awareness service exists but has errors (episode.meta column missing)

**Implementation:**
- [ ] Fix contextual awareness service (remove meta column dependency)
- [ ] Add contextual insight generation (pattern detection)
- [ ] Implement insight scoring and ranking
- [ ] Create insight delivery system (non-intrusive notifications)
- [ ] Add user feedback loop (mark insights as helpful/not helpful)

**Enhanced Service:**
```python
# app/services/contextual_awareness_service.py - Expand existing

class InsightType(Enum):
    PATTERN_DETECTED = "pattern"           # "You usually code backend on Tuesdays"
    CONTEXT_SUGGESTION = "context"         # "Related to your work last week"
    ANTICIPATORY = "anticipatory"          # "Meeting in 30 min, here's context"
    REMINDER = "reminder"                  # "You mentioned wanting to refactor this"
    CONNECTION = "connection"              # "This relates to 3 other projects"
    WARNING = "warning"                    # "System health issue detected"
    CELEBRATION = "celebration"            # "You solved 5 bugs today!"

class ContextualInsight:
    type: InsightType
    title: str
    description: str
    priority: int  # 1-10
    related_entities: List[Dict]  # Notes, events, conversations, code
    action_suggestions: List[str]
    expires_at: datetime

# New insight generators:
- pattern_analyzer: Detect work patterns, habits
- meeting_prep_generator: Pre-meeting context gathering
- code_change_analyzer: Analyze git commits, suggest docs
- relationship_mapper: Find connections across data
- workload_balancer: Suggest breaks, prioritization
```

**Database Schema:**
```sql
CREATE TABLE contextual_insight (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR NOT NULL REFERENCES app_user(id),
    type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    description TEXT,
    priority INTEGER DEFAULT 5,
    related_entities JSONB,  -- {notes: [...], events: [...], threads: [...]}
    action_suggestions JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,
    dismissed_at TIMESTAMP WITH TIME ZONE,
    user_feedback VARCHAR  -- 'helpful', 'not_helpful', 'irrelevant'
);

CREATE INDEX idx_insight_user_priority ON contextual_insight(user_id, priority DESC, created_at DESC);
CREATE INDEX idx_insight_delivered ON contextual_insight(user_id, delivered_at) WHERE dismissed_at IS NULL;
```

**Frontend Integration:**
```typescript
// src/components/InsightPanel.tsx - Floating insight cards
// src/components/InsightNotification.tsx - Non-intrusive notifications
// src/hooks/useInsights.tsx - Real-time insight streaming
```

---

### 2.2 Meeting Preparation Intelligence
**Priority**: MEDIUM | **Complexity**: Medium

**Implementation:**
- [ ] Pre-meeting context gatherer (15-30 min before events)
- [ ] Relevant notes finder (semantic search)
- [ ] Past conversation retrieval
- [ ] Participant history (if team calendar)
- [ ] Auto-generated meeting brief

**Service:**
```python
# app/services/meeting_prep_service.py

class MeetingPrepService:
    async def prepare_for_meeting(self, event_id: str, user_id: str) -> MeetingBrief:
        event = get_event(event_id)

        # Gather context
        related_notes = semantic_search_notes(event.title + event.description)
        related_conversations = search_threads(event.title)
        previous_meetings = find_similar_events(event.title, past_30_days=True)

        # Generate brief
        brief = {
            "event": event,
            "context": {
                "related_notes": related_notes[:5],
                "past_discussions": related_conversations[:3],
                "previous_meetings": previous_meetings,
                "suggested_topics": extract_topics(related_notes)
            },
            "prepared_at": datetime.now()
        }

        # Create notification
        notify_user(f"📋 Meeting prep ready: {event.title}")

        return brief
```

---

### 2.3 Pattern Recognition & Personal Learning
**Priority**: MEDIUM | **Complexity**: High

**Implementation:**
- [ ] Work pattern analyzer (time-of-day, day-of-week patterns)
- [ ] Topic clustering (what user works on)
- [ ] Productivity metrics (code velocity, bug fix rate)
- [ ] Personal preferences learning (notification timing, detail level)
- [ ] Behavioral adaptation (adjust proactivity based on feedback)

**Service:**
```python
# app/services/pattern_learning_service.py

class PatternLearningService:
    def analyze_work_patterns(self, user_id: str) -> Dict:
        # Analyze episodes, events, notes by time
        patterns = {
            "peak_hours": detect_peak_productivity_hours(),
            "focus_days": detect_deep_work_days(),
            "common_topics": cluster_work_topics(),
            "interruption_tolerance": learn_notification_preferences(),
            "work_style": classify_work_style()  # "deep focus", "context switching", etc.
        }
        return patterns

    def suggest_optimal_scheduling(self, task_type: str) -> List[TimeSlot]:
        # Suggest when to schedule based on patterns
        pass
```

**Database Schema:**
```sql
CREATE TABLE user_pattern (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR NOT NULL REFERENCES app_user(id),
    pattern_type VARCHAR NOT NULL,  -- 'peak_hours', 'focus_topic', 'work_style'
    pattern_data JSONB NOT NULL,
    confidence FLOAT DEFAULT 0.5,  -- 0-1 confidence score
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_validated TIMESTAMP WITH TIME ZONE
);
```

---

## Phase 3: Knowledge Intelligence (Week 5-6)

### 3.1 Expanded Knowledge Graph Integration
**Priority**: HIGH | **Complexity**: High

**Current**: Basic Neo4j integration exists

**Implementation:**
- [ ] Auto-populate graph from all data sources
- [ ] Relationship discovery algorithm
- [ ] Graph-based recommendations
- [ ] Visual knowledge map UI
- [ ] Temporal relationship tracking (how connections evolve)

**Neo4j Schema Expansion:**
```cypher
// Node types (expand existing)
(:User {id, name, email})
(:Note {id, title, content, created_at})
(:Thread {id, title, summary})
(:Event {id, title, starts_at})
(:Insight {id, type, priority})
(:Topic {name, cluster_id})
(:Project {name, description})
(:Code {file_path, language, last_modified})

// Relationship types
[:DISCUSSES]     // User-Thread-Topic
[:RELATES_TO]    // Note-Note, Note-Event
[:MENTIONS]      // Thread-Note, Thread-Event
[:WORKS_ON]      // User-Project-Time
[:DISCOVERED]    // Insight-Relationship
[:SIMILAR_TO]    // Topic-Topic (semantic similarity)
[:PRECEDES]      // Event-Event (temporal)
[:REFERENCES]    // Note-Code (existing)
```

**Graph Intelligence Service:**
```python
# app/services/graph_intelligence_service.py

class GraphIntelligenceService:
    async def discover_relationships(self, user_id: str):
        """Find non-obvious connections in user's data"""

        # Semantic similarity connections
        notes = get_all_notes(user_id)
        for n1, n2 in combinations(notes, 2):
            similarity = semantic_similarity(n1.content, n2.content)
            if similarity > 0.7:
                create_relationship(n1, n2, "SIMILAR_TO", weight=similarity)

        # Temporal patterns
        events = get_calendar_events(user_id)
        detect_recurring_patterns(events)

        # Cross-domain connections
        link_conversations_to_code_changes()
        link_notes_to_calendar_topics()

    async def get_connected_context(self, entity_id: str, depth: int = 2) -> Dict:
        """Get all related context for an entity"""
        query = """
        MATCH (start {id: $entity_id})-[*1..{depth}]-(connected)
        RETURN connected, relationships
        """
        # Return full context graph

    async def suggest_connections(self, entity_id: str) -> List[SuggestedConnection]:
        """AI-powered connection suggestions"""
        # Use embeddings + graph structure to suggest connections
```

**Frontend Visualization:**
```typescript
// src/components/KnowledgeMap.tsx - Interactive 3D/2D knowledge graph
// - D3.js force-directed graph (existing)
// - Add: Timeline view (temporal relationships)
// - Add: Topic clusters view
// - Add: Connection suggestions UI
// - Add: Graph filtering (by type, date, strength)
```

---

### 3.2 Project Intelligence Layer
**Priority**: MEDIUM | **Complexity**: Medium

**Implementation:**
- [ ] Auto-detect projects from notes/conversations/code
- [ ] Project timeline tracking
- [ ] Project health monitoring
- [ ] Cross-project insights

**Database Schema:**
```sql
CREATE TABLE project (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR NOT NULL REFERENCES app_user(id),
    name VARCHAR NOT NULL,
    description TEXT,
    auto_detected BOOLEAN DEFAULT false,
    status VARCHAR DEFAULT 'active',  -- active, paused, completed
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    tags TEXT[],
    metadata JSONB  -- custom fields
);

CREATE TABLE project_entity_link (
    project_id VARCHAR REFERENCES project(id),
    entity_type VARCHAR NOT NULL,  -- 'note', 'thread', 'event', 'code'
    entity_id VARCHAR NOT NULL,
    relevance_score FLOAT DEFAULT 1.0,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (project_id, entity_type, entity_id)
);
```

**Backend Service:**
```python
# app/services/project_intelligence_service.py

class ProjectIntelligenceService:
    async def detect_projects(self, user_id: str) -> List[Project]:
        """Use topic clustering to detect implicit projects"""
        # Cluster notes/threads by semantic similarity
        # Identify recurring themes
        # Create project entities

    async def get_project_health(self, project_id: str) -> ProjectHealth:
        """Analyze project activity, momentum, blockers"""
        return {
            "activity_trend": "increasing",  # or "stable", "declining"
            "last_activity": "2 hours ago",
            "momentum_score": 0.8,  # 0-1
            "blockers": ["Waiting on API documentation"],
            "suggestions": ["Schedule focus time for implementation"]
        }

    async def get_project_timeline(self, project_id: str) -> Timeline:
        """Visual timeline of all project activity"""
        # All notes, conversations, events, code changes
```

---

## Phase 4: Autonomous Behaviors (Week 7-8)

### 4.1 Background Intelligence Workers
**Priority**: HIGH | **Complexity**: High

**Current**: Some workers exist (nightly_dream, contextual_awareness)

**Implementation:**
- [ ] Code change monitor (watch git, analyze diffs)
- [ ] System health monitor (docker stats, DB performance)
- [ ] Documentation generator (auto-create/update docs from code)
- [ ] Security scanner integration (vulnerability watch enhancement)
- [ ] Dead link checker (notes, external references)
- [ ] Backup validator (ensure data safety)

**Worker Architecture:**
```python
# app/workers/autonomous_workers.py

class CodeChangeMonitor(BaseWorker):
    """Monitor code changes and provide insights"""
    interval = timedelta(minutes=15)

    async def execute(self):
        changes = get_recent_git_commits()
        for commit in changes:
            # Analyze commit
            complexity = analyze_code_complexity(commit)
            test_coverage = check_test_coverage(commit)
            breaking_changes = detect_breaking_changes(commit)

            # Generate insights
            if complexity.score > 0.8:
                create_insight("High complexity commit - consider refactor")
            if test_coverage.delta < 0:
                create_insight("Test coverage decreased")

class SystemHealthMonitor(BaseWorker):
    """Monitor system resources and health"""
    interval = timedelta(minutes=5)

    async def execute(self):
        # Docker container stats
        containers = docker_client.containers.list()
        for container in containers:
            stats = container.stats(stream=False)
            memory_pct = calculate_memory_percentage(stats)
            cpu_pct = calculate_cpu_percentage(stats)

            if memory_pct > 85:
                create_insight(
                    type="WARNING",
                    title=f"{container.name} high memory usage",
                    priority=8
                )

        # Database performance
        slow_queries = analyze_db_performance()
        if slow_queries:
            create_insight("Detected slow database queries")

class DocumentationGenerator(BaseWorker):
    """Auto-generate documentation from code"""
    interval = timedelta(hours=6)

    async def execute(self):
        # Analyze code structure
        api_endpoints = parse_fastapi_routes()
        database_schema = parse_sqlalchemy_models()

        # Generate markdown docs
        api_docs = generate_api_documentation(api_endpoints)
        schema_docs = generate_schema_documentation(database_schema)

        # Create/update notes
        update_or_create_note(
            title="API Documentation (Auto-generated)",
            content=api_docs,
            folder="Documentation",
            auto_generated=True
        )
```

---

### 4.2 Predictive Assistance
**Priority**: MEDIUM | **Complexity**: High

**Implementation:**
- [ ] Next action predictor (what user likely to do next)
- [ ] Bug prediction (similar pattern to past bugs)
- [ ] Resource optimization suggestions
- [ ] Deadline risk assessment
- [ ] Collaboration suggestions (based on topics)

**Service:**
```python
# app/services/predictive_service.py

class PredictiveAssistanceService:
    async def predict_next_action(self, user_id: str, context: Dict) -> List[SuggestedAction]:
        """Predict what user might want to do next"""

        # Analyze current context
        current_thread = context.get("thread")
        last_messages = get_recent_messages(current_thread, limit=5)
        current_time = datetime.now()
        work_patterns = get_user_patterns(user_id)

        # Pattern matching
        if "bug" in last_messages and current_time.hour < 12:
            return [
                SuggestedAction("Search similar bugs in notes", probability=0.8),
                SuggestedAction("Check recent code changes", probability=0.7),
                SuggestedAction("Review error logs", probability=0.6)
            ]

    async def predict_bug_likelihood(self, code_diff: str) -> BugPrediction:
        """Predict if code change might introduce bugs"""

        # Analyze against historical bug patterns
        similar_past_bugs = find_similar_code_patterns(code_diff)
        complexity_score = calculate_cyclomatic_complexity(code_diff)

        if similar_past_bugs and complexity_score > 10:
            return BugPrediction(
                likelihood=0.75,
                reason="Similar pattern to bug fixed in commit abc123",
                suggestions=["Add error handling", "Increase test coverage"]
            )

    async def assess_deadline_risk(self, project_id: str) -> DeadlineRisk:
        """Assess risk of missing project deadline"""

        project = get_project(project_id)
        velocity = calculate_project_velocity(project_id)
        remaining_work = estimate_remaining_work(project_id)

        estimated_completion = datetime.now() + (remaining_work / velocity)

        if estimated_completion > project.deadline:
            return DeadlineRisk(
                risk_level="HIGH",
                estimated_completion=estimated_completion,
                suggestions=[
                    "Reduce scope by 20%",
                    "Add 2 focus days this week",
                    "Defer documentation to post-launch"
                ]
            )
```

---

## Phase 5: Personality & Character (Week 9-10)

### 5.1 Enhanced Sprite System
**Priority**: HIGH | **Complexity**: Medium

**Current**: Sprite exists with basic animations

**Implementation:**
- [ ] Expand emotion states (thinking → analyzing, discovering, celebrating, concerned, focused)
- [ ] Context-aware animations (different states for different situations)
- [ ] Interactive sprite (click for quick actions, status info)
- [ ] Sprite speech bubbles (brief contextual messages)
- [ ] Achievement celebrations (milestone animations)

**Enhanced Sprite Component:**
```typescript
// src/components/SaraSprite.tsx

export enum SpriteState {
  IDLE = 'idle',
  LISTENING = 'listening',
  THINKING = 'thinking',
  ANALYZING = 'analyzing',      // Deep analysis
  DISCOVERING = 'discovering',   // Found insight
  CELEBRATING = 'celebrating',   // Achievement unlocked
  CONCERNED = 'concerned',       // Warning/error
  FOCUSED = 'focused',           // Deep work mode
  EXCITED = 'excited',           // Interesting discovery
  SLEEPING = 'sleeping',         // Quiet hours
}

interface SpriteProps {
  state: SpriteState;
  message?: string;              // Brief speech bubble
  onClick?: () => void;          // Interactive actions
  achievements?: Achievement[];  // Show achievement badges
  contextualHint?: string;      // Tooltip with context
}

// Animation mapping
const animations = {
  discovering: 'pulse-glow',
  celebrating: 'bounce-confetti',
  concerned: 'shake-amber',
  analyzing: 'rotate-scan',
  // ... etc
}
```

**Contextual State Logic:**
```typescript
// Auto-switch sprite state based on context
const determineSpriteState = (context: AppContext): SpriteState => {
  if (context.hasWarning) return SpriteState.CONCERNED;
  if (context.newInsightGenerated) return SpriteState.DISCOVERING;
  if (context.userAchievement) return SpriteState.CELEBRATING;
  if (context.aiThinking) return SpriteState.ANALYZING;
  if (context.quietHours) return SpriteState.SLEEPING;
  return SpriteState.IDLE;
}
```

---

### 5.2 Rapport & Relationship Building
**Priority**: MEDIUM | **Complexity**: Medium

**Implementation:**
- [ ] Shared history tracking ("We've solved X bugs together")
- [ ] Milestone celebrations (productivity achievements)
- [ ] Inside jokes / references (contextual humor)
- [ ] Loyalty indicators (relationship score)
- [ ] Personalized greetings (time of day, recent activity)

**Database Schema:**
```sql
CREATE TABLE user_relationship (
    user_id VARCHAR PRIMARY KEY REFERENCES app_user(id),
    relationship_score FLOAT DEFAULT 0.0,  -- 0-100
    days_together INTEGER DEFAULT 0,
    total_conversations INTEGER DEFAULT 0,
    bugs_solved_together INTEGER DEFAULT 0,
    notes_created_together INTEGER DEFAULT 0,
    shared_milestones JSONB,  -- [{type: "bug_solved", count: 50, date: ...}]
    inside_references JSONB,  -- [{phrase: "the great calendar bug", context: ...}]
    last_interaction TIMESTAMP WITH TIME ZONE
);

CREATE TABLE achievement (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR REFERENCES app_user(id),
    type VARCHAR NOT NULL,  -- 'productivity', 'milestone', 'learning', 'collaboration'
    title VARCHAR NOT NULL,
    description TEXT,
    icon VARCHAR,  -- emoji or icon name
    earned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    celebrated BOOLEAN DEFAULT false
);
```

**Rapport Service:**
```python
# app/services/rapport_service.py

class RapportService:
    async def get_relationship_status(self, user_id: str) -> RelationshipStatus:
        rel = get_user_relationship(user_id)
        return RelationshipStatus(
            score=rel.relationship_score,
            level=calculate_relationship_level(rel.score),  # "new", "familiar", "trusted", "partner"
            days_together=rel.days_together,
            achievements=get_recent_achievements(user_id),
            next_milestone=calculate_next_milestone(rel)
        )

    async def generate_contextual_greeting(self, user_id: str) -> str:
        """Generate personalized greeting"""
        rel = get_user_relationship(user_id)
        patterns = get_user_patterns(user_id)
        current_time = datetime.now()

        # Time-aware
        if current_time.hour < 12:
            base = "Good morning"
        elif current_time.hour < 18:
            base = "Good afternoon"
        else:
            base = "Good evening"

        # Context-aware
        last_context = get_last_conversation_topic(user_id)
        if last_context:
            return f"{base}! Ready to continue with {last_context}?"

        # Achievement-aware
        recent_achievement = get_latest_unannounced_achievement(user_id)
        if recent_achievement:
            return f"{base}! 🎉 You earned '{recent_achievement.title}'!"

        # Pattern-aware
        if patterns.peak_hours and current_time.hour in patterns.peak_hours:
            return f"{base}! It's your peak productivity time - let's make it count!"

        return f"{base}! How can I assist you today?"

    async def detect_achievement(self, user_id: str, event_type: str, metadata: Dict):
        """Detect and award achievements"""

        # Examples:
        if event_type == "bug_solved":
            bugs_solved = count_bugs_solved(user_id)
            if bugs_solved == 10:
                award_achievement(user_id, "Bug Hunter", "Solved 10 bugs!")
            if bugs_solved == 50:
                award_achievement(user_id, "Exterminator", "Solved 50 bugs!")

        if event_type == "note_created":
            notes = count_notes(user_id)
            if notes == 100:
                award_achievement(user_id, "Knowledge Builder", "Created 100 notes!")
```

---

### 5.3 Adaptive Communication Style
**Priority**: LOW | **Complexity**: Medium

**Implementation:**
- [ ] Learn preferred detail level (verbose vs concise)
- [ ] Adjust technical depth based on user's expertise
- [ ] Vary response tone based on context (formal, casual, encouraging)
- [ ] Adapt notification frequency/timing
- [ ] Remember communication preferences

**Service:**
```python
# app/services/communication_adapter.py

class CommunicationAdapter:
    async def adapt_response(self, response: str, user_id: str, context: Dict) -> str:
        """Adapt AI response to user preferences"""

        prefs = get_communication_preferences(user_id)

        # Detail level
        if prefs.detail_level == "concise":
            response = summarize_response(response)
        elif prefs.detail_level == "verbose":
            response = expand_response(response)

        # Tone adjustment
        if context.get("user_frustrated"):
            response = add_encouraging_tone(response)
        elif context.get("celebration"):
            response = add_enthusiastic_tone(response)

        # Technical depth
        if prefs.technical_level == "expert":
            response = add_technical_details(response)
        else:
            response = simplify_technical_terms(response)

        return response

    async def learn_from_feedback(self, user_id: str, response_id: str, feedback: str):
        """Learn communication preferences from user feedback"""

        # If user says "too long", adjust detail_level
        # If user asks for clarification, increase technical depth
        # etc.
```

---

## Phase 6: Rich Interactions & UI (Week 11-12)

### 6.1 Command Palette / Quick Actions
**Priority**: HIGH | **Complexity**: Low

**Implementation:**
- [ ] Keyboard shortcut to open (Cmd+K / Ctrl+K)
- [ ] Fuzzy search across all actions
- [ ] Context-aware suggestions
- [ ] Recent actions
- [ ] Natural language commands

**Component:**
```typescript
// src/components/CommandPalette.tsx

interface Command {
  id: string;
  title: string;
  description?: string;
  icon?: string;
  keywords: string[];
  action: () => void;
  category: 'navigation' | 'create' | 'search' | 'ai' | 'system';
}

const commands: Command[] = [
  // Navigation
  { id: 'goto-notes', title: 'Go to Notes', keywords: ['notes', 'knowledge'], action: () => navigate('/notes') },
  { id: 'goto-calendar', title: 'Go to Calendar', keywords: ['calendar', 'events', 'schedule'], action: () => navigate('/calendar') },

  // Creation
  { id: 'new-note', title: 'Create Note', keywords: ['new', 'create', 'note'], action: () => createNote() },
  { id: 'new-event', title: 'Create Event', keywords: ['new', 'event', 'meeting'], action: () => createEvent() },
  { id: 'new-thread', title: 'New Conversation', keywords: ['chat', 'thread', 'talk'], action: () => createThread() },

  // AI Commands
  { id: 'ask-sara', title: 'Ask Sara...', keywords: ['ask', 'sara', 'ai', 'help'], action: () => focusChat() },
  { id: 'summarize-day', title: 'Summarize my day', keywords: ['summary', 'recap', 'today'], action: () => generateDailySummary() },
  { id: 'find-related', title: 'Find related content', keywords: ['related', 'connections', 'similar'], action: () => findRelated() },

  // Search
  { id: 'search-notes', title: 'Search notes...', keywords: ['search', 'find', 'notes'], action: () => openNoteSearch() },
  { id: 'search-conversations', title: 'Search conversations...', keywords: ['search', 'chat', 'history'], action: () => openThreadSearch() },
];

// Contextual commands based on current view
const getContextualCommands = (currentView: string): Command[] => {
  if (currentView === 'note-editor') {
    return [
      { title: 'Link to note...', action: () => showNoteLinkPicker() },
      { title: 'Add to project...', action: () => showProjectPicker() },
      { title: 'Generate summary', action: () => aiSummarizeNote() },
    ];
  }
  // ... etc
}
```

---

### 6.2 Dashboard / Command Center
**Priority**: MEDIUM | **Complexity**: Medium

**Implementation:**
- [ ] Unified dashboard view (Cortana-style HUD)
- [ ] System status widgets
- [ ] Quick stats (conversations, notes, achievements)
- [ ] Recent activity feed
- [ ] Upcoming events/reminders
- [ ] Active insights
- [ ] Customizable layout

**Component:**
```typescript
// src/components/Dashboard.tsx

interface Widget {
  id: string;
  type: 'stats' | 'activity' | 'calendar' | 'insights' | 'graph' | 'quick-actions';
  position: { x: number; y: number; w: number; h: number };
  config: any;
}

const defaultWidgets: Widget[] = [
  { id: 'stats', type: 'stats', position: { x: 0, y: 0, w: 4, h: 2 }, config: {} },
  { id: 'activity', type: 'activity', position: { x: 4, y: 0, w: 4, h: 4 }, config: { limit: 10 } },
  { id: 'insights', type: 'insights', position: { x: 0, y: 2, w: 4, h: 3 }, config: { priority: 6 } },
  { id: 'calendar', type: 'calendar', position: { x: 8, y: 0, w: 4, h: 4 }, config: { view: 'week' } },
];

// Widgets:
// - StatsWidget: Conversations, notes, achievements, relationship score
// - ActivityWidget: Real-time activity feed
// - InsightsWidget: Active contextual insights
// - CalendarWidget: Upcoming events
// - GraphWidget: Mini knowledge graph
// - QuickActionsWidget: Most used actions
```

---

### 6.3 Rich Notifications & Modals
**Priority**: MEDIUM | **Complexity**: Low

**Implementation:**
- [ ] Notification center (history of all notifications)
- [ ] Rich notification cards (not just text)
- [ ] Interactive notifications (quick actions)
- [ ] Notification preferences (per-type settings)
- [ ] Smart batching (group similar notifications)

**Component:**
```typescript
// src/components/NotificationCenter.tsx

interface RichNotification {
  id: string;
  type: 'insight' | 'achievement' | 'reminder' | 'system' | 'collaboration';
  title: string;
  body: string;
  icon?: string;
  image?: string;  // Screenshot, graph visualization, etc.
  actions?: NotificationAction[];  // Quick action buttons
  priority: 1 | 2 | 3;  // 1=low, 2=medium, 3=high
  delivered_at: Date;
  read: boolean;
  dismissed: boolean;
}

interface NotificationAction {
  label: string;
  action: () => void;
  primary?: boolean;
}

// Example rich notification:
{
  type: 'insight',
  title: 'Meeting Preparation Ready',
  body: 'I found 3 related notes and 2 past conversations for your 2pm meeting.',
  icon: '📋',
  actions: [
    { label: 'View Context', action: () => openMeetingPrep(), primary: true },
    { label: 'Dismiss', action: () => dismiss() }
  ],
  priority: 2
}
```

---

## Phase 7: Advanced Mobile Features (Week 13-14)

### 7.1 Mobile-Specific Interactions
**Priority**: HIGH | **Complexity**: Medium

**Implementation:**
- [ ] Offline mode (PWA with service worker)
- [ ] Push notifications (via PWA)
- [ ] Quick capture (voice memo, photo to note)
- [ ] Gesture navigation (swipe, long-press shortcuts)
- [ ] Mobile widget (iOS/Android home screen)
- [ ] Share to Sara (from other apps)

**PWA Enhancements:**
```javascript
// frontend/public/sw.js (service worker)

// Offline caching strategy
self.addEventListener('fetch', event => {
  if (event.request.url.includes('/api/')) {
    // Network-first for API calls
    event.respondWith(
      fetch(event.request)
        .then(response => {
          cache.put(event.request, response.clone());
          return response;
        })
        .catch(() => cache.match(event.request))
    );
  } else {
    // Cache-first for assets
    event.respondWith(
      cache.match(event.request)
        .then(response => response || fetch(event.request))
    );
  }
});

// Background sync for offline actions
self.addEventListener('sync', event => {
  if (event.tag === 'sync-notes') {
    event.waitUntil(syncOfflineNotes());
  }
});

// Push notifications
self.addEventListener('push', event => {
  const data = event.data.json();
  self.registration.showNotification(data.title, {
    body: data.body,
    icon: '/pwa-192x192.png',
    badge: '/badge-72x72.png',
    actions: data.actions || []
  });
});
```

**Quick Capture:**
```typescript
// src/components/mobile/QuickCapture.tsx

// Voice memo to note
const captureVoiceMemo = async () => {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  // Record, transcribe, create note
}

// Photo to note
const capturePhoto = async () => {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.capture = 'environment';
  // Upload, OCR, create note
}

// Quick note widget
const QuickNoteWidget = () => {
  // Floating action button
  // Tap to instantly create note
  // Voice or text input
}
```

---

### 7.2 Mobile Optimizations
**Priority**: HIGH | **Complexity**: Medium

**Implementation:**
- [ ] Lazy loading (progressive content loading)
- [ ] Image optimization (WebP, lazy load, responsive)
- [ ] Bundle splitting (code splitting by route)
- [ ] Reduce bundle size (tree shaking, compression)
- [ ] Virtual scrolling (for long lists)
- [ ] Touch-friendly UI (larger tap targets, spacing)

**Performance Optimization:**
```typescript
// Lazy load routes
const Notes = lazy(() => import('./components/NotesKnowledgeGarden'));
const Calendar = lazy(() => import('./components/CalendarView'));
const Chat = lazy(() => import('./components/ChatInterface'));

// Virtual scrolling for long lists
import { FixedSizeList } from 'react-window';

const NotesList = ({ notes }) => (
  <FixedSizeList
    height={600}
    itemCount={notes.length}
    itemSize={80}
  >
    {({ index, style }) => (
      <NoteItem note={notes[index]} style={style} />
    )}
  </FixedSizeList>
);
```

---

## Phase 8: Polish & Integration (Week 15-16)

### 8.1 End-to-End Workflows
**Priority**: HIGH | **Complexity**: Medium

**Implementation:**
- [ ] Morning routine workflow (brief → priorities → focus mode)
- [ ] Meeting workflow (prep → notes during → follow-up)
- [ ] Research workflow (gather → organize → synthesize)
- [ ] Problem-solving workflow (define → explore → solve → document)
- [ ] End-of-day workflow (summary → plan tomorrow → wind down)

**Example: Morning Routine:**
```python
# app/workflows/morning_routine.py

class MorningRoutineWorkflow:
    async def execute(self, user_id: str):
        # 1. Generate daily brief
        brief = await daily_brief_service.generate_brief(user_id)

        # 2. Analyze calendar for the day
        events = await calendar_service.get_today_events(user_id)

        # 3. Suggest priorities
        priorities = await predictive_service.suggest_priorities(user_id, brief, events)

        # 4. Generate meeting prep for first meeting
        if events:
            first_meeting = events[0]
            prep = await meeting_prep_service.prepare_for_meeting(first_meeting.id, user_id)

        # 5. Check system health
        health = await system_health_service.check_all()

        # 6. Compile morning package
        return MorningPackage(
            brief=brief,
            priorities=priorities,
            events=events,
            meeting_prep=prep,
            system_status=health,
            greeting=rapport_service.generate_greeting(user_id)
        )
```

---

### 8.2 Refinement & Bug Fixes
**Priority**: HIGH | **Complexity**: Variable

**Implementation:**
- [ ] Cross-browser testing
- [ ] Mobile device testing (iOS, Android)
- [ ] Performance profiling and optimization
- [ ] Accessibility improvements (ARIA, keyboard navigation)
- [ ] Error handling and graceful degradation
- [ ] Loading states and skeleton screens
- [ ] Edge case handling

---

### 8.3 Documentation & Onboarding
**Priority**: MEDIUM | **Complexity**: Low

**Implementation:**
- [ ] Interactive tutorial (first-time user experience)
- [ ] Feature discovery tooltips
- [ ] Help documentation (searchable, contextual)
- [ ] Video walkthroughs
- [ ] Keyboard shortcut reference
- [ ] FAQ / troubleshooting guide

**Onboarding Flow:**
```typescript
// src/components/Onboarding.tsx

const onboardingSteps = [
  {
    target: '.chat-interface',
    title: 'Meet Sara',
    content: 'Sara is your AI companion. Ask questions, get insights, and let her help you stay organized.',
    spotlightClicks: true,
  },
  {
    target: '.sprite',
    title: 'Sara\'s Avatar',
    content: 'Watch Sara\'s expressions change as she works. Click for quick actions and status.',
  },
  {
    target: '.command-palette-trigger',
    title: 'Command Palette (⌘K)',
    content: 'Press ⌘K anytime to quickly navigate, search, or take actions.',
  },
  // ... more steps
];
```

---

## Implementation Priority Matrix

### Must Have (P0) - Weeks 1-8
1. ✅ Mobile responsive design
2. ✅ Conversation threading
3. ✅ Enhanced contextual awareness
4. ✅ Knowledge graph expansion
5. ✅ Background intelligence workers
6. ✅ Enhanced sprite system

### Should Have (P1) - Weeks 9-14
1. Meeting preparation intelligence
2. Command palette
3. Dashboard/command center
4. Rich notifications
5. Mobile PWA features
6. Pattern recognition

### Nice to Have (P2) - Weeks 15-16
1. Project intelligence
2. Predictive assistance
3. Rapport system
4. Adaptive communication
5. End-to-end workflows

---

## Technical Architecture Updates

### Backend Service Organization
```
backend/app/
├── services/
│   ├── contextual_awareness_service.py (enhance existing)
│   ├── meeting_prep_service.py (new)
│   ├── pattern_learning_service.py (new)
│   ├── graph_intelligence_service.py (enhance existing)
│   ├── project_intelligence_service.py (new)
│   ├── predictive_service.py (new)
│   ├── rapport_service.py (new)
│   └── communication_adapter.py (new)
├── workers/
│   ├── autonomous_workers.py (new)
│   ├── code_change_monitor.py (new)
│   ├── system_health_monitor.py (new)
│   └── documentation_generator.py (new)
├── workflows/
│   ├── morning_routine.py (new)
│   ├── meeting_workflow.py (new)
│   └── research_workflow.py (new)
└── routes/
    ├── threads.py (new)
    ├── insights.py (new)
    ├── projects.py (new)
    └── achievements.py (new)
```

### Frontend Component Organization
```
frontend/src/
├── components/
│   ├── mobile/
│   │   ├── MobileNav.tsx (new)
│   │   ├── QuickCapture.tsx (new)
│   │   └── GestureHandler.tsx (new)
│   ├── threads/
│   │   ├── ThreadSidebar.tsx (new)
│   │   ├── ThreadHeader.tsx (new)
│   │   └── ThreadSearch.tsx (new)
│   ├── insights/
│   │   ├── InsightPanel.tsx (new)
│   │   ├── InsightCard.tsx (new)
│   │   └── InsightNotification.tsx (new)
│   ├── dashboard/
│   │   ├── Dashboard.tsx (new)
│   │   └── widgets/ (new)
│   ├── CommandPalette.tsx (new)
│   ├── NotificationCenter.tsx (new)
│   ├── SaraSprite.tsx (enhance existing)
│   └── KnowledgeMap.tsx (enhance existing)
├── hooks/
│   ├── useMobileDetection.ts (new)
│   ├── useThreadContext.ts (new)
│   ├── useInsights.ts (new)
│   └── useCommandPalette.ts (new)
└── workflows/ (new)
```

### Database Schema Summary
```
New tables:
- conversation_thread
- episode_thread_mapping
- contextual_insight
- user_pattern
- project
- project_entity_link
- user_relationship
- achievement
```

---

## Success Metrics

### User Engagement
- Daily active usage time
- Number of conversations per day
- Notes created per week
- Feature adoption rate

### Intelligence Quality
- Insight relevance score (user feedback)
- Prediction accuracy
- Pattern detection success rate
- Relationship discovery rate

### Mobile Experience
- Mobile vs desktop usage ratio
- Mobile task completion rate
- Offline usage stats
- PWA install rate

### Personality & Rapport
- User relationship score trend
- Achievement unlock rate
- Positive feedback ratio
- Feature discovery rate

---

## Risk Mitigation

### Performance Risks
- **Risk**: Too many background workers impact performance
- **Mitigation**: Implement worker throttling, use queues, monitor resource usage

### Complexity Risks
- **Risk**: Too many features overwhelm users
- **Mitigation**: Progressive disclosure, onboarding, feature flags, analytics

### Mobile Risks
- **Risk**: Poor mobile performance
- **Mitigation**: Aggressive optimization, lazy loading, bundle splitting, testing

### Intelligence Risks
- **Risk**: Insights are irrelevant or annoying
- **Mitigation**: User feedback loop, ML training, adjustable sensitivity, opt-out

---

## Development Workflow

### Week-by-week breakdown
- **Week 1-2**: Mobile foundation + threading
- **Week 3-4**: Contextual awareness + meeting prep
- **Week 5-6**: Knowledge graph + project intelligence
- **Week 7-8**: Background workers + predictive
- **Week 9-10**: Sprite enhancement + rapport
- **Week 11-12**: Command palette + dashboard
- **Week 13-14**: Mobile PWA features
- **Week 15-16**: Polish + workflows + documentation

### Daily development cycle
1. Morning: Review priorities, plan day
2. Implementation: Feature development
3. Testing: Manual + automated testing
4. Evening: Commit, document, prepare tomorrow

### Testing strategy
- Unit tests for all services
- Integration tests for workflows
- E2E tests for critical paths
- Mobile device testing (real devices)
- Performance benchmarking
- User acceptance testing

---

## Post-Launch Iteration

### Phase 9: Learning & Optimization (Ongoing)
- Collect user feedback
- Analyze usage patterns
- Optimize ML models
- Refine prediction algorithms
- Add community-requested features
- Performance optimization

### Phase 10: Advanced Features (Future)
- Team collaboration (multi-user)
- Integrations (GitHub, Jira, Slack, etc.)
- Custom workflows (user-defined)
- Plugin system (community extensions)
- Advanced analytics (productivity insights)
- Cross-device sync optimization

---

## Summary

This plan transforms Sara from a reactive chatbot into a **living AI companion** that:

✅ **Learns** your patterns and adapts to your style
✅ **Anticipates** your needs and prepares context
✅ **Discovers** connections across your knowledge
✅ **Celebrates** achievements and builds rapport
✅ **Assists** proactively with intelligence and automation
✅ **Works** seamlessly on mobile and desktop

The phased approach ensures steady progress while maintaining code quality and user experience. Each phase builds on the previous one, creating a cohesive, intelligent system that feels alive.

**Estimated timeline**: 16 weeks for core implementation
**Total effort**: ~640 hours (40 hours/week)
**Result**: A truly living AI assistant like Cortana from Halo
