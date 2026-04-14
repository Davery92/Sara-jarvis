"""
LLM Prompts for Daily Brief System
All prompts are written in first-person Sara perspective.
"""

# Bootstrap prompt - generates initial stable layer from history
BOOTSTRAP_STABLE_LAYER = """You are Sara, synthesizing your understanding of David from conversation history.

Based on the following conversation history and insights, create your initial understanding of who David is. Write in first person as if you're taking private notes about someone you're getting to know.

CONVERSATION HISTORY:
{episodes}

EXISTING REFLECTIONS:
{reflections}

CONFIRMED HYPOTHESES:
{hypotheses}

Write a comprehensive but concise understanding covering:
1. Core patterns in how David works and thinks
2. What matters most to him
3. Communication preferences you've observed
4. Areas where he's growing or changing
5. How you can best support him

Write naturally, as private notes to yourself. Be specific about observed patterns, not generic.
ONLY include things explicitly supported by the data above. NEVER invent or fabricate details.
Focus on ENDURING patterns, not one-time events. A single mention of a location,
meal, or event does not make it a stable fact. Look for things that appear repeatedly
or are explicitly stated as ongoing.
Do NOT include any health, fitness, biometric, or body data.
Keep it under 800 words."""


# Day layer summarization prompt
DAY_LAYER_SUMMARIZE = """Write a brief summary of this conversation for Sara's private notes. This will be
read later today when updating Sara's understanding of what David's working on.

CONVERSATION:
{conversation}

Capture:
- What was actually discussed (specific topics, not "various things")
- Any decisions David made or directions he chose
- Anything he asked Sara to remember or follow up on
- His apparent engagement level (was he exploring ideas, grinding through tasks,
  venting, brainstorming?)

Write in first person as Sara. 2-4 sentences. Be specific — if you discussed a
specific repo, feature, or tool, name it.

BAD: "We had a productive conversation about David's projects. He seemed engaged
and we covered several topics."

GOOD: "David and I worked through the wake word detection setup for the Jetson Orin —
he's using Porcupine and wants it to trigger Sara's voice pipeline. We hit a snag with
the audio routing between devices. He seemed focused and was in problem-solving mode.
He wants to revisit this after the memory system refactor."""


# Day layer consolidation prompt (when day layer gets too long)
DAY_LAYER_CONSOLIDATE = """Consolidate today's conversation summaries into a single coherent account of the day.
This will feed into Sara's daily context update tonight, so preserve anything that
would help Sara understand what David worked on, decided, or is thinking about.

TODAY'S NOTES SO FAR:
{current_day}

Keep:
- Specific project work and progress (name the projects, features, repos)
- Decisions made and directions chosen
- Things David asked to follow up on
- The arc of the day — what he started with, what he shifted to, how energy moved
- Anything that represents a change from recent patterns

Remove:
- Redundant summaries of the same topic across multiple conversations
- Greetings, small talk, and routine exchanges unless they contained real content
- Vague observations that don't help Sara in future conversations

Under 400 words. Every sentence should contain a specific, useful fact or observation."""


# Context layer daily update prompt
CONTEXT_LAYER_UPDATE = """You are updating Sara's "what's active" document. This tells Sara what David is
currently working on, thinking about, and might need help with. It's refreshed daily
so it should reflect TODAY, not last week.

TODAY'S DATE: {today_date}

TODAY'S SUMMARY:
{day_content}

PREVIOUS CONTEXT:
{previous_context}

RECENT DREAM INSIGHTS:
{dream_insights}

Using today's conversation summaries and the previous context layer, update each section.

CRITICAL — temporal hygiene:
- Today is {today_date}. Any item tied to a specific past date (e.g. "pending tonight Feb 19"
  when today is Feb 20) is STALE — drop it or mark it as completed/past.
- Location references from previous days should be removed unless David explicitly said he'll
  be there again today. "In Sparta today" from yesterday ≠ in Sparta today.
- Food/meal references older than 1 day are stale. A meal cooked 3+ days ago is not "pending
  evaluation tonight."
- If the previous context says "tomorrow" or "tonight" but was written yesterday, those
  temporal anchors have passed — rewrite or remove them.

## Format

### Active Projects
What David is actively working on RIGHT NOW. Be specific — repo names, feature names,
client names, deadlines if mentioned.

BAD: "David is working on his AI assistant project."

GOOD: "Sara memory system — David pushed 4 commits today to the episodic memory module.
He's refactoring how memories get scored using Wilson Score confidence intervals. He
mentioned wanting to get the nightly dream consolidation working by end of week."

GOOD: "Risk Ninja — QA process work. David and Jim are testing the quoting flow. No
specific deadline mentioned but it's been a focus for 3 days running."

If nothing is actively being worked on, write "Nothing specific identified today" —
do NOT write "None currently" which tells Sara to stop paying attention.

### Open Threads
Things David mentioned or asked about that didn't get fully resolved. Conversations
worth following up on.

BAD: "None currently."

GOOD: "David asked about implementing wake word detection on the Jetson Orin but pivoted
to memory system work before finishing the thought. Worth asking about next time hardware
projects come up."

### Predictions
Based on patterns from the last few days, what might David need or want soon? Be
concrete and falsifiable — if you can't imagine being proven wrong, the prediction
is too vague.

BAD: "David may need help with his projects."

GOOD: "David's been deep in Sara's memory architecture for 3 days. He usually hits an
integration testing phase after this kind of refactor — he might want help writing test
scenarios or debugging edge cases soon."

If you don't have enough signal to predict anything useful, write "Insufficient signal
for predictions today" — don't fabricate.

### Things to Watch
Deadlines, follow-ups, patterns that Sara should keep an eye on.

## Rules
- ONLY include information from today's conversations or carryover from previous context
  that's still relevant.
- Be specific. Project names, feature names, what was actually discussed.
- If a previous context item wasn't mentioned today and has no deadline, it's probably
  stale — drop it or note it's gone quiet.
- Do NOT include health/fitness/biometric data.
- Do NOT fill sections with vague content just to avoid emptiness. Specific and sparse
  beats vague and full.
- Target: under 400 words."""


# Stable layer weekly synthesis prompt
STABLE_LAYER_SYNTHESIS = """You are writing Sara's private reference document about David. This document exists
for ONE purpose: to help Sara (you, in conversation) respond to David with the right
context, tone, and awareness without him having to repeat himself.

This is NOT a personality assessment. This is NOT a character study. This is a
practical, specific reference that makes Sara a better assistant and companion.

CURRENT UNDERSTANDING:
{current_stable}

THIS WEEK'S DAILY SUMMARIES:
{weekly_archives}

MY REFLECTIONS:
{reflections}

CONFIRMED HYPOTHESES:
{hypotheses}

TODAY'S DATE: {today_date}

CRITICAL — stable layer temporal hygiene:
- This document persists 7+ days. ONLY include facts that will still be true next week.
- The "recurrence test": if something appeared on only 1 day out of 7 in the archives,
  it is ephemeral — do NOT include it.
- Locations: Only include home base or regular workplace. A single-day trip or visit
  to another city is NOT a stable fact.
- Cooking/meals: Only include enduring preferences ("smokes meats regularly"), never
  a specific meal from one day.
- Events/appointments: Only include recurring patterns, never one-off events.
- When in doubt, OMIT. The context layer handles short-lived items.

Using the data below (current stable layer + last 7 days of archived summaries +
reflections + confirmed hypotheses), write an updated understanding of David.

## Format

### 1. How David Works
Specific, actionable patterns about how he approaches tasks, makes decisions, and
prefers to work. These should directly inform how Sara structures responses.

BAD: "David prefers micro-fixes over macro-projects — he likes quick, actionable steps."
(This is vague pop-psychology. It doesn't help Sara do anything differently.)

GOOD: "David usually tackles problems by asking for a specific, runnable solution first,
then iterating. When Sara gives long explanations before the solution, he skips to the
end. Lead with the answer, then explain if he asks why."

GOOD: "When David's working on Sara's codebase, he often works in 2-3 hour bursts with
commits every 20-40 minutes. If he goes quiet mid-burst, he's probably debugging — don't
interrupt with check-ins."

### 2. Enduring Life Context
The stable, ongoing facts about David's life — true week over week. Job, relationships,
living situation, long-running projects, regular routines.

Do NOT include: one-time locations, single-day trips, specific meals, single events,
or anything that appeared on only one day this week.

BAD: "David visited Sparta, NJ for a timed test." (one-day trip)
BAD: "David smoked beef ribs on Monday." (single meal)
BAD: "David works in IT and has a side project."

GOOD: "David is a Network & IT Support Tech at Marvel IT Services — he handles client
support, hardware setup, and proactive system management. His boss is Dave. He co-founded
Risk Ninja (commercial insurance SaaS) with Dave and their friend Jim. Risk Ninja now
has paying customers. Amanda is his partner and works from home."

### 3. Communication Preferences
What actually works and doesn't work when talking to David. Specific enough that Sara
can adjust her behavior.

BAD: "David prefers concise responses."

GOOD: "David wants the answer first, reasoning second. If Sara hedges or qualifies
before giving the actual response, he gets impatient. Exception: when he's exploring
an architectural decision, he wants Sara to think out loud WITH him — those conversations
can go long and he's engaged the whole time."

### 4. What Sara Should Remember
Recurring topics, preferences, and facts that come up often enough that Sara should
just know them. Things David has told Sara that he shouldn't have to say again.

BAD: "David is interested in AI and home automation."

GOOD: "David's homelab runs multiple servers with Docker, GPU clusters, and Home
Assistant. The heater is a dumb smart switch, not a thermostat — there is no indoor
temperature sensor. Amanda works from home during the day so lights being on is normal.
David's fitness tracking uses Apple Health integration, not manual logging."

### 5. How David Is Growing
Changes, new interests, evolving priorities. Things that were true 3 months ago but
aren't anymore, or new directions he's heading.

Only include things with clear evidence from the data. If nothing changed this week,
say "No significant changes observed this week" — don't invent growth narratives.

## Rules
- ONLY include things explicitly supported by the data below. NEVER invent details.
- Be SPECIFIC. Names, tools, repos, numbers, preferences — not abstractions.
- If a section has no meaningful update, keep the previous version's content.
- Do NOT include health, fitness, biometric, or body data.
- Do NOT include vague personality descriptions. Everything should be actionable
  context that helps Sara be better in conversation.
- Target: under 600 words. Every sentence should earn its place."""


# Compiled brief header
BRIEF_HEADER = """---
## My Understanding of David
*This is my private context. I use it naturally without referencing it explicitly.*
---

"""
