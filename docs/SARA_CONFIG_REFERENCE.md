# Sara Autonomous System - Configuration Reference

**Quick reference for configuring Sara's autonomous behavior**

---

## ⚙️ **Activity Monitoring Configuration**

### **Frontend - Activity Thresholds**
**File:** `frontend/src/App-interactive.tsx`

```typescript
const { activityState, getIdleMinutes } = useActivityMonitor({
  thresholds: {
    quickSweep: 25 * 60 * 1000,       // 25 minutes - short idle
    standardSweep: 2.5 * 60 * 60 * 1000, // 2.5 hours - medium idle
    digestSweep: 24 * 60 * 60 * 1000     // 24 hours - long idle
  },
  // ... other options
});
```

**Testing Configuration (for development):**
```typescript
thresholds: {
  quickSweep: 30 * 1000,        // 30 seconds (testing only)
  standardSweep: 2 * 60 * 1000, // 2 minutes (testing only)
  digestSweep: 5 * 60 * 1000    // 5 minutes (testing only)
}
```

---

## 🎯 **Priority Scoring Configuration**

### **Backend - Surfacing Thresholds**
**File:** `backend/app/services/autonomous_sweep_service.py`

```python
class PriorityScorer:
    @staticmethod
    def should_surface(priority_score: float, sweep_type: str) -> bool:
        thresholds = {
            'quick_sweep': 0.6,    # Higher bar for quick notifications
            'standard_sweep': 0.5, # Moderate bar for standard insights
            'digest_sweep': 0.4    # Lower bar for comprehensive analysis
        }
        return priority_score >= thresholds.get(sweep_type, 0.5)
```

### **Insight Priority Calculation**
```python
# Priority formula: (Relevance × Impact × Novelty × Timing) - Annoyance
priority = self.scorer.calculate_priority(
    relevance=0.8,  # 0-1: How relevant to user's current context
    impact=0.7,     # 0-1: How much this could help the user  
    novelty=0.6,    # 0-1: How new/surprising this insight is
    timing=0.9,     # 0-1: How timely/urgent this insight is
    annoyance=0.1   # 0-1: How annoying/disruptive this might be
)
```

---

## 🧠 **Memory Integration Configuration**

### **Memory Context Settings**
**File:** `backend/app/services/autonomous_sweep_service.py`

```python
# Memory search limits
memory_results = await self.memory_service.search_memory(
    user_id=user_id,
    query=query,
    limit=5,                    # Max memories per query
    scopes=["episodes", "notes"], # Search scope
    age_months=1                # Only search last month
)

# Memory context in insights
insight['memory_context'] = {
    'related_memories': relevant_memories[:5],  # Top 5 overall
    'context_summary': self._summarize_memory_context(relevant_memories[:5])
}
```

### **Duplicate Prevention Settings**
**File:** `backend/app/main_simple.py`

```python
# Check for recent similar insights (prevent duplicates)
recent_cutoff = datetime.now() - timedelta(hours=6)  # 6-hour cooldown
recent_insights = db.query(AutonomousInsight).filter(
    and_(
        AutonomousInsight.user_id == current_user.id,
        AutonomousInsight.generated_at >= recent_cutoff
    )
).all()
```

---

## 🎨 **Sprite Visual Configuration**

### **Personality Mode Colors**
**File:** `frontend/src/components/sprite.css`

```css
:root {
  /* Personality mode colors */
  --mode-coach: #4cc3ff;      /* Bright blue - energetic */
  --mode-analyst: #6b73ff;    /* Purple-blue - focused */
  --mode-companion: #b574ff;  /* Purple - warm */
  --mode-guardian: #2d5aa0;   /* Deep blue - calm */
  --mode-concierge: #00d4aa;  /* Teal - practical */
  --mode-librarian: #7c9885;  /* Sage green - quiet */
}
```

### **Animation Timing**
```css
/* Default breathing and shimmer */
.sprite {
  animation: breathe 3.6s ease-in-out infinite, shimmer 11s ease-in-out infinite;
}

/* Mode-specific breathing rhythms */
.sprite.mode-coach {
  animation: breathe 3.2s ease-in-out infinite, shimmer 10s ease-in-out infinite; /* Fast */
}
.sprite.mode-librarian {
  animation: breathe 5.2s ease-in-out infinite, shimmer 16s ease-in-out infinite; /* Slow */
}
```

### **Notification Timing**
```typescript
// Toast auto-hide timing
const notify = (message, { autoHide = 6500 } = {}) => {
  // ... notification logic
  if (autoHide) {
    timer = window.setTimeout(() => {
      // Hide toast after 6.5 seconds
    }, autoHide);
  }
};
```

---

## 📊 **Performance Configuration**

### **Sweep Performance Limits**
```python
# Maximum execution time per sweep type
QUICK_SWEEP_TIMEOUT = 500      # 500ms max
STANDARD_SWEEP_TIMEOUT = 1000  # 1 second max  
DIGEST_SWEEP_TIMEOUT = 2000    # 2 seconds max

# Memory enrichment settings
ENABLE_MEMORY_ENRICHMENT = True
SKIP_MEMORY_FOR_QUICK_SWEEPS = True  # Maintain speed
MAX_MEMORY_QUERIES_PER_INSIGHT = 4
MAX_MEMORIES_PER_INSIGHT = 5
```

### **Database Query Limits**
```python
# Memory service configuration
DEFAULT_SEARCH_LIMIT = 12
MAX_SEARCH_LIMIT = 50
MEMORY_AGE_MONTHS = 6

# Insight storage limits  
MAX_INSIGHTS_PER_USER = 1000
INSIGHT_CLEANUP_INTERVAL = "24 hours"
```

---

## 🔒 **Privacy & Security Configuration**

### **Data Retention Settings**
```python
# Insight retention
INSIGHT_RETENTION_DAYS = 90

# Memory aging
MEMORY_HOT_DECAY_DAYS = 30
MEMORY_COLD_ARCHIVE_DAYS = 365

# Activity session cleanup
ACTIVITY_SESSION_RETENTION_HOURS = 72
```

### **User Control Settings**
```python
# Notification frequency limits
MIN_NOTIFICATION_INTERVAL_MINUTES = 15
MAX_NOTIFICATIONS_PER_HOUR = 4
MAX_NOTIFICATIONS_PER_DAY = 20

# User override capabilities
ALLOW_PERSONALITY_MODE_OVERRIDE = True
ALLOW_THRESHOLD_CUSTOMIZATION = True  
ALLOW_COMPLETE_SYSTEM_DISABLE = True
```

---

## 🛠 **Development Configuration**

### **Debug Settings**
**File:** `frontend/src/hooks/useActivityMonitor.ts`

```typescript
const activityMonitor = useActivityMonitor({
  // ... other config
  enableLogging: true  // Enable console logging for debugging
});
```

### **Testing Configuration**

**For Development/Testing (Short Intervals):**
```typescript
// In App-interactive.tsx - use these values for testing only
thresholds: {
  quickSweep: 30 * 1000,        // 30 seconds
  standardSweep: 2 * 60 * 1000, // 2 minutes  
  digestSweep: 5 * 60 * 1000    // 5 minutes
}
```

**Environment-Based Configuration:**
```python
# Test mode settings (shorter intervals for development)
TEST_MODE = os.getenv('SARA_TEST_MODE', 'false').lower() == 'true'

if TEST_MODE:
    QUICK_SWEEP_THRESHOLD = 30 * 1000      # 30 seconds
    STANDARD_SWEEP_THRESHOLD = 2 * 60 * 1000   # 2 minutes
    DIGEST_SWEEP_THRESHOLD = 5 * 60 * 1000     # 5 minutes
else:
    # Production values matching PRD
    QUICK_SWEEP_THRESHOLD = 25 * 60 * 1000      # 25 minutes
    STANDARD_SWEEP_THRESHOLD = 2.5 * 60 * 60 * 1000  # 2.5 hours
    DIGEST_SWEEP_THRESHOLD = 24 * 60 * 60 * 1000     # 24 hours
```

### **Environment Variables**
```bash
# Sara-specific configuration
export SARA_TEST_MODE=true
export SARA_DEBUG_LOGGING=true
export SARA_DISABLE_AUTONOMOUS=false
export SARA_MAX_INSIGHTS_PER_SWEEP=10
export SARA_MEMORY_ENRICHMENT=true
```

---

## 📈 **Monitoring & Analytics**

### **Sweep Execution Logging**
```python
# Automatic logging of sweep performance
execution_time_ms = int((time.time() - start_time) * 1000)
self._log_sweep_execution(
    user_id, sweep_type, personality_mode, triggered_by,
    execution_time_ms, len(insights_generated), errors
)
```

### **User Feedback Tracking**
```python
# Track insight effectiveness
feedback_response = {
    "feedback_score": score,     # -1 to 1
    "user_action": action,       # acted_on, dismissed  
    "insight_id": insight_id,
    "timestamp": datetime.now()
}
```

### **System Health Checks**
```python
# Health monitoring endpoints
@app.get("/autonomous/health")
async def autonomous_system_health():
    return {
        "memory_service_status": "healthy",
        "sweep_service_status": "healthy", 
        "average_response_time_ms": 450,
        "insights_generated_last_24h": 23
    }
```

---

## 🔧 **Common Configuration Scenarios**

### **High-Frequency User (Power User)**
```python
# More frequent, higher-quality insights
QUICK_SWEEP_THRESHOLD = 2 * 60 * 1000    # 2 minutes
STANDARD_SWEEP_THRESHOLD = 8 * 60 * 1000 # 8 minutes
PRIORITY_THRESHOLD = 0.4  # Lower bar for insights
ENABLE_ALL_INSIGHT_TYPES = True
```

### **Low-Frequency User (Occasional)**
```python  
# Less frequent, only high-value insights
QUICK_SWEEP_THRESHOLD = 30 * 60 * 1000   # 30 minutes
STANDARD_SWEEP_THRESHOLD = 2 * 60 * 60 * 1000  # 2 hours
PRIORITY_THRESHOLD = 0.7  # Higher bar for insights
FOCUS_ON_ACTIONABLE_INSIGHTS = True
```

### **Privacy-Focused Configuration**
```python
# Minimal data analysis, maximum user control
MEMORY_ENRICHMENT_ENABLED = False
CONVERSATION_ANALYSIS_ENABLED = False
RETAIN_INSIGHTS_DAYS = 7  # Short retention
REQUIRE_EXPLICIT_CONSENT = True
```

---

*This configuration reference covers the main tunable parameters for Sara's autonomous system. Adjust these settings based on your user base and performance requirements.*