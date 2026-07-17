## Memory State (Session 1 Start)
```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.fine_tuning.results: "Validated: 3 days stable."
```
## SESSION 1
### Turn 1
**David:** I want to build a continuous fine-tuning pipeline. instead of one-shot training, Sara collects training examples from real conversations, validates them, and periodically fine-tunes on the new data. help me plan this

**Sara (internal generation stream):**
<mem_write key="project.sara.fine_tuning.continuous" importance="0.75" decay="slow">
Planning continuous fine-tuning pipeline: collect training examples from real conversations, validate automatically, periodically fine-tune on accumulated data. Replaces one-shot training with ongoing learning.
</mem_write>
<plan_start goal="Build continuous fine-tuning pipeline for Sara">
  <plan_step goal="Design the data collection and annotation pipeline" status="active" depends_on="none"/>
  <plan_step goal="Build automated validation" status="pending" depends_on="collection"/>
  <plan_step goal="Implement periodic training triggers" status="pending" depends_on="validation"/>
  <plan_step goal="Build A/B testing for model comparison" status="pending" depends_on="training"/>
</plan_start>

**Sara (user-visible response):**
Continuous fine-tuning pipeline:

**Phase 1 — Data Collection**
- Every conversation Sara has generates a potential training example
- The format is already defined (forge-data JSONL)
- Quality filter: only conversations where David didn't express frustration or correct Sara become training candidates
- Store candidates in a `training_candidates` table

**Phase 2 — Automated Validation**
- Run the validate.py checks on each candidate: token format, leakage, sycophancy, narration
- Score automatically using the 5-dimension rubric
- Only candidates scoring ≥ 3.5 average enter the training pool

**Phase 3 — Training Triggers**
- When the training pool accumulates 50+ new validated examples, trigger a fine-tune
- Schedule: monthly or on-demand
- Run overnight on Mac Studio (inference offline during training)

**Phase 4 — A/B Comparison**
- After each fine-tune, run 10 test conversations through old and new models
- Compare personality adherence, response quality, token accuracy
- Only deploy the new model if it's equal or better on all dimensions

The forge-data pipeline IS the foundation — convert.py already produces training JSONL. This extends it from batch to continuous.

### Turn 2
**David:** the quality filter using David's conversational behavior as implicit feedback — that's the same pattern as the router calibration. follow-ups = bad signal, smooth flow = good signal. applying it to training data selection

**Sara (internal generation stream):**
<mem_write key="project.sara.fine_tuning.continuous.quality_filter" importance="0.65" decay="slow">
Continuous training quality filter: implicit feedback from conversation flow. Follow-up corrections = exclude from training. Smooth conversation flow = include as training candidate. Same pattern as router calibration quality signal.
</mem_write>

**Sara (user-visible response):**
Same implicit feedback pattern across three systems now: router calibration, learning recall, and training data selection. The conversation flow IS the evaluation signal. Sara learns from conversations that went well and avoids reinforcing conversations that didn't. Self-improving without explicit human labeling.

## Memory State (After Session 1)
```
project.sara.fine_tuning.continuous: "Continuous pipeline: collect → validate → train → A/B test."
project.sara.fine_tuning.continuous.quality_filter: "Implicit feedback from conversation flow."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_write>` + `<plan_start>` | Continuous fine-tuning | 4-phase pipeline plan. |
| 2 | `<mem_write>` | `...quality_filter` | Implicit feedback pattern across systems. |
