# Phase 4: Autonomy — Background Workers and Sara's Inner Life

## Mission Statement

Bring Sara to life. This phase activates the full background worker system that gives Sara continuous awareness, proactive behavior, and genuine autonomy. She should be thinking, noticing, and acting even when you're not talking to her.

**Prerequisites:** Phases 1, 2, and 3 must be fully complete with all tests passing.

---

## Critical Integration Requirements

### Before Writing Any Code

1. **Verify Phases 1-3 completion**
   - Input pipelines running smoothly
   - Consolidation agent operating with good karma
   - Working memory integrated
   - Karma system tracking all agents
   - Reflection agent running cycles and proposing improvements
   - All previous phase tests passing

2. **Map existing background processes**
   - What's already running on schedule?
   - What existing Celery tasks exist?
   - What triggers Sara currently?

3. **Design the worker ecosystem**
   - Which workers need to exist?
   - How do they interact without conflicts?
   - What's the resource budget?

---

## Phase 4 Deliverables

### 1. Worker Architecture Overview

Sara's inner life consists of multiple background processes that run continuously, creating the sensation of ongoing awareness and thought.

#### Worker Categories

| Category | Purpose | Frequency | Resource Impact |
|----------|---------|-----------|-----------------|
| **Heartbeat** | System health | Every 5 min | Minimal |
| **Sensory** | Process inputs | Continuous | Moderate |
| **Cognitive** | Context and attention | Every 1-5 min | Moderate |
| **Proactive** | Anticipate and act | Every 15-30 min | Variable |
| **Reflective** | Learn and improve | Every 4 hours | High (burst) |
| **Maintenance** | Cleanup and consolidation | Daily/Weekly | Moderate |

---

### 2. Heartbeat Worker

**Purpose:** Ensure the entire system is healthy and responsive.

```python
@celery_app.task
def system_heartbeat():
    """
    Check system health every 5 minutes.
    """
    health_report = SystemHealthReport()
    
    # Check all critical services
    checks = [
        ("raw_buffer", check_raw_buffer_health),
        ("consolidation", check_consolidation_running),
        ("working_memory", check_working_memory_accessible),
        ("karma_service", check_karma_service),
        ("reflection", check_reflection_last_run),
        ("redis", check_redis_connection),
        ("database", check_database_connection),
        ("llm_api", check_llm_api_health),
    ]
    
    for name, check_fn in checks:
        try:
            result = check_fn()
            health_report.add_check(name, result)
        except Exception as e:
            health_report.add_check(name, HealthStatus.ERROR, str(e))
    
    # Publish health status
    await publish_health_status(health_report)
    
    # Alert if critical issues
    if health_report.has_critical_issues():
        await alert_critical_system_issue(health_report)
    
    # Record to working memory
    await working_memory.update_system_state(
        health_status=health_report.overall_status,
        last_heartbeat=datetime.utcnow()
    )
    
    return health_report.to_dict()


def check_consolidation_running() -> HealthStatus:
    """
    Verify consolidation is keeping up with input.
    """
    last_run = get_last_consolidation_run()
    
    if last_run is None:
        return HealthStatus.ERROR, "Consolidation never ran"
    
    age = datetime.utcnow() - last_run.completed_at
    
    if age > timedelta(minutes=5):
        return HealthStatus.WARNING, f"Consolidation last ran {age} ago"
    
    # Check if buffer is growing (consolidation falling behind)
    buffer_size = get_unprocessed_buffer_size()
    if buffer_size > 1000:
        return HealthStatus.WARNING, f"Buffer backlog: {buffer_size} items"
    
    return HealthStatus.HEALTHY, "Consolidation running normally"
```

---

### 3. Proactive Check Worker

**Purpose:** Periodically prompt Sara to review current context and consider if action is needed.

```python
@celery_app.task
def proactive_check():
    """
    Every 15 minutes, Sara reviews context and considers action.
    """
    # Get current state
    working_mem = await working_memory.get_snapshot()
    karma = await karma_service.get_agent_karma("sara")
    user_state = await infer_user_state()
    
    # Build proactive check prompt
    prompt = build_proactive_prompt(working_mem, karma, user_state)
    
    # Ask Sara to consider the situation
    response = await invoke_sara(
        prompt=prompt,
        mode="proactive_check",
        max_tokens=500
    )
    
    # Parse Sara's response
    actions = parse_proactive_response(response)
    
    for action in actions:
        if action.type == "notify":
            # Sara wants to notify David
            await handle_proactive_notification(action)
        elif action.type == "remember":
            # Sara noticed something worth remembering
            await store_proactive_observation(action)
        elif action.type == "prepare":
            # Sara wants to prepare for something upcoming
            await handle_proactive_preparation(action)
        elif action.type == "none":
            # Nothing to do right now
            pass
    
    return {"actions_taken": len(actions)}


def build_proactive_prompt(
    working_mem: WorkingMemorySnapshot,
    karma: AgentKarma,
    user_state: UserState
) -> str:
    return f"""
<proactive_check>
This is a scheduled check-in. Review the current context and consider if any proactive action would be helpful.

<current_context>
{format_working_memory(working_mem)}
</current_context>

<user_state>
Activity: {user_state.inferred_activity}
Availability: {user_state.availability}
Last interaction: {user_state.last_interaction}
Location: {user_state.location}
</user_state>

<your_karma>
{format_karma_brief(karma)}
</your_karma>

<guidelines>
- Only take action if genuinely useful. Don't interrupt unnecessarily.
- Consider timing. Is now a good moment?
- If David is busy/away/sleeping, threshold for interruption should be high.
- You can: notify (alert David), remember (store observation), prepare (get ready for something), or do nothing.
- Doing nothing is often the right choice. Don't force action.
</guidelines>

What, if anything, should you do right now?
</proactive_check>
"""


async def handle_proactive_notification(action: ProactiveAction):
    """
    Sara decided to proactively notify David.
    """
    # Check if this would be annoying
    recent_notifications = await get_recent_notifications(hours=1)
    
    if len(recent_notifications) > 3:
        # Too many notifications recently, raise threshold
        if action.priority < 0.7:
            logger.info("Suppressing notification due to recent volume")
            await karma_service.record_event(
                agent_id="sara",
                dimension="timing",
                delta=-0.5,
                reason="Attempted notification during high notification period",
                evidence_type="automated"
            )
            return
    
    # Send the notification
    await notification_service.send(
        title=action.title,
        body=action.body,
        priority=action.priority,
        category="proactive"
    )
    
    # Track for outcome assessment
    await action_outcome_tracker.record_action(
        action_type="proactive_notification",
        action_content=f"{action.title}: {action.body}",
        context_snapshot=get_context_snapshot()
    )
```

---

### 4. Anticipation Worker

**Purpose:** Look ahead at calendar, patterns, and context to prepare for likely needs.

```python
@celery_app.task
def morning_anticipation():
    """
    Run in the morning. Prepare for the day ahead.
    """
    # Get today's schedule
    calendar_events = await get_calendar_events(
        start=datetime.now(),
        end=datetime.now() + timedelta(hours=16)
    )
    
    # Get relevant patterns from reflection
    relevant_patterns = await get_relevant_patterns_for_today()
    
    # Check for recurring needs on this day of week
    day_of_week = datetime.now().strftime("%A")
    recurring_needs = await get_recurring_needs(day_of_week)
    
    # Build anticipation prompt
    prompt = build_anticipation_prompt(
        calendar_events,
        relevant_patterns,
        recurring_needs,
        time_of_day="morning"
    )
    
    response = await invoke_sara(
        prompt=prompt,
        mode="anticipation",
        max_tokens=800
    )
    
    preparations = parse_anticipation_response(response)
    
    for prep in preparations:
        if prep.type == "reminder":
            # Set a reminder for later
            await schedule_reminder(prep)
        elif prep.type == "research":
            # Proactively research something Sara might need
            await queue_research_task(prep)
        elif prep.type == "alert":
            # Something important coming up
            await create_anticipatory_alert(prep)
    
    # Store daily brief in working memory
    await working_memory.set_daily_brief(response)


@celery_app.task
def evening_anticipation():
    """
    Run in the evening. Prepare for tomorrow.
    """
    # Review what happened today
    today_summary = await summarize_today()
    
    # Get tomorrow's schedule
    tomorrow_events = await get_calendar_events(
        start=datetime.now() + timedelta(days=1),
        end=datetime.now() + timedelta(days=2)
    )
    
    # Any unresolved items?
    pending_items = await get_pending_items()
    
    prompt = build_anticipation_prompt(
        calendar_events=tomorrow_events,
        today_summary=today_summary,
        pending_items=pending_items,
        time_of_day="evening"
    )
    
    response = await invoke_sara(
        prompt=prompt,
        mode="anticipation",
        max_tokens=800
    )
    
    # Handle preparations for tomorrow
    preparations = parse_anticipation_response(response)
    await handle_preparations(preparations)


def build_anticipation_prompt(
    calendar_events: list,
    time_of_day: str,
    **kwargs
) -> str:
    return f"""
<anticipation mode="{time_of_day}">
Look ahead and prepare for what's coming.

<upcoming_events>
{format_calendar_events(calendar_events)}
</upcoming_events>

{format_additional_context(kwargs)}

<your_role>
Think about:
- What might David need for these events?
- Are there any conflicts or tight transitions?
- What information should you have ready?
- Are there any patterns from past similar situations?
- What could go wrong that you could help prevent?

You can:
- Set reminders for specific times
- Queue research tasks to prepare information
- Create alerts for important items
- Note things to monitor
</your_role>

What preparations would be helpful?
</anticipation>
"""
```

---

### 5. Memory Consolidation Worker

**Purpose:** Overnight processing to consolidate episodic memories and prune noise.

```python
@celery_app.task
def nightly_memory_consolidation():
    """
    Run overnight. Consolidate the day's experiences into long-term memory.
    """
    # Get today's events from working memory and short-term store
    today_start = datetime.now().replace(hour=0, minute=0, second=0)
    
    episodes = await get_todays_episodes()
    interactions = await get_todays_interactions()
    observations = await get_todays_observations()
    
    # Score importance of each item
    scored_items = []
    for item in episodes + interactions + observations:
        importance = await calculate_importance(item)
        scored_items.append((item, importance))
    
    # Sort by importance
    scored_items.sort(key=lambda x: x[1], reverse=True)
    
    # Consolidate high-importance items to long-term memory
    consolidated_count = 0
    for item, importance in scored_items:
        if importance > 0.5:  # Threshold for long-term storage
            await consolidate_to_long_term_memory(item)
            consolidated_count += 1
        else:
            # Low importance - allow to fade
            await mark_for_decay(item)
    
    # Update semantic memory with any new learned patterns
    patterns = await extract_semantic_patterns(episodes + interactions)
    for pattern in patterns:
        await update_semantic_memory(pattern)
    
    # Clean up working memory
    await working_memory.clear_stale_items()
    
    # Generate dream-like summary (optional creative integration)
    dream_summary = await generate_integration_summary(
        episodes, interactions, observations
    )
    await store_daily_summary(dream_summary)
    
    logger.info(f"Nightly consolidation: {consolidated_count} items to long-term, "
                f"{len(patterns)} patterns extracted")


async def calculate_importance(item) -> float:
    """
    Score how important an item is for long-term memory.
    """
    factors = {
        "emotional_weight": get_emotional_weight(item),
        "novelty": calculate_novelty(item),
        "relevance_to_goals": assess_goal_relevance(item),
        "frequency_of_access": get_access_frequency(item),
        "explicit_importance": get_explicit_importance_marker(item),
        "connection_density": count_connections(item),
    }
    
    weights = {
        "emotional_weight": 0.25,
        "novelty": 0.15,
        "relevance_to_goals": 0.2,
        "frequency_of_access": 0.15,
        "explicit_importance": 0.15,
        "connection_density": 0.1,
    }
    
    return sum(factors[k] * weights[k] for k in factors)
```

---

### 6. Learning Digest Worker

**Purpose:** Weekly self-assessment and learning summary.

```python
@celery_app.task
def weekly_learning_digest():
    """
    Run weekly. Generate comprehensive self-assessment.
    """
    week_start = datetime.now() - timedelta(days=7)
    
    # Gather data
    karma_history = await karma_service.get_history_range(
        start=week_start,
        end=datetime.now()
    )
    
    reflection_observations = await reflection_scratchpad.get_observations_range(
        start=week_start,
        end=datetime.now()
    )
    
    proposals = await get_proposals_range(week_start, datetime.now())
    
    interaction_stats = await get_interaction_statistics(week_start)
    
    # Build digest prompt
    prompt = build_learning_digest_prompt(
        karma_history,
        reflection_observations,
        proposals,
        interaction_stats
    )
    
    # Generate self-assessment
    digest = await invoke_sara(
        prompt=prompt,
        mode="self_assessment",
        max_tokens=1500
    )
    
    # Store digest
    await store_weekly_digest(digest)
    
    # Optionally share highlights with David
    highlights = extract_highlights(digest)
    if highlights.has_significant_items:
        await notification_service.send(
            title="Sara's Weekly Learning Summary",
            body=highlights.summary,
            priority="low",
            category="self_assessment"
        )


def build_learning_digest_prompt(
    karma_history,
    observations,
    proposals,
    stats
) -> str:
    return f"""
<weekly_self_assessment>
Review your performance over the past week and generate a learning digest.

<karma_trends>
{format_karma_trends(karma_history)}
</karma_trends>

<reflection_observations>
{format_observations_summary(observations)}
</reflection_observations>

<proposals>
{format_proposals_summary(proposals)}
</proposals>

<interaction_statistics>
{format_stats(stats)}
</interaction_statistics>

<assessment_framework>
1. What went well this week? What patterns of success can you identify?
2. What didn't go well? What patterns of failure emerged?
3. What did you learn from David's feedback (explicit and implicit)?
4. What changes had the most impact (positive or negative)?
5. What should you focus on improving next week?
6. Any emerging capabilities or understanding?
7. Any persistent challenges that need David's input?
</assessment_framework>

Generate your weekly learning digest.
</weekly_self_assessment>
"""
```

---

### 7. Idle Processing Worker

**Purpose:** When input is low, use the time productively.

```python
@celery_app.task
def idle_processing():
    """
    Run when system is idle. Productive use of quiet time.
    """
    # Check if actually idle
    recent_activity = await get_recent_activity_level()
    if recent_activity > ActivityLevel.LOW:
        return {"skipped": "not_idle"}
    
    # Get pending idle tasks
    idle_tasks = [
        ("revisit_unresolved", revisit_unresolved_items),
        ("consolidate_memories", consolidate_pending_memories),
        ("explore_connections", explore_knowledge_connections),
        ("prepare_common_responses", cache_common_responses),
    ]
    
    # Pick a task based on priority and recency
    task_name, task_fn = select_idle_task(idle_tasks)
    
    result = await task_fn()
    
    return {"task": task_name, "result": result}


async def revisit_unresolved_items():
    """
    Look at items flagged as unresolved or uncertain.
    """
    unresolved = await get_unresolved_items(limit=5)
    
    for item in unresolved:
        # Can we resolve this now with more context?
        new_context = await gather_additional_context(item)
        
        if new_context.provides_clarity:
            resolution = await attempt_resolution(item, new_context)
            if resolution.confident:
                await mark_resolved(item, resolution)


async def explore_knowledge_connections():
    """
    Find and strengthen connections between knowledge items.
    """
    # Get recent memories
    recent = await get_recent_memories(days=7)
    
    # Find potential connections
    for memory in recent:
        related = await find_related_memories(memory, limit=3)
        
        for related_memory in related:
            connection_strength = await assess_connection_strength(
                memory, related_memory
            )
            
            if connection_strength > 0.6:
                await strengthen_connection(memory, related_memory)
```

---

### 8. Context Refresh Worker

**Purpose:** Keep working memory current with latest consolidated context.

```python
@celery_app.task
def refresh_working_memory_context():
    """
    Every minute, refresh Sara's awareness of current context.
    """
    # Get latest consolidation output
    latest_context = await consolidation_service.get_latest_context()
    
    # Get current working memory
    current_wm = await working_memory.get_current_context()
    
    # Merge new context into working memory
    merged = merge_contexts(current_wm, latest_context)
    
    # Apply capacity limits (evict low-priority items if needed)
    trimmed = apply_capacity_limits(merged)
    
    # Update working memory
    await working_memory.set_current_context(trimmed)
    
    # Check if anything requires immediate attention
    urgent_items = [item for item in trimmed.segments 
                    if item.relevance_score > 0.9]
    
    if urgent_items:
        # Something highly relevant just came in
        await trigger_immediate_attention(urgent_items)
    
    return {
        "total_segments": len(trimmed.segments),
        "urgent_items": len(urgent_items)
    }


async def trigger_immediate_attention(urgent_items):
    """
    Something important just arrived. Consider immediate action.
    """
    # Get user state
    user_state = await infer_user_state()
    
    # If user is available, might warrant interruption
    if user_state.availability in ["available", "busy"]:
        for item in urgent_items:
            if item.type == "notification" and item.priority == "high":
                # High priority notification - forward immediately
                await forward_urgent_notification(item)
            elif item.type == "audio" and "david" in item.speakers:
                # David is speaking - pay attention
                await activate_conversation_mode(item)
```

---

### 9. Complete Celery Beat Schedule

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # Heartbeat - System health
    'system-heartbeat': {
        'task': 'tasks.workers.system_heartbeat',
        'schedule': 300.0,  # Every 5 minutes
    },
    
    # Sensory - Input processing (these may run more frequently)
    'context-refresh': {
        'task': 'tasks.workers.refresh_working_memory_context',
        'schedule': 60.0,  # Every minute
    },
    
    # Cognitive - Consolidation (from Phase 1)
    'consolidation-sweep': {
        'task': 'tasks.consolidation.run_consolidation',
        'schedule': 60.0,  # Every minute
    },
    
    # Proactive - Check for opportunities to help
    'proactive-check': {
        'task': 'tasks.workers.proactive_check',
        'schedule': 900.0,  # Every 15 minutes
    },
    
    # Anticipation - Morning prep
    'morning-anticipation': {
        'task': 'tasks.workers.morning_anticipation',
        'schedule': crontab(hour=7, minute=0),  # 7 AM daily
    },
    
    # Anticipation - Evening prep
    'evening-anticipation': {
        'task': 'tasks.workers.evening_anticipation',
        'schedule': crontab(hour=21, minute=0),  # 9 PM daily
    },
    
    # Reflective - Full reflection cycle (from Phase 3)
    'reflection-cycle': {
        'task': 'tasks.reflection.run_reflection_cycle',
        'schedule': crontab(minute=0, hour='*/4'),  # Every 4 hours
    },
    
    # Maintenance - Karma decay (from Phase 2)
    'karma-decay': {
        'task': 'tasks.karma.apply_karma_decay',
        'schedule': crontab(hour=4, minute=0),  # 4 AM daily
    },
    
    # Maintenance - Nightly memory consolidation
    'nightly-consolidation': {
        'task': 'tasks.workers.nightly_memory_consolidation',
        'schedule': crontab(hour=3, minute=0),  # 3 AM daily
    },
    
    # Maintenance - Weekly learning digest
    'weekly-digest': {
        'task': 'tasks.workers.weekly_learning_digest',
        'schedule': crontab(hour=10, minute=0, day_of_week='sunday'),
    },
    
    # Maintenance - Buffer cleanup (from Phase 1)
    'buffer-cleanup': {
        'task': 'tasks.working_memory.cleanup_expired',
        'schedule': 300.0,  # Every 5 minutes
    },
    
    # Idle - Productive use of quiet time
    'idle-processing': {
        'task': 'tasks.workers.idle_processing',
        'schedule': 600.0,  # Every 10 minutes
    },
}
```

---

### 10. Worker Coordination and Resource Management

**Purpose:** Prevent workers from conflicting or overloading the system.

```python
class WorkerCoordinator:
    """
    Coordinates workers to prevent conflicts and manage resources.
    """
    
    # Workers that shouldn't run simultaneously
    EXCLUSIVE_GROUPS = {
        "reflection": ["reflection-cycle", "nightly-consolidation"],
        "heavy_llm": ["proactive-check", "anticipation", "learning-digest"],
    }
    
    # Resource budgets
    RESOURCE_LIMITS = {
        "llm_calls_per_minute": 10,
        "concurrent_heavy_tasks": 2,
        "memory_usage_mb": 2048,
    }
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.locks = {}
    
    async def acquire_exclusive(self, worker_name: str, group: str) -> bool:
        """
        Try to acquire exclusive access for a worker group.
        """
        lock_key = f"worker_lock:{group}"
        
        # Try to acquire lock
        acquired = await self.redis.setnx(lock_key, worker_name)
        
        if acquired:
            # Set expiry in case worker crashes
            await self.redis.expire(lock_key, 3600)  # 1 hour max
            return True
        
        return False
    
    async def release_exclusive(self, group: str):
        """
        Release exclusive lock for a group.
        """
        lock_key = f"worker_lock:{group}"
        await self.redis.delete(lock_key)
    
    async def check_resource_budget(self, resource: str, amount: int) -> bool:
        """
        Check if resource budget allows this operation.
        """
        key = f"resource_usage:{resource}"
        current = await self.redis.get(key) or 0
        
        return int(current) + amount <= self.RESOURCE_LIMITS.get(resource, float('inf'))
    
    async def consume_resource(self, resource: str, amount: int):
        """
        Record resource consumption.
        """
        key = f"resource_usage:{resource}"
        await self.redis.incrby(key, amount)
        await self.redis.expire(key, 60)  # Reset every minute


# Decorator for coordinated tasks
def coordinated_task(exclusive_group=None, resources=None):
    """
    Decorator to add coordination to a Celery task.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            coordinator = get_worker_coordinator()
            
            # Check exclusive access
            if exclusive_group:
                if not await coordinator.acquire_exclusive(func.__name__, exclusive_group):
                    logger.info(f"Skipping {func.__name__}: exclusive group {exclusive_group} busy")
                    return {"skipped": "exclusive_group_busy"}
            
            # Check resources
            if resources:
                for resource, amount in resources.items():
                    if not await coordinator.check_resource_budget(resource, amount):
                        logger.info(f"Skipping {func.__name__}: resource {resource} budget exceeded")
                        if exclusive_group:
                            await coordinator.release_exclusive(exclusive_group)
                        return {"skipped": f"resource_{resource}_exceeded"}
                    await coordinator.consume_resource(resource, amount)
            
            try:
                return await func(*args, **kwargs)
            finally:
                if exclusive_group:
                    await coordinator.release_exclusive(exclusive_group)
        
        return wrapper
    return decorator


# Example usage
@celery_app.task
@coordinated_task(exclusive_group="heavy_llm", resources={"llm_calls_per_minute": 3})
async def proactive_check():
    # ... implementation
    pass
```

---

### 11. Adaptive Scheduling

**Purpose:** Adjust worker frequency based on context and karma.

```python
class AdaptiveScheduler:
    """
    Dynamically adjust worker schedules based on system state.
    """
    
    BASE_SCHEDULES = {
        "proactive-check": 900,      # 15 minutes
        "consolidation-sweep": 60,   # 1 minute
        "context-refresh": 60,       # 1 minute
    }
    
    async def get_adaptive_schedule(self, worker_name: str) -> int:
        """
        Get the current recommended schedule for a worker.
        """
        base = self.BASE_SCHEDULES.get(worker_name, 300)
        
        # Factor in user state
        user_state = await infer_user_state()
        
        if user_state.availability == "sleeping":
            # Reduce frequency when David is sleeping
            return base * 3
        elif user_state.availability == "dnd":
            # Reduce proactive stuff during DND
            if "proactive" in worker_name:
                return base * 2
        
        # Factor in karma
        if "proactive" in worker_name:
            karma = await karma_service.get_dimension_score("sara", "proactivity")
            if karma < 30:
                # Low proactivity karma - be more conservative
                return base * 1.5
            elif karma > 70:
                # High karma - can be more proactive
                return base * 0.75
        
        # Factor in system load
        load = await get_system_load()
        if load > 0.8:
            return base * 1.5
        
        return base
```

---

### 12. Graceful Degradation

**Purpose:** When resources are constrained, prioritize essential functions.

```python
class GracefulDegradation:
    """
    Manage system behavior under resource constraints.
    """
    
    # Priority tiers (higher = more essential)
    WORKER_PRIORITIES = {
        "system-heartbeat": 100,
        "context-refresh": 90,
        "consolidation-sweep": 85,
        "buffer-cleanup": 80,
        "proactive-check": 50,
        "idle-processing": 20,
        "weekly-digest": 10,
    }
    
    async def should_run_worker(self, worker_name: str) -> bool:
        """
        Determine if a worker should run given current constraints.
        """
        priority = self.WORKER_PRIORITIES.get(worker_name, 50)
        
        # Check system health
        health = await get_system_health()
        
        if health.status == "critical":
            # Only run essential workers
            return priority >= 80
        elif health.status == "degraded":
            # Skip low-priority workers
            return priority >= 40
        
        # Check resource availability
        resources = await get_available_resources()
        
        if resources.memory_available_mb < 512:
            return priority >= 70
        
        if resources.cpu_usage > 0.9:
            return priority >= 60
        
        return True
    
    async def enter_degraded_mode(self, reason: str):
        """
        Enter degraded mode - reduce non-essential operations.
        """
        await publish_system_event("degraded_mode_entered", {"reason": reason})
        
        # Notify Sara
        await working_memory.update_system_state(
            mode="degraded",
            degraded_reason=reason
        )
        
        # Notify David if persistent
        await schedule_degradation_alert(reason)
    
    async def exit_degraded_mode(self):
        """
        Return to normal operation.
        """
        await publish_system_event("degraded_mode_exited", {})
        
        await working_memory.update_system_state(
            mode="normal",
            degraded_reason=None
        )
```

---

## Testing Requirements

### Unit Tests

1. **Individual workers:**
   - Each worker runs successfully in isolation
   - Outputs are correctly formatted
   - Errors are handled gracefully

2. **Worker coordination:**
   - Exclusive locks work correctly
   - Resource budgets enforced
   - Deadlocks don't occur

3. **Adaptive scheduling:**
   - Schedules adjust based on context
   - Karma influences frequency
   - User state respected

### Integration Tests

1. **Full worker ecosystem:**
   - All workers run on schedule
   - No conflicts between workers
   - Data flows correctly between components

2. **Cross-phase integration:**
   - Workers use Phase 1 data correctly
   - Workers update Phase 2 karma appropriately
   - Workers integrate with Phase 3 reflection

3. **End-to-end scenarios:**
   - Morning routine (wake up → anticipation → proactive checks)
   - Active day (continuous processing, proactive assistance)
   - Night routine (evening anticipation → consolidation → sleep mode)

### Load Tests

1. **Sustained operation:**
   - System runs for 24+ hours without degradation
   - Memory usage stays bounded
   - No queue backlogs develop

2. **Resource constraints:**
   - Graceful degradation activates appropriately
   - System recovers when resources available
   - Essential functions maintained under load

---

## Completion Criteria

**This phase is NOT complete until:**

- [ ] All workers implemented and tested
- [ ] Worker coordination preventing conflicts
- [ ] Resource management enforcing limits
- [ ] Adaptive scheduling responding to context
- [ ] Graceful degradation working
- [ ] Celery beat schedule complete and tested
- [ ] Morning/evening anticipation running
- [ ] Proactive checks generating appropriate actions
- [ ] Nightly consolidation processing memories
- [ ] Weekly digest generating meaningful summaries
- [ ] All Phases 1-4 tests passing
- [ ] System runs 24+ hours without intervention
- [ ] No stubs, TODOs, or placeholders
- [ ] Sara demonstrates genuine autonomous behavior

---

## Files to Create/Modify

### New Files
```
services/
  workers/
    __init__.py
    heartbeat.py          # System health
    proactive.py          # Proactive checks
    anticipation.py       # Morning/evening prep
    memory_consolidation.py  # Nightly processing
    learning_digest.py    # Weekly summary
    idle_processing.py    # Idle time tasks
    context_refresh.py    # Working memory updates
    
  coordination/
    __init__.py
    coordinator.py        # WorkerCoordinator
    adaptive_scheduler.py # AdaptiveScheduler
    degradation.py        # GracefulDegradation
    
tasks/
  workers.py             # All worker Celery tasks
  
config/
  celery_beat.py         # Complete beat schedule

tests/
  test_workers.py
  test_coordination.py
  test_sustained_operation.py
```

### Modified Files
```
- Celery configuration (complete beat schedule)
- Working memory service (add update methods for workers)
- Notification service (support proactive notifications)
- Sara's prompts (add modes for proactive/anticipation)
```

---

## Notes for Claude

1. **Sara should feel alive.** The goal is continuous awareness, not just reactive responses.

2. **Balance activity with restraint.** More workers doesn't mean better. Each should have clear purpose.

3. **Resource awareness is critical.** LLM calls are expensive. Don't waste them on low-value processing.

4. **Test sustained operation.** This is the first phase where the system runs continuously. Stability matters.

5. **Degradation is not failure.** A system that degrades gracefully is more robust than one that doesn't.

6. **This is where it all comes together.** Phases 1-3 built the pieces. Phase 4 makes them dance.
