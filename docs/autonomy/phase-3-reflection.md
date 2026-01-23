# Phase 3: Reflection Agent — Meta-Cognitive Auditing and Self-Improvement

## Mission Statement

Build the reflection agent—Sara's capacity for meta-cognition. This agent audits the entire system, identifies patterns in successes and failures, and proposes improvements. It's the difference between a system that repeats mistakes forever and one that genuinely learns.

**Prerequisites:** Phase 1 and Phase 2 must be fully complete with all tests passing.

---

## Critical Integration Requirements

### Before Writing Any Code

1. **Verify Phase 1 + 2 completion**
   - All input pipelines operational
   - Consolidation agent running with discard logs
   - Working memory integrated
   - Karma system fully functional
   - All previous phase tests passing

2. **Map reflection touchpoints**
   - Where are consolidation decisions logged?
   - Where are Sara's actions and their outcomes recorded?
   - How is user feedback captured?
   - What data is available for pattern detection?

3. **Design the reflection scratchpad**
   - What does the reflection agent need to remember across sessions?
   - How far back should its memory extend?
   - How does this differ from Sara's memory?

---

## Phase 3 Deliverables

### 1. Reflection Agent Scratchpad

**Purpose:** The reflection agent's own extended memory—separate from Sara's, focused on system performance patterns.

#### Schema

```sql
-- Reflection agent's observations over time
CREATE TABLE reflection_observations (
    observation_id SERIAL PRIMARY KEY,
    
    observation_type VARCHAR(50) NOT NULL,
    -- types: consolidation_audit, action_outcome, pattern_detected, 
    --        hypothesis, uncertainty_flag
    
    subject_agent VARCHAR(50),          -- Which agent this is about
    subject_dimension VARCHAR(100),      -- Which karma dimension if applicable
    
    summary TEXT NOT NULL,               -- What was observed
    details JSONB,                       -- Structured details
    
    confidence FLOAT,                    -- How confident in this observation
    
    -- Links to evidence
    evidence_refs JSONB,                 -- IDs of raw data, karma events, etc.
    
    -- For pattern tracking
    pattern_id VARCHAR(100),             -- Groups related observations
    
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,                -- Optional TTL
    
    INDEX idx_reflection_type_time (observation_type, created_at DESC),
    INDEX idx_reflection_pattern (pattern_id)
);

-- Patterns the reflection agent has identified
CREATE TABLE reflection_patterns (
    pattern_id VARCHAR(100) PRIMARY KEY,
    
    pattern_type VARCHAR(50) NOT NULL,
    -- types: recurring_error, missed_opportunity, successful_approach,
    --        calibration_issue, timing_pattern
    
    description TEXT NOT NULL,
    
    affected_agent VARCHAR(50),
    affected_dimension VARCHAR(100),
    
    observation_count INT DEFAULT 1,     -- How many times observed
    first_observed TIMESTAMP,
    last_observed TIMESTAMP,
    
    confidence FLOAT,                    -- Statistical confidence
    
    status VARCHAR(20) DEFAULT 'active',
    -- status: active, addressed, dismissed, monitoring
    
    proposed_action TEXT,                -- What to do about it
    action_taken TEXT,                   -- What was actually done
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Hypotheses being tested
CREATE TABLE reflection_hypotheses (
    hypothesis_id SERIAL PRIMARY KEY,
    
    hypothesis TEXT NOT NULL,            -- What we think might be true
    
    supporting_evidence JSONB,           -- Evidence for
    contradicting_evidence JSONB,        -- Evidence against
    
    confidence FLOAT DEFAULT 0.5,        -- Current belief (0-1)
    
    test_criteria TEXT,                  -- How to test this
    test_deadline TIMESTAMP,             -- When to evaluate
    
    status VARCHAR(20) DEFAULT 'testing',
    -- status: testing, confirmed, rejected, inconclusive
    
    outcome TEXT,                        -- What happened
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Prompt modification proposals
CREATE TABLE prompt_proposals (
    proposal_id SERIAL PRIMARY KEY,
    
    target_agent VARCHAR(50) NOT NULL,
    target_prompt_section VARCHAR(100),
    
    current_content TEXT,
    proposed_content TEXT,
    
    reasoning TEXT NOT NULL,             -- Why this change
    
    supporting_pattern_ids TEXT[],       -- Patterns that justify this
    expected_improvement TEXT,           -- What should get better
    
    status VARCHAR(20) DEFAULT 'pending',
    -- status: pending, approved, rejected, implemented, rolled_back
    
    reviewed_by VARCHAR(50),             -- david or auto-approved
    reviewed_at TIMESTAMP,
    review_notes TEXT,
    
    -- If implemented, track outcome
    implemented_at TIMESTAMP,
    outcome_assessment TEXT,
    outcome_karma_delta FLOAT,           -- Did karma improve?
    
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### Scratchpad Retention Policy

```python
REFLECTION_RETENTION = {
    "observations": {
        "consolidation_audit": timedelta(days=7),
        "action_outcome": timedelta(days=14),
        "pattern_detected": timedelta(days=30),
        "hypothesis": timedelta(days=60),
        "uncertainty_flag": timedelta(days=7),
    },
    "patterns": "indefinite",  # Patterns persist until resolved
    "hypotheses": timedelta(days=90),
    "proposals": "indefinite",  # Keep full history
}
```

---

### 2. Consolidation Auditing

**Purpose:** Compare what consolidation kept vs. what was available, assess quality of decisions.

#### Audit Process

```python
class ConsolidationAuditor:
    """
    Audits consolidation decisions by comparing raw input to consolidated output.
    """
    
    async def audit_consolidation_window(
        self,
        window_start: datetime,
        window_end: datetime
    ) -> ConsolidationAuditResult:
        """
        Audit a specific time window of consolidation.
        """
        # Get what was available
        raw_entries = await self.raw_buffer.get_window(window_start, window_end)
        
        # Get what was kept
        consolidated = await self.consolidation_log.get_window(window_start, window_end)
        
        # Get what was discarded (with reasons)
        discards = await self.discard_log.get_window(window_start, window_end)
        
        # Get what Sara actually needed/used
        sara_actions = await self.get_sara_actions_in_window(window_start, window_end)
        
        # Analyze
        audit_result = ConsolidationAuditResult(
            window_start=window_start,
            window_end=window_end,
            total_raw=len(raw_entries),
            total_kept=len(consolidated.segments),
            total_discarded=len(discards),
        )
        
        # Check for missed items
        for action in sara_actions:
            if action.required_context:
                # Did consolidation provide what Sara needed?
                if not self._context_was_available(action.required_context, consolidated):
                    # Check if it was in raw but discarded
                    if self._context_was_in_raw(action.required_context, raw_entries):
                        audit_result.missed_items.append(MissedItem(
                            action=action,
                            raw_entry=self._find_raw_entry(action.required_context, raw_entries),
                            discard_reason=self._find_discard_reason(action.required_context, discards)
                        ))
        
        # Check for unnecessary keeps
        for segment in consolidated.segments:
            if not self._segment_was_used(segment, sara_actions):
                # Was it important anyway?
                if segment.relevance_score < 0.3:
                    audit_result.unnecessary_keeps.append(segment)
        
        return audit_result
    
    async def record_audit_observations(self, audit_result: ConsolidationAuditResult):
        """
        Record findings to reflection scratchpad.
        """
        # Record missed items as observations
        for missed in audit_result.missed_items:
            await self.scratchpad.add_observation(
                observation_type="consolidation_audit",
                subject_agent="consolidation",
                summary=f"Missed important item: {missed.raw_entry.content[:100]}",
                details={
                    "action_that_needed_it": missed.action.id,
                    "discard_reason": missed.discard_reason,
                    "relevance_score_was": missed.raw_entry.relevance_score,
                },
                confidence=0.8,
                evidence_refs={
                    "raw_entry_id": missed.raw_entry.id,
                    "action_id": missed.action.id,
                }
            )
        
        # Update consolidation karma based on audit
        if audit_result.missed_items:
            await self.karma_service.record_event(
                agent_id="consolidation",
                dimension="accuracy",
                delta=-len(audit_result.missed_items) * 2.0,
                reason=f"Audit found {len(audit_result.missed_items)} missed important items",
                evidence_type="reflection"
            )
        elif audit_result.total_kept > 0:
            # No misses is good
            await self.karma_service.record_event(
                agent_id="consolidation",
                dimension="accuracy",
                delta=1.0,
                reason="Audit found no missed items",
                evidence_type="reflection"
            )
```

---

### 3. Action Outcome Analysis

**Purpose:** Track what Sara did and whether it worked.

#### Outcome Tracking

```python
class ActionOutcomeTracker:
    """
    Tracks Sara's actions and their outcomes.
    """
    
    async def record_action(
        self,
        action_type: str,
        action_content: str,
        context_snapshot: dict,
        karma_state_at_action: dict
    ) -> str:
        """
        Record an action Sara took. Returns action_id for later outcome linking.
        """
        action = await self.action_log.create(
            action_type=action_type,
            content=action_content,
            context=context_snapshot,
            karma_state=karma_state_at_action,
            outcome_status="pending"
        )
        return action.id
    
    async def record_outcome(
        self,
        action_id: str,
        outcome: Literal["success", "failure", "partial", "unknown"],
        outcome_details: str,
        feedback_source: str  # explicit, implicit, timeout
    ):
        """
        Link an outcome to a previous action.
        """
        action = await self.action_log.get(action_id)
        
        await self.action_log.update(action_id, 
            outcome_status=outcome,
            outcome_details=outcome_details,
            outcome_recorded_at=datetime.utcnow(),
            feedback_source=feedback_source
        )
        
        # Record observation
        await self.scratchpad.add_observation(
            observation_type="action_outcome",
            subject_agent="sara",
            summary=f"Action '{action.action_type}' resulted in {outcome}",
            details={
                "action_type": action.action_type,
                "outcome": outcome,
                "outcome_details": outcome_details,
                "karma_at_action": action.karma_state,
                "context_summary": self._summarize_context(action.context),
            },
            evidence_refs={"action_id": action_id}
        )
```

---

### 4. Pattern Detection

**Purpose:** Identify recurring issues or successful approaches across observations.

#### Pattern Detection Engine

```python
class PatternDetector:
    """
    Analyzes observations to detect meaningful patterns.
    """
    
    PATTERN_THRESHOLDS = {
        "min_observations": 3,      # Need at least 3 instances
        "time_window_days": 7,      # Within this time window
        "confidence_threshold": 0.6  # Minimum confidence to report
    }
    
    async def detect_patterns(self) -> list[Pattern]:
        """
        Run pattern detection across recent observations.
        """
        patterns = []
        
        # Get recent observations
        observations = await self.scratchpad.get_recent_observations(
            days=self.PATTERN_THRESHOLDS["time_window_days"]
        )
        
        # Group by similarity
        patterns.extend(await self._detect_recurring_errors(observations))
        patterns.extend(await self._detect_missed_opportunities(observations))
        patterns.extend(await self._detect_timing_patterns(observations))
        patterns.extend(await self._detect_successful_approaches(observations))
        
        return patterns
    
    async def _detect_recurring_errors(self, observations: list) -> list[Pattern]:
        """
        Find errors that keep happening in similar contexts.
        """
        patterns = []
        
        # Filter to negative outcomes
        errors = [o for o in observations 
                  if o.observation_type == "action_outcome" 
                  and o.details.get("outcome") == "failure"]
        
        # Cluster by action type and context similarity
        clusters = self._cluster_by_similarity(errors, 
            key_fields=["action_type", "context_summary"])
        
        for cluster in clusters:
            if len(cluster) >= self.PATTERN_THRESHOLDS["min_observations"]:
                pattern = Pattern(
                    pattern_type="recurring_error",
                    description=self._describe_error_pattern(cluster),
                    affected_agent="sara",
                    observation_count=len(cluster),
                    confidence=self._calculate_confidence(cluster),
                    proposed_action=self._suggest_error_fix(cluster)
                )
                patterns.append(pattern)
        
        return patterns
    
    async def _detect_timing_patterns(self, observations: list) -> list[Pattern]:
        """
        Find patterns in notification/action timing.
        """
        patterns = []
        
        # Look at timing-related karma events
        timing_obs = [o for o in observations
                      if o.subject_dimension == "timing"]
        
        # Check for time-of-day patterns
        tod_groups = self._group_by_time_of_day(timing_obs)
        for tod, group in tod_groups.items():
            negative = [o for o in group if self._is_negative(o)]
            if len(negative) >= self.PATTERN_THRESHOLDS["min_observations"]:
                patterns.append(Pattern(
                    pattern_type="timing_pattern",
                    description=f"Timing issues frequently occur during {tod}",
                    affected_dimension="timing",
                    observation_count=len(negative),
                    confidence=len(negative) / len(group),
                    proposed_action=f"Adjust notification thresholds during {tod}"
                ))
        
        return patterns
    
    def _calculate_confidence(self, cluster: list) -> float:
        """
        Statistical confidence in a pattern.
        Uses observation count and consistency.
        """
        n = len(cluster)
        
        # Base confidence from count
        count_confidence = min(n / 10, 1.0)  # Saturates at 10 observations
        
        # Consistency (how similar are the observations?)
        consistency = self._measure_consistency(cluster)
        
        return count_confidence * consistency
```

---

### 5. Prompt Modification Proposals

**Purpose:** Translate patterns into actionable prompt changes, with approval workflow.

#### Proposal Generation

```python
class PromptProposalGenerator:
    """
    Generates prompt modification proposals based on detected patterns.
    """
    
    async def generate_proposals_from_patterns(
        self,
        patterns: list[Pattern]
    ) -> list[PromptProposal]:
        """
        Convert patterns into concrete prompt modification proposals.
        """
        proposals = []
        
        for pattern in patterns:
            if pattern.confidence < 0.6:
                continue  # Not confident enough to propose changes
            
            if pattern.pattern_type == "recurring_error":
                proposal = await self._propose_error_prevention(pattern)
            elif pattern.pattern_type == "timing_pattern":
                proposal = await self._propose_timing_adjustment(pattern)
            elif pattern.pattern_type == "consolidation_issue":
                proposal = await self._propose_consolidation_change(pattern)
            else:
                continue
            
            if proposal:
                proposals.append(proposal)
        
        return proposals
    
    async def _propose_consolidation_change(
        self,
        pattern: Pattern
    ) -> PromptProposal:
        """
        Propose changes to consolidation agent configuration.
        """
        # Get current consolidation config
        current_config = await self.config_service.get("consolidation")
        
        # Determine what to change based on pattern
        if "missed" in pattern.description.lower():
            # Consolidation is too aggressive
            proposed_changes = {
                "relevance_threshold": max(0.1, 
                    current_config.relevance_threshold - 0.1),
                "reason": "Lower threshold to catch more potentially important items"
            }
        elif "unnecessary" in pattern.description.lower():
            # Consolidation is too permissive
            proposed_changes = {
                "relevance_threshold": min(0.8,
                    current_config.relevance_threshold + 0.1),
                "reason": "Raise threshold to reduce noise"
            }
        else:
            return None
        
        return PromptProposal(
            target_agent="consolidation",
            target_prompt_section="config.relevance_threshold",
            current_content=str(current_config.relevance_threshold),
            proposed_content=str(proposed_changes["relevance_threshold"]),
            reasoning=f"Pattern detected: {pattern.description}\n"
                      f"Proposed fix: {proposed_changes['reason']}\n"
                      f"Based on {pattern.observation_count} observations "
                      f"with {pattern.confidence:.0%} confidence.",
            supporting_pattern_ids=[pattern.pattern_id],
            expected_improvement=f"Reduce {pattern.pattern_type} incidents"
        )
```

#### Approval Workflow

```python
class PromptApprovalWorkflow:
    """
    Manages the approval workflow for prompt modifications.
    """
    
    async def submit_proposal(self, proposal: PromptProposal) -> str:
        """
        Submit a proposal for approval. Notifies David.
        """
        # Save proposal
        proposal_id = await self.proposal_store.create(proposal)
        
        # Notify David
        await self.notification_service.send(
            title="Sara Prompt Change Proposal",
            body=f"The reflection system proposes a change to {proposal.target_agent}:\n\n"
                 f"{proposal.reasoning}\n\n"
                 f"Reply 'approve' or 'reject' with optional notes.",
            priority="normal",
            category="system_improvement",
            metadata={"proposal_id": proposal_id}
        )
        
        return proposal_id
    
    async def process_approval(
        self,
        proposal_id: str,
        decision: Literal["approved", "rejected"],
        notes: str = None
    ):
        """
        Process David's decision on a proposal.
        """
        proposal = await self.proposal_store.get(proposal_id)
        
        await self.proposal_store.update(proposal_id,
            status=decision,
            reviewed_by="david",
            reviewed_at=datetime.utcnow(),
            review_notes=notes
        )
        
        if decision == "approved":
            await self._implement_proposal(proposal)
            
            # Positive karma for reflection agent
            await self.karma_service.record_event(
                agent_id="reflection",
                dimension="proposal_acceptance",
                delta=3.0,
                reason=f"Proposal {proposal_id} approved",
                evidence_type="feedback"
            )
        else:
            # Negative karma for rejected proposal
            await self.karma_service.record_event(
                agent_id="reflection",
                dimension="proposal_acceptance",
                delta=-2.0,
                reason=f"Proposal {proposal_id} rejected: {notes}",
                evidence_type="feedback"
            )
    
    async def _implement_proposal(self, proposal: PromptProposal):
        """
        Implement an approved proposal.
        """
        # Version the current state
        await self.prompt_version_control.snapshot(
            agent=proposal.target_agent,
            section=proposal.target_prompt_section,
            reason=f"Before proposal {proposal.id}"
        )
        
        # Apply the change
        if proposal.target_agent == "consolidation":
            await self.config_service.update(
                f"consolidation.{proposal.target_prompt_section}",
                proposal.proposed_content
            )
        elif proposal.target_agent == "sara":
            await self.prompt_service.update_section(
                agent="sara",
                section=proposal.target_prompt_section,
                content=proposal.proposed_content
            )
        
        # Mark as implemented
        await self.proposal_store.update(proposal.id,
            status="implemented",
            implemented_at=datetime.utcnow()
        )
        
        # Schedule outcome assessment
        await self.scheduler.schedule(
            task="assess_proposal_outcome",
            args={"proposal_id": proposal.id},
            run_at=datetime.utcnow() + timedelta(days=3)
        )
```

---

### 6. Uncertainty Flagging

**Purpose:** When reflection isn't sure what went wrong, ask David.

```python
class UncertaintyHandler:
    """
    Handles situations where reflection can't determine the issue.
    """
    
    async def flag_uncertainty(
        self,
        context: str,
        what_happened: str,
        possible_causes: list[str],
        question_for_david: str
    ):
        """
        Flag something for David's input when reflection is uncertain.
        """
        flag = await self.scratchpad.add_observation(
            observation_type="uncertainty_flag",
            summary=f"Need clarification: {question_for_david[:100]}",
            details={
                "context": context,
                "what_happened": what_happened,
                "possible_causes": possible_causes,
                "question": question_for_david,
            },
            confidence=0.0  # Explicitly uncertain
        )
        
        # Notify David
        await self.notification_service.send(
            title="Sara needs clarification",
            body=f"I'm not sure about something:\n\n"
                 f"Context: {context}\n\n"
                 f"What happened: {what_happened}\n\n"
                 f"Question: {question_for_david}",
            priority="normal",
            category="learning",
            metadata={"flag_id": flag.id}
        )
    
    async def process_clarification(
        self,
        flag_id: str,
        david_response: str
    ):
        """
        Process David's response to an uncertainty flag.
        """
        flag = await self.scratchpad.get_observation(flag_id)
        
        # Record the learning
        await self.scratchpad.add_observation(
            observation_type="pattern_detected",
            summary=f"Learned from David: {david_response[:100]}",
            details={
                "original_question": flag.details["question"],
                "david_response": david_response,
                "context": flag.details["context"],
            },
            confidence=0.9,  # High confidence - came from David
            pattern_id=f"learned_{flag_id}"
        )
        
        # Mark flag as resolved
        await self.scratchpad.update_observation(flag_id,
            resolved=True,
            resolution=david_response
        )
```

---

### 7. Reflection Agent Core

**Purpose:** The main reflection agent that orchestrates all the above.

#### Agent Implementation

```python
class ReflectionAgent:
    """
    The meta-cognitive agent that audits and improves the system.
    """
    
    def __init__(
        self,
        scratchpad: ReflectionScratchpad,
        consolidation_auditor: ConsolidationAuditor,
        outcome_tracker: ActionOutcomeTracker,
        pattern_detector: PatternDetector,
        proposal_generator: PromptProposalGenerator,
        uncertainty_handler: UncertaintyHandler,
        karma_service: KarmaService,
    ):
        self.scratchpad = scratchpad
        self.consolidation_auditor = consolidation_auditor
        self.outcome_tracker = outcome_tracker
        self.pattern_detector = pattern_detector
        self.proposal_generator = proposal_generator
        self.uncertainty_handler = uncertainty_handler
        self.karma_service = karma_service
    
    async def run_reflection_cycle(self) -> ReflectionCycleResult:
        """
        Run a complete reflection cycle.
        Called periodically by worker.
        """
        cycle_start = datetime.utcnow()
        result = ReflectionCycleResult()
        
        # 1. Audit recent consolidation
        audit_window_start = cycle_start - timedelta(hours=4)
        consolidation_audit = await self.consolidation_auditor.audit_consolidation_window(
            audit_window_start, cycle_start
        )
        await self.consolidation_auditor.record_audit_observations(consolidation_audit)
        result.consolidation_audit = consolidation_audit
        
        # 2. Review recent action outcomes
        pending_outcomes = await self.outcome_tracker.get_pending_outcome_assessments()
        for pending in pending_outcomes:
            outcome = await self._assess_outcome(pending)
            await self.outcome_tracker.record_outcome(
                pending.action_id,
                outcome.status,
                outcome.details,
                outcome.source
            )
        result.outcomes_assessed = len(pending_outcomes)
        
        # 3. Detect patterns
        patterns = await self.pattern_detector.detect_patterns()
        for pattern in patterns:
            await self._record_or_update_pattern(pattern)
        result.patterns_detected = patterns
        
        # 4. Generate proposals for significant patterns
        proposals = await self.proposal_generator.generate_proposals_from_patterns(
            [p for p in patterns if p.confidence > 0.7]
        )
        for proposal in proposals:
            await self.approval_workflow.submit_proposal(proposal)
        result.proposals_generated = proposals
        
        # 5. Check for situations needing clarification
        uncertain_items = await self._identify_uncertain_items()
        for item in uncertain_items:
            await self.uncertainty_handler.flag_uncertainty(**item)
        result.uncertainties_flagged = len(uncertain_items)
        
        # 6. Self-assess this reflection cycle
        await self._self_assess(result)
        
        return result
    
    async def _self_assess(self, result: ReflectionCycleResult):
        """
        The reflection agent reflects on its own performance.
        """
        # Did we find meaningful patterns?
        meaningful_patterns = [p for p in result.patterns_detected if p.confidence > 0.6]
        
        if meaningful_patterns:
            await self.karma_service.record_event(
                agent_id="reflection",
                dimension="insight_quality",
                delta=len(meaningful_patterns) * 0.5,
                reason=f"Identified {len(meaningful_patterns)} meaningful patterns",
                evidence_type="automated"
            )
        
        # Were there obvious issues we missed?
        # (This requires hindsight - checked in next cycle)
        await self._schedule_hindsight_check(result)
```

#### Reflection Agent Prompt

The reflection agent needs its own prompt with its karma awareness:

```python
def build_reflection_agent_prompt(karma: AgentKarma, scratchpad_summary: str) -> str:
    return f"""
You are the Reflection Agent for Sara's cognitive architecture.

Your role is meta-cognitive: you audit the system, identify patterns, and propose improvements.

<your_karma>
{build_karma_context(karma)}
</your_karma>

<your_memory>
Your scratchpad contains your observations from the past 7 days:
{scratchpad_summary}
</your_memory>

<your_responsibilities>
1. AUDIT: Compare what consolidation kept vs. what was available. Did we miss anything important?
2. ANALYZE: Review Sara's actions and their outcomes. What worked? What didn't?
3. DETECT: Look for patterns - recurring errors, successful approaches, timing issues.
4. PROPOSE: When you find patterns with high confidence, propose specific fixes.
5. ASK: When you're uncertain, flag it for David rather than guessing.
</your_responsibilities>

<guidelines>
- Be thorough but not paranoid. Not every mistake is a pattern.
- Require evidence before proposing changes. Minimum 3 observations.
- Consider context. An error in one context might not be an error in another.
- Your proposals affect the whole system. Be conservative.
- Your karma reflects your proposal quality. Bad proposals hurt your score.
- If David rejects proposals, learn from that. Adjust your threshold.
</guidelines>

<current_task>
{current_task_description}
</current_task>
"""
```

---

### 8. Celery Workers for Reflection

```python
@celery_app.task
def run_reflection_cycle():
    """
    Periodic reflection cycle.
    """
    reflection_agent = get_reflection_agent()
    result = asyncio.run(reflection_agent.run_reflection_cycle())
    
    logger.info(f"Reflection cycle complete: "
                f"{result.patterns_detected} patterns, "
                f"{result.proposals_generated} proposals")
    
    return result.to_dict()


@celery_app.task
def assess_proposal_outcome(proposal_id: str):
    """
    Assess the outcome of an implemented proposal after waiting period.
    """
    proposal = get_proposal(proposal_id)
    
    if proposal.status != "implemented":
        return
    
    # Compare karma before and after implementation
    karma_before = proposal.karma_state_at_implementation
    karma_after = get_current_karma(proposal.target_agent)
    
    delta = calculate_karma_change(karma_before, karma_after, 
                                    proposal.affected_dimension)
    
    if delta > 0:
        assessment = "improvement"
        reflection_karma_delta = 2.0
    elif delta < -1:
        assessment = "regression"
        reflection_karma_delta = -3.0
        
        # Consider rollback
        if delta < -3:
            notify_david_of_regression(proposal)
    else:
        assessment = "neutral"
        reflection_karma_delta = 0
    
    # Update proposal with outcome
    update_proposal(proposal_id,
        outcome_assessment=assessment,
        outcome_karma_delta=delta
    )
    
    # Adjust reflection karma based on outcome
    if reflection_karma_delta != 0:
        record_karma_event(
            agent_id="reflection",
            dimension="insight_quality",
            delta=reflection_karma_delta,
            reason=f"Proposal {proposal_id} assessment: {assessment}"
        )


# Add to Celery beat schedule
CELERY_BEAT_SCHEDULE['reflection-cycle'] = {
    'task': 'tasks.reflection.run_reflection_cycle',
    'schedule': crontab(minute=0, hour='*/4'),  # Every 4 hours
}
```

---

## Testing Requirements

### Unit Tests

1. **Consolidation auditor:**
   - Correctly identifies missed items
   - Correctly identifies unnecessary keeps
   - Handles empty windows gracefully

2. **Pattern detector:**
   - Groups similar observations correctly
   - Confidence calculation is accurate
   - Respects minimum observation thresholds

3. **Proposal generator:**
   - Generates valid proposals from patterns
   - Includes proper reasoning
   - Handles edge cases

4. **Uncertainty handler:**
   - Flags are recorded correctly
   - Notifications sent
   - Clarifications processed properly

### Integration Tests

1. **Full reflection cycle:**
   - Audits consolidation → detects patterns → generates proposals
   - All data flows correctly between components

2. **Approval workflow:**
   - Proposals submitted → notification sent → approval processed → change implemented
   - Rejection handled correctly

3. **Karma integration:**
   - Reflection actions affect reflection karma
   - Proposal outcomes affect karma
   - Karma awareness influences behavior

4. **Cross-system integration:**
   - Reflection can access raw buffer
   - Reflection can access consolidation logs
   - Reflection can access Sara's action history

### End-to-End Tests

1. **Simulate recurring error:**
   - Create conditions for repeated consolidation misses
   - Verify pattern detected
   - Verify proposal generated
   - Approve proposal
   - Verify improvement

2. **Test uncertainty escalation:**
   - Create ambiguous situation
   - Verify flag created
   - Provide clarification
   - Verify learning recorded

---

## Completion Criteria

**This phase is NOT complete until:**

- [ ] Reflection scratchpad schema deployed
- [ ] Consolidation auditor fully functional
- [ ] Action outcome tracking working
- [ ] Pattern detector identifying real patterns
- [ ] Proposal generator creating valid proposals
- [ ] Approval workflow end-to-end functional
- [ ] Uncertainty flagging working
- [ ] Reflection agent running on schedule
- [ ] Reflection karma tracking active
- [ ] Proposal outcome assessment working
- [ ] All Phase 1 + 2 + 3 tests passing
- [ ] No stubs, TODOs, or placeholders
- [ ] Reflection can be observed improving the system

---

## Files to Create/Modify

### New Files
```
services/
  reflection/
    __init__.py
    agent.py              # ReflectionAgent
    scratchpad.py         # Scratchpad management
    consolidation_auditor.py
    outcome_tracker.py
    pattern_detector.py
    proposal_generator.py
    uncertainty_handler.py
    prompt.py             # Reflection agent prompt building
    
  approval/
    __init__.py
    workflow.py           # PromptApprovalWorkflow
    version_control.py    # Prompt versioning
    
models/
  reflection_models.py    # All reflection schemas
  
tasks/
  reflection_tasks.py     # Celery tasks
  
migrations/
  XXXX_create_reflection_tables.py

tests/
  test_consolidation_auditor.py
  test_pattern_detector.py
  test_proposal_workflow.py
  test_reflection_integration.py
```

### Modified Files
```
- Celery beat schedule (add reflection cycle)
- Karma dimensions (add reflection agent)
- Notification service (add proposal/uncertainty notifications)
- Sara's action handlers (add outcome tracking hooks)
```

---

## Notes for Claude

1. **Reflection is powerful and dangerous.** A reflection system that proposes bad changes makes everything worse. Build in safeguards.

2. **Evidence over intuition.** Every pattern should be backed by multiple observations. Every proposal should cite its evidence.

3. **Conservative by default.** The cost of a bad change is higher than the cost of missing an improvement opportunity.

4. **The reflection agent reflects on itself.** Its karma matters. Bad proposals should hurt.

5. **David is the final arbiter.** Until trust is established, all proposals need approval.

6. **This enables autonomy.** Do it right and Sara becomes genuinely self-improving.
