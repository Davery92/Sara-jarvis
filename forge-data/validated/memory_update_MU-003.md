## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, 26 tools"
project.sara.tools: "Registered in app/tools/registry.py. Categories: memory, notes, reminders, timers, calendar."
project.sara.tools.debugging: "Tool calls logged to agent_run_log table. Debug via /debug/notification-funnel endpoint."
```

## SESSION 1

### Turn 1

**David:** the tool debugging approach needs to change. right now we log tool calls to agent_run_log but there's no way to replay a failed tool call. I want to add input/output capture so I can replay any tool execution

**Sara (internal generation stream):**

<mem_read key="project.sara.tools.debugging">
  <mem_result>Tool calls logged to agent_run_log table. Debug via /debug/notification-funnel endpoint.</mem_result>
</mem_read>

<mem_write key="project.sara.tools.debugging.replay_plan" importance="0.65" decay="medium">
David planning to add tool call replay capability. Current: tool calls logged to agent_run_log without input/output capture. Proposed: capture full input/output for replay.
</mem_write>

**Sara (user-visible response):**

Input/output capture for replay is the right investment — debugging tool failures from logs alone is painful. The minimal approach: serialize the tool call input (arguments) and output (result or exception) as JSON in the agent_run_log entry. Then a replay endpoint that takes a log entry ID and re-executes the tool with the captured inputs.

Are you capturing the tool context too (memory state, user context at call time)? Without that, a replay might produce different results because the surrounding state changed.

### Turn 2

**David:** good point — I need the context snapshot too. so each log entry gets: tool name, input args, output result, execution time, and a snapshot of the relevant context keys

**Sara (internal generation stream):**

<mem_update key="project.sara.tools.debugging">
Tool debugging: agent_run_log captures tool name, input args, output result, execution time, and context key snapshot for replay capability. Debug endpoint at /debug/notification-funnel.
</mem_update>

**Sara (user-visible response):**

That's a complete replay payload. For the context snapshot, keep it light — only the memory keys the tool actually read during execution, not the full working memory. You can get that by instrumenting the mem_read calls within each tool to record which keys they accessed.

Schema addition to agent_run_log:
```sql
ALTER TABLE agent_run_log ADD COLUMN tool_input JSONB;
ALTER TABLE agent_run_log ADD COLUMN tool_output JSONB;
ALTER TABLE agent_run_log ADD COLUMN context_snapshot JSONB;
ALTER TABLE agent_run_log ADD COLUMN execution_ms INTEGER;
```

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, 26 tools"
project.sara.tools: "Registered in app/tools/registry.py."
project.sara.tools.debugging: "agent_run_log with full input/output/context capture for replay. Debug endpoint at /debug/notification-funnel."
```

---

*Time gap: next day*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** actually, I changed my mind on the tool debugging approach. capturing full input/output for every tool call is too much data — the agent_run_log table would balloon. going with a sampling approach instead: only capture full payloads for failed calls and a random 10% sample of successful ones

**Sara (internal generation stream):**

<mem_read key="project.sara.tools.debugging">
  <mem_result>agent_run_log with full input/output/context capture for replay.</mem_result>
</mem_read>

<mem_update key="project.sara.tools.debugging">
Tool debugging: agent_run_log with sampled payload capture. Failed calls: always capture full input/output/context. Successful calls: 10% random sample captures full payload. Prevents table bloat while maintaining replay capability for failures.
</mem_update>

**Sara (user-visible response):**

Sampling is the right trade-off. 100% capture on failures gives you full replay for the cases that matter, and 10% sampling on successes gives you enough data for profiling and optimization without the storage cost. The table stays manageable.

For the sampling: use a deterministic hash of the request ID modulo 10, not random() — that way the sampling is reproducible and you can explain which calls were captured vs. not.

### Turn 2

**David:** deterministic hash — nice, hadn't thought of that. yeah I'll use the run_id hash. thanks

**Sara (internal generation stream):**

<reflect confidence="0.85">
David accepting the deterministic hash suggestion. Minor implementation detail — the key decision (sampling approach) is already captured. Session close.
</reflect>

**Sara (user-visible response):**

`hash(run_id) % 10 == 0` for the 10% sample. Clean and reproducible.

## Memory State (After Session 2)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, 26 tools"
project.sara.tools: "Registered in app/tools/registry.py."
project.sara.tools.debugging: "agent_run_log: 100% capture on failures, 10% deterministic sample on successes. Captures tool input/output/context for replay."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_read>` | `project.sara.tools.debugging` | Recall current debugging approach. |
| S1T1 | `<mem_write>` | `project.sara.tools.debugging.replay_plan` | New plan: replay capability. |
| S1T2 | `<mem_update>` | `project.sara.tools.debugging` | Update with full schema: input, output, context snapshot, execution time. |
| S2T1 | `<mem_read>` | `project.sara.tools.debugging` | Recall current approach. |
| S2T1 | `<mem_update>` | `project.sara.tools.debugging` | Direction changed: sampling instead of 100% capture. UPDATE same key. "Got it" style — no apology for previous approach. |
| S2T2 | `<reflect>` | — | Implementation detail accepted. Key decision already captured. |
