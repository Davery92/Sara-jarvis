# Phase 2: Karma System — Multi-Dimensional Performance Tracking

## Mission Statement

Build a comprehensive karma system that gives Sara and her sub-agents persistent internal stakes. This isn't gamification—it's creating genuine consequences for performance that shape behavior over time. Every agent must be aware of its karma and have that awareness influence its operation.

**Prerequisites:** Phase 1 must be fully complete with all integration tests passing.

---

## Critical Integration Requirements

### Before Writing Any Code

1. **Verify Phase 1 completion**
   - All input handlers operational
   - Raw buffer storing and expiring correctly
   - Consolidation agent running on schedule
   - Working memory integrated with Sara
   - All Phase 1 tests passing

2. **Map karma touchpoints**
   - Where does Sara make decisions that could be right or wrong?
   - Where does the consolidation agent make keep/discard decisions?
   - What existing feedback mechanisms exist (user ratings, corrections)?
   - How will karma be surfaced to each agent?

3. **Design feedback collection**
   - How will you detect "correct" vs "incorrect" outcomes?
   - What implicit signals indicate success/failure?
   - How will explicit feedback from David be captured?

---

## Phase 2 Deliverables

### 1. Karma Schema and Storage

**Purpose:** Persistent, queryable storage of karma scores with full history.

#### Core Schema

```sql
-- Agents being tracked
CREATE TABLE karma_agents (
    agent_id VARCHAR(50) PRIMARY KEY,
    agent_type VARCHAR(50) NOT NULL,  -- sara, consolidation, reflection
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- Karma dimensions per agent
CREATE TABLE karma_dimensions (
    dimension_id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) REFERENCES karma_agents(agent_id),
    dimension_name VARCHAR(100) NOT NULL,
    description TEXT,
    weight FLOAT DEFAULT 1.0,  -- For computing overall score
    
    UNIQUE(agent_id, dimension_name)
);

-- Current karma scores (denormalized for fast access)
CREATE TABLE karma_scores (
    score_id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) REFERENCES karma_agents(agent_id),
    dimension_name VARCHAR(100) NOT NULL,
    
    current_score FLOAT DEFAULT 50.0,  -- 0-100 scale, starts neutral
    trend FLOAT DEFAULT 0.0,           -- Rolling average of recent deltas
    
    last_updated TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(agent_id, dimension_name)
);

-- Full karma history (append-only)
CREATE TABLE karma_events (
    event_id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) REFERENCES karma_agents(agent_id),
    dimension_name VARCHAR(100) NOT NULL,
    
    delta FLOAT NOT NULL,              -- Change amount (+/-)
    new_score FLOAT NOT NULL,          -- Score after this event
    
    reason TEXT NOT NULL,              -- Human-readable explanation
    evidence_type VARCHAR(50),         -- feedback, automated, reflection, decay
    evidence_ids JSONB,                -- References to supporting data
    
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- For querying
    INDEX idx_karma_events_agent_time (agent_id, created_at DESC)
);

-- Karma thresholds and configuration
CREATE TABLE karma_config (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Default Configuration

```json
{
  "thresholds": {
    "critical_low": 20,
    "low": 35,
    "neutral": 50,
    "good": 65,
    "excellent": 80
  },
  "decay": {
    "enabled": true,
    "rate_per_day": 1.0,
    "target": 50,
    "min_score_for_decay": 55,
    "max_score_for_recovery": 45
  },
  "trend_window_hours": 72,
  "alert_on_critical": true
}
```

---

### 2. Karma Dimensions per Agent

#### Sara — Primary Cognitive Agent

| Dimension | Description | Positive Signals | Negative Signals |
|-----------|-------------|------------------|------------------|
| **helpfulness** | Did actions/responses actually help? | Explicit thanks, task completion confirmed, positive feedback | Corrections needed, "that's wrong", repeated asks |
| **proactivity** | Anticipated needs vs. just reacted | Alerts before problems, useful unprompted info | Missed obvious opportunities, always waiting for prompts |
| **timing** | Right information at the right time | Timely alerts, appropriate interruptions | Too early (annoying), too late (useless), wrong moment |
| **calibration** | When uncertain, was appropriately uncertain | Caveats matched actual uncertainty, asked when should | Overconfident errors, unnecessary hedging on clear things |
| **accuracy** | Factual correctness | Verified correct information | Factual errors, hallucinations, outdated info |

#### Consolidation Agent

| Dimension | Description | Positive Signals | Negative Signals |
|-----------|-------------|------------------|------------------|
| **accuracy** | Kept what mattered, discarded what didn't | Reflection confirms good decisions | Reflection finds missed important items |
| **compression_quality** | Summaries preserved meaning | Sara successfully acted on summaries | Details needed that were lost in summary |

#### Reflection Agent (added in Phase 3, schema ready now)

| Dimension | Description | Positive Signals | Negative Signals |
|-----------|-------------|------------------|------------------|
| **insight_quality** | Observations lead to real improvements | Accepted proposals improve outcomes | Proposals rejected or make things worse |
| **proposal_acceptance** | David approves suggestions | High approval rate | High rejection rate |
| **false_positive_rate** | Flags real problems | Flagged issues were actual issues | Flagged non-issues, crying wolf |

---

### 3. Karma Service Implementation

**Purpose:** Centralized service for all karma operations.

#### Core Interface

```python
class KarmaService:
    """
    Central service for karma management.
    All karma modifications MUST go through this service.
    """
    
    async def get_agent_karma(self, agent_id: str) -> AgentKarma:
        """
        Get complete karma state for an agent.
        Returns current scores, trends, and recent history.
        This is what gets injected into agent prompts.
        """
        pass
    
    async def record_event(
        self,
        agent_id: str,
        dimension: str,
        delta: float,
        reason: str,
        evidence_type: str,
        evidence_ids: list[str] = None
    ) -> KarmaEvent:
        """
        Record a karma-affecting event.
        Automatically updates current score and trend.
        Triggers alerts if thresholds crossed.
        """
        pass
    
    async def get_karma_dashboard(self) -> KarmaDashboard:
        """
        Get overview of all agents' karma for monitoring/display.
        """
        pass
    
    async def apply_decay(self) -> list[KarmaEvent]:
        """
        Apply time-based decay toward neutral.
        Run periodically (e.g., daily).
        Returns list of decay events applied.
        """
        pass
    
    async def get_dimension_history(
        self,
        agent_id: str,
        dimension: str,
        hours: int = 168  # 1 week
    ) -> list[KarmaEvent]:
        """
        Get history for specific dimension.
        Used for trend analysis and debugging.
        """
        pass
```

#### Karma Calculation Rules

```python
# Score bounds
MIN_SCORE = 0.0
MAX_SCORE = 100.0
STARTING_SCORE = 50.0

# Delta scaling based on current score
# Prevents runaway scores and enables recovery
def calculate_effective_delta(current_score: float, raw_delta: float) -> float:
    """
    Diminishing returns at extremes.
    Easier to recover from low scores.
    Harder to maintain very high scores.
    """
    if raw_delta > 0:
        # Positive delta: diminishing returns as score increases
        headroom = MAX_SCORE - current_score
        effective = raw_delta * (headroom / MAX_SCORE)
    else:
        # Negative delta: diminishing damage as score decreases
        floor_room = current_score - MIN_SCORE
        effective = raw_delta * (floor_room / MAX_SCORE)
    
    return effective

# Trend calculation
def calculate_trend(recent_events: list[KarmaEvent], window_hours: int) -> float:
    """
    Rolling average of recent deltas.
    Positive trend = improving
    Negative trend = declining
    """
    if not recent_events:
        return 0.0
    
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    relevant = [e for e in recent_events if e.created_at > cutoff]
    
    if not relevant:
        return 0.0
    
    return sum(e.delta for e in relevant) / len(relevant)
```

---

### 4. Feedback Collection System

**Purpose:** Capture signals that indicate karma-relevant outcomes.

#### Explicit Feedback Handlers

```python
class FeedbackCollector:
    """
    Collects feedback from various sources and translates to karma events.
    """
    
    async def record_explicit_feedback(
        self,
        target_agent: str,
        rating: Literal["positive", "negative", "neutral"],
        context: str,
        interaction_id: str = None
    ):
        """
        Handle direct feedback from David.
        Could come from UI buttons, voice commands, or explicit statements.
        """
        delta_map = {"positive": 3.0, "neutral": 0.0, "negative": -5.0}
        # Negative weighs more - mistakes should matter
        
        await self.karma_service.record_event(
            agent_id=target_agent,
            dimension="helpfulness",
            delta=delta_map[rating],
            reason=f"Explicit {rating} feedback: {context}",
            evidence_type="feedback",
            evidence_ids=[interaction_id] if interaction_id else None
        )
    
    async def record_correction(
        self,
        target_agent: str,
        original_response: str,
        correction: str,
        severity: Literal["minor", "moderate", "major"]
    ):
        """
        David corrected something Sara said/did.
        """
        severity_delta = {"minor": -2.0, "moderate": -5.0, "major": -10.0}
        
        await self.karma_service.record_event(
            agent_id=target_agent,
            dimension="accuracy",
            delta=severity_delta[severity],
            reason=f"Correction ({severity}): {correction[:100]}",
            evidence_type="feedback"
        )
```

#### Implicit Signal Detection

```python
class ImplicitSignalDetector:
    """
    Detect karma-relevant outcomes from behavior patterns.
    """
    
    async def analyze_conversation_end(self, conversation: Conversation):
        """
        When a conversation ends, analyze for implicit signals.
        """
        signals = []
        
        # Repeated questions suggest confusion or unhelpfulness
        if self._detect_repeated_questions(conversation):
            signals.append(KarmaSignal(
                dimension="helpfulness",
                delta=-2.0,
                reason="User had to repeat/rephrase question"
            ))
        
        # Quick task completion suggests good help
        if self._detect_quick_resolution(conversation):
            signals.append(KarmaSignal(
                dimension="helpfulness",
                delta=2.0,
                reason="Task completed efficiently"
            ))
        
        # Explicit thanks
        if self._detect_gratitude(conversation):
            signals.append(KarmaSignal(
                dimension="helpfulness",
                delta=1.5,
                reason="User expressed gratitude"
            ))
        
        return signals
    
    async def analyze_notification_response(
        self,
        notification: Notification,
        user_response: UserResponse
    ):
        """
        How did David respond to a proactive notification?
        """
        if user_response.action == "dismissed_immediately":
            return KarmaSignal(
                dimension="timing",
                delta=-2.0,
                reason="Notification dismissed without engagement"
            )
        elif user_response.action == "acted_on":
            return KarmaSignal(
                dimension="proactivity",
                delta=3.0,
                reason="Proactive notification led to action"
            )
        elif user_response.action == "marked_useful":
            return KarmaSignal(
                dimension="proactivity",
                delta=2.0,
                reason="Notification marked as useful"
            )
```

---

### 5. Agent Karma Awareness

**Purpose:** Each agent sees its karma and adjusts behavior accordingly.

#### Karma Context Injection

Every time an agent runs, inject its karma state into the prompt:

```python
def build_karma_context(agent_karma: AgentKarma) -> str:
    """
    Build the karma section for agent prompts.
    """
    context = f"""
<karma_state agent="{agent_karma.agent_id}">
  <overall_score>{agent_karma.overall_score:.1f}</overall_score>
  <overall_trend>{format_trend(agent_karma.overall_trend)}</overall_trend>
  
  <dimensions>
"""
    for dim in agent_karma.dimensions:
        context += f"""    <dimension name="{dim.name}">
      <score>{dim.current_score:.1f}</score>
      <trend>{format_trend(dim.trend)}</trend>
      <recent_events>
        {format_recent_events(dim.recent_events, limit=3)}
      </recent_events>
    </dimension>
"""
    
    context += """  </dimensions>
  
  <guidance>
"""
    
    # Add behavioral guidance based on karma state
    if agent_karma.overall_score < 35:
        context += """    Your performance has been below expectations recently.
    Focus on accuracy over speed. Ask for clarification when uncertain.
    Consider requesting confirmation before taking significant actions.
"""
    elif agent_karma.overall_score > 75:
        context += """    Your performance has been strong.
    You have earned trust for more autonomous action.
    Continue calibrating confidence appropriately.
"""
    else:
        context += """    Your performance is in normal range.
    Balance helpfulness with accuracy.
    Continue building trust through consistent performance.
"""
    
    context += """  </guidance>
</karma_state>
"""
    return context


def format_trend(trend: float) -> str:
    if trend > 0.5:
        return f"improving (+{trend:.1f})"
    elif trend < -0.5:
        return f"declining ({trend:.1f})"
    else:
        return "stable"


def format_recent_events(events: list[KarmaEvent], limit: int) -> str:
    if not events:
        return "No recent events"
    
    lines = []
    for event in events[:limit]:
        sign = "+" if event.delta > 0 else ""
        lines.append(f"[{sign}{event.delta:.1f}] {event.reason[:50]}")
    
    return "\n        ".join(lines)
```

#### Behavioral Modification Based on Karma

Sara's prompt should include instructions for karma-aware behavior:

```markdown
## Karma-Aware Behavior

Your karma scores reflect your performance over time. Use them to calibrate your behavior:

### Low Karma Responses (score < 35 in any dimension)
- Be more cautious and explicit
- Ask for confirmation on important actions
- Prefer providing options over taking direct action
- Acknowledge uncertainty more explicitly

### Normal Karma (35-65)
- Balance efficiency with accuracy
- Take routine actions autonomously
- Escalate non-routine decisions

### High Karma (> 75)
- You've earned trust—use it wisely
- More autonomous action is appropriate
- But maintain calibration—overconfidence erodes trust fast

### Critical Low (< 20)
- Enter conservative mode
- Notify David of your status
- Request guidance on how to improve
- Every action should be validated
```

---

### 6. Karma Decay System

**Purpose:** Scores naturally drift toward neutral over time. No eternal punishment, no resting on laurels.

#### Decay Worker

```python
@celery_app.task
def apply_karma_decay():
    """
    Run daily. Applies decay toward neutral (50).
    """
    config = get_karma_config()
    
    if not config.decay.enabled:
        return
    
    all_scores = karma_service.get_all_current_scores()
    
    for score in all_scores:
        # Only decay if sufficiently far from neutral
        if score.current_score > config.decay.min_score_for_decay:
            # High scores decay down
            decay_amount = config.decay.rate_per_day
            karma_service.record_event(
                agent_id=score.agent_id,
                dimension=score.dimension_name,
                delta=-decay_amount,
                reason="Daily decay toward neutral",
                evidence_type="decay"
            )
        elif score.current_score < config.decay.max_score_for_recovery:
            # Low scores recover up (slower)
            recovery_amount = config.decay.rate_per_day * 0.5
            karma_service.record_event(
                agent_id=score.agent_id,
                dimension=score.dimension_name,
                delta=recovery_amount,
                reason="Daily recovery toward neutral",
                evidence_type="decay"
            )
```

#### Celery Beat Schedule Addition

```python
CELERY_BEAT_SCHEDULE['karma-decay'] = {
    'task': 'tasks.karma.apply_karma_decay',
    'schedule': crontab(hour=4, minute=0),  # 4 AM daily
}
```

---

### 7. Karma Alerting

**Purpose:** Notify David when karma crosses critical thresholds.

```python
class KarmaAlertService:
    """
    Monitor karma and alert on significant changes.
    """
    
    async def check_thresholds(self, karma_event: KarmaEvent):
        """
        Called after every karma event.
        Check if thresholds crossed and alert if needed.
        """
        score = await self.karma_service.get_score(
            karma_event.agent_id,
            karma_event.dimension_name
        )
        config = get_karma_config()
        
        # Critical low threshold
        if score.current_score < config.thresholds.critical_low:
            await self.send_alert(
                level="critical",
                agent_id=karma_event.agent_id,
                dimension=karma_event.dimension_name,
                score=score.current_score,
                message=f"{karma_event.agent_id}'s {karma_event.dimension_name} "
                        f"has dropped to critical level ({score.current_score:.1f})"
            )
        
        # Significant negative trend
        elif score.trend < -2.0:
            await self.send_alert(
                level="warning",
                agent_id=karma_event.agent_id,
                dimension=karma_event.dimension_name,
                score=score.current_score,
                message=f"{karma_event.agent_id}'s {karma_event.dimension_name} "
                        f"is declining rapidly (trend: {score.trend:.1f})"
            )
    
    async def send_alert(self, level: str, agent_id: str, dimension: str, 
                         score: float, message: str):
        """
        Send alert through Sara's notification system.
        """
        # Integrate with existing notification mechanism
        await notification_service.send(
            title=f"Karma Alert: {agent_id}",
            body=message,
            priority="high" if level == "critical" else "normal",
            category="system_health"
        )
```

---

### 8. Manual Karma Adjustment Interface

**Purpose:** Allow David to directly adjust karma when automated detection misses something.

#### Voice/Text Commands Sara Should Recognize

```
"Sara, that was really helpful" → +helpfulness
"Sara, you got that wrong" → -accuracy
"That notification was perfectly timed" → +timing
"You missed something important earlier" → -proactivity (prompt for details)
"Your consolidation missed that" → -consolidation.accuracy (prompt for details)
"Good catch" → +proactivity
"Adjust your [dimension] karma [up/down]" → Manual adjustment with reason prompt
```

#### Command Handler

```python
class KarmaCommandHandler:
    """
    Handle natural language karma adjustments.
    """
    
    QUICK_ADJUSTMENTS = {
        "that was helpful": ("sara", "helpfulness", 2.0),
        "really helpful": ("sara", "helpfulness", 3.0),
        "you got that wrong": ("sara", "accuracy", -3.0),
        "that's incorrect": ("sara", "accuracy", -3.0),
        "perfect timing": ("sara", "timing", 3.0),
        "good catch": ("sara", "proactivity", 3.0),
        "you missed that": ("sara", "proactivity", -3.0),
    }
    
    async def process_command(self, text: str, context: dict) -> str:
        """
        Process karma-related commands from David.
        """
        text_lower = text.lower()
        
        # Check quick adjustments
        for phrase, (agent, dimension, delta) in self.QUICK_ADJUSTMENTS.items():
            if phrase in text_lower:
                await self.karma_service.record_event(
                    agent_id=agent,
                    dimension=dimension,
                    delta=delta,
                    reason=f"Direct feedback: {text[:100]}",
                    evidence_type="feedback"
                )
                return f"Noted. Adjusted {dimension} karma by {delta:+.1f}."
        
        # Check for explicit adjustment command
        if "adjust" in text_lower and "karma" in text_lower:
            return await self._handle_explicit_adjustment(text, context)
        
        return None  # Not a karma command
```

---

## Testing Requirements

### Unit Tests

1. **Karma calculations:**
   - Score bounds enforced (0-100)
   - Diminishing returns work correctly
   - Trend calculation accurate

2. **Event recording:**
   - Events persisted correctly
   - Current score updated atomically
   - History maintained

3. **Decay system:**
   - Decay applies correctly
   - Recovery works for low scores
   - Neutral scores unaffected

### Integration Tests

1. **Full feedback flow:**
   - Explicit feedback → karma event → score update → agent sees new karma
   - Implicit signals detected and recorded
   - Alerts triggered at thresholds

2. **Agent awareness:**
   - Karma context correctly injected into prompts
   - Behavioral guidance matches karma state
   - Sara can reference her own karma naturally

3. **Cross-phase integration:**
   - Consolidation agent has karma
   - Consolidation decisions can affect its karma (prep for Phase 3)

### Manual Testing

1. Give Sara explicit feedback, verify karma changes
2. Verify karma shows in Sara's self-awareness
3. Test decay over simulated time
4. Test threshold alerts

---

## Completion Criteria

**This phase is NOT complete until:**

- [ ] Karma schema deployed with migrations
- [ ] All three agents have karma dimensions configured
- [ ] KarmaService fully implemented with all methods
- [ ] Feedback collection working (explicit and implicit)
- [ ] Karma context injected into all agent prompts
- [ ] Agents demonstrate karma-aware behavior in responses
- [ ] Decay system running on schedule
- [ ] Alerting functional at thresholds
- [ ] Manual adjustment commands working
- [ ] All Phase 1 + Phase 2 tests passing
- [ ] No stubs, TODOs, or placeholder implementations
- [ ] Sara can naturally discuss her own karma state
- [ ] Dashboard/monitoring shows karma health

---

## Files to Create/Modify

### New Files
```
services/
  karma/
    __init__.py
    service.py           # Core KarmaService
    models.py            # Pydantic models
    calculations.py      # Score calculations
    config.py            # Configuration management
    
  feedback/
    __init__.py
    collector.py         # FeedbackCollector
    implicit_signals.py  # ImplicitSignalDetector
    command_handler.py   # KarmaCommandHandler
    
  alerts/
    karma_alerts.py      # KarmaAlertService
    
tasks/
  karma_tasks.py         # Decay worker, other karma tasks
  
migrations/
  XXXX_create_karma_tables.py

tests/
  test_karma_service.py
  test_feedback_collection.py
  test_karma_integration.py
```

### Modified Files
```
- Sara's prompt template (add karma context injection)
- Consolidation agent prompt (add karma awareness)
- Celery beat schedule (add decay task)
- Notification service (integrate karma alerts)
- Sara's command processing (add karma commands)
```

---

## Notes for Claude

1. **Karma must feel natural.** Sara shouldn't be constantly talking about her karma. It should influence behavior subtly.

2. **Feedback detection is hard.** Start with explicit signals, add implicit detection carefully. False positives are worse than missed signals.

3. **Test the emotional experience.** Does low karma actually make Sara more cautious? Does high karma enable appropriate autonomy?

4. **Avoid punishment spirals.** The system should enable recovery. A bad day shouldn't permanently damage an agent.

5. **This is infrastructure for Phase 3.** The reflection agent will use karma heavily. Make sure the APIs are clean and comprehensive.
