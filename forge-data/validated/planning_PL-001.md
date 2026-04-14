## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI, PostgreSQL/pgvector, Redis, Neo4j, Celery"
project.sara.voice: "Separate project at /home/david/Projects/sara-voice/ (Jetson Orin Nano)"
project.sara.voice.pipeline: "AIRHUG capture → noise gate → wake word → VAD → STT → backend"
project.sara.voice.state_machine: "IDLE→WAKE→LISTENING→PROCESSING→SPEAKING→COOLDOWN + barge-in"
```

## SESSION 1

### Turn 1

**David:** the voice pipeline end-to-end latency is too high. from the moment I stop speaking to when Sara starts responding, it's like 4-5 seconds. I need to get that under 2 seconds. help me plan the optimization

**Sara (internal generation stream):**

<mem_write key="project.sara.voice.latency.current" importance="0.75" decay="medium">
Sara voice pipeline end-to-end latency: 4-5 seconds from end of speech to start of response. Target: under 2 seconds.
</mem_write>

<plan_start goal="Reduce Sara voice pipeline latency from 4-5s to under 2s">
  <plan_step goal="Profile current pipeline to identify bottleneck stages" status="pending" depends_on="none"/>
  <plan_step goal="Optimize the slowest stage(s)" status="pending" depends_on="profiling"/>
  <plan_step goal="Validate end-to-end latency meets 2s target" status="pending" depends_on="optimization"/>
</plan_start>

**Sara (user-visible response):**

4-5 seconds is too long for conversational voice — it breaks the natural rhythm. Let's map the pipeline stages and find out where the time is going.

Your pipeline: AIRHUG capture → noise gate → wake word → VAD → STT → backend LLM → TTS → audio output.

The latency is between "end of speech" and "start of response," so we're measuring: VAD endpoint detection + STT transcription + network round-trip + LLM inference + TTS first-chunk. Let's profile each:

| Stage | Expected Latency | Likely Actual | Notes |
|-------|-----------------|---------------|-------|
| VAD endpoint detection | 200-500ms | 500-800ms? | VAD has to wait for silence to confirm speech is done |
| STT transcription | 200-500ms | 500-1000ms? | Depends on model and whether it's streaming |
| Network (Jetson → backend) | 5-20ms | 5-20ms | LAN, negligible |
| LLM inference (first token) | 200-500ms | 1000-2000ms? | Depends on model, context length, and hardware |
| TTS (first chunk) | 100-300ms | 200-500ms | Depends on TTS model |

Where do you think the biggest chunk is? If you haven't profiled yet, start by timestamping each stage transition in your state machine and logging the deltas.

### Turn 2

**David:** I have some rough numbers. VAD endpoint is about 600ms — it waits for 600ms of silence. STT is the big one — Whisper on the Jetson takes about 1.5 seconds for a typical utterance. then LLM inference is about 1.2 seconds to first token on the 1070. TTS is fast, maybe 200ms for the first chunk

**Sara (internal generation stream):**

<mem_write key="project.sara.voice.latency.breakdown" importance="0.75" decay="medium">
Voice pipeline latency breakdown: VAD endpoint 600ms, STT (Whisper on Jetson) 1500ms, LLM first token (GTX 1070) 1200ms, TTS first chunk 200ms. Total: ~3.5s (plus overhead). STT is the primary bottleneck.
</mem_write>

**Sara (user-visible response):**

So the breakdown is: 600 + 1500 + 1200 + 200 = 3500ms plus overhead. STT at 1.5 seconds is the biggest single stage, and LLM at 1.2 seconds is second.

Here's the optimization plan, ordered by impact:

**Phase 1 — STT optimization (target: save 1000ms)**
- Switch from batch Whisper to **streaming STT**. Instead of waiting for the full utterance, start transcribing as speech arrives. By the time VAD detects the endpoint, you already have most of the transcript.
- Alternatively: use **Whisper distilled** (distil-whisper-large-v3) which is 5-6x faster with minimal accuracy loss. On the Jetson, that could cut STT from 1500ms to 300-500ms.
- Best: combine both — streaming distilled Whisper.

**Phase 2 — VAD tuning (target: save 200-300ms)**
- 600ms silence threshold is conservative. For conversational use, 300-400ms is typical. Below 300ms you'll get false endpoints mid-sentence.
- This is a config change, not a code change.

**Phase 3 — LLM optimization (target: save 400-600ms)**
- The dedicated GPU passthrough VM you're setting up should help — no contention.
- Reduce context length for voice responses. Full 64K context is overkill for voice turns. Use a voice-specific context budget (2000-4000 tokens).
- Consider a smaller model for voice responses if quality is acceptable.

**Phase 4 — Pipeline parallelism (target: save 200-300ms)**
- Start LLM prompt construction while STT is finishing the last few tokens.
- Start TTS as soon as the first sentence from the LLM is complete (streaming TTS).

Total potential savings: 1800-2200ms. That gets you from 3.5s to 1.3-1.7s — under your 2s target.

### Turn 3

**David:** ok this is solid. phase 1 is the big win. I'll start with distil-whisper — I've been meaning to try it anyway. what's the VRAM requirement on the Jetson?

**Sara (internal generation stream):**

<self_check domain="LLM inference / quantization">
  <self_result confidence="0.76" notes="Know the general specs for distil-whisper models. Jetson Orin Nano has 8GB shared memory. distil-whisper-large-v3 is ~1.5GB at fp16."/>
</self_check>

**Sara (user-visible response):**

distil-whisper-large-v3 is about 1.5GB at fp16. The Jetson Orin Nano has 8GB shared between CPU and GPU, so you've got room — but check how much the VAD model and other pipeline components are already using. You might need to run it at int8 quantization to fit comfortably alongside everything else. int8 distil-whisper is under 800MB and the accuracy hit is negligible for English speech recognition.

### Turn 4

**David:** I think I'm using about 3GB for the other pipeline components. so 1.5GB for the model is fine. I'll try fp16 first and fall back to int8 if I need the headroom. what about the VAD threshold — you said 300-400ms?

**Sara (internal generation stream):**

<reflect confidence="0.82">
David is asking about the VAD threshold recommendation. This is something I suggested — 300-400ms for conversational use. I'm confident in this range from voice UX research. No tool needed, no uncertainty to flag.
</reflect>

**Sara (user-visible response):**

300-400ms silence threshold for conversational turn-taking. Start at 400ms and test with your natural speaking patterns. If you're getting false endpoints (it cuts you off mid-sentence while you pause to think), bump it up to 450ms. If it feels sluggish, drop to 350ms.

The sweet spot is usually around 350-400ms for a technical user who pauses between thoughts. Below 300ms is too aggressive — natural speech has pauses of 200-300ms between clauses.

### Turn 5

**David:** alright, here's my plan: 1) swap to distil-whisper-large-v3 on the Jetson, 2) drop VAD threshold to 400ms, 3) test end-to-end latency. if I'm under 2 seconds with just those two changes, I'll defer the LLM and parallelism optimizations

**Sara (internal generation stream):**

<mem_write key="project.sara.voice.latency.optimization_plan" importance="0.70" decay="medium">
Voice latency optimization plan: (1) Swap Whisper to distil-whisper-large-v3 on Jetson, (2) Reduce VAD silence threshold from 600ms to 400ms, (3) Test E2E latency. LLM and pipeline parallelism deferred unless needed to hit 2s target.
</mem_write>

**Sara (user-visible response):**

That's the right sequencing — the two lowest-effort highest-impact changes first. If distil-whisper cuts STT from 1500ms to ~400ms and the VAD goes from 600ms to 400ms, you're looking at: 400 + 400 + 1200 + 200 = 2200ms. Just over target. But in practice the STT savings might be better than estimated — distil-whisper is often under 300ms on modern hardware. You might hit 2s without touching anything else.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.voice: "Separate project at /home/david/Projects/sara-voice/"
project.sara.voice.pipeline: "AIRHUG capture → noise gate → wake word → VAD → STT → backend"
project.sara.voice.state_machine: "IDLE→WAKE→LISTENING→PROCESSING→SPEAKING→COOLDOWN + barge-in"
project.sara.voice.latency.current: "4-5s end-to-end. Target: under 2s."
project.sara.voice.latency.breakdown: "VAD 600ms, STT (Whisper) 1500ms, LLM 1200ms, TTS 200ms."
project.sara.voice.latency.optimization_plan: "(1) distil-whisper-large-v3, (2) VAD 600→400ms, (3) test. LLM/parallelism deferred."
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

**David:** distil-whisper is running on the Jetson. STT is down to 380ms average. VAD at 400ms. end-to-end is 2.1 seconds — so close

**Sara (internal generation stream):**

<mem_read key="project.sara.voice.latency.*">
  <mem_result>Target under 2s. Plan: distil-whisper + VAD tuning. Breakdown: VAD 600ms, STT 1500ms, LLM 1200ms, TTS 200ms.</mem_result>
</mem_read>

<mem_update key="project.sara.voice.latency.breakdown">
Updated latency breakdown: VAD 400ms, STT (distil-whisper) 380ms, LLM 1200ms, TTS 200ms. Total: ~2.1s. 100ms over target.
</mem_update>

**Sara (user-visible response):**

380ms STT is a huge improvement — 1500 to 380. You're 100ms over target. The cheapest 100ms to find:

- Drop VAD to 350ms: saves 50ms, minimal risk
- The context budget change from Phase 3 — if voice turns use a 3000-token context instead of whatever you're currently sending, the LLM time-to-first-token drops. That's where the other 50-100ms lives.

You could also just call 2.1s good enough. The perceptual difference between 2.0 and 2.1 is negligible.

### Turn 2

**David:** 2.1 is close enough honestly. I'll try the VAD at 350 to see if it causes any issues but I'm not going to chase the last 100ms. the improvement from 4.5 to 2.1 is already massive

**Sara (internal generation stream):**

<mem_update key="project.sara.voice.latency.current">
Voice pipeline latency reduced from 4-5s to 2.1s. David accepting 2.1s as target met. May tune VAD to 350ms but not chasing further optimization.
</mem_update>

<mem_write key="project.sara.voice.stt_model" importance="0.65" decay="slow">
Sara voice STT: distil-whisper-large-v3 on Jetson Orin Nano. fp16. ~380ms average transcription time. Replaced full Whisper (was 1500ms).
</mem_write>

**Sara (user-visible response):**

4.5 to 2.1 is a 53% reduction from two config changes — distil-whisper swap and VAD tuning. That's a good place to stop. The Phase 3 and 4 optimizations are still available if you ever need to push below 2 seconds, but 2.1 is conversational.

## Memory State (After Session 2)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System"
project.sara.voice: "Separate project at /home/david/Projects/sara-voice/"
project.sara.voice.pipeline: "AIRHUG capture → noise gate → wake word → VAD → STT → backend"
project.sara.voice.state_machine: "IDLE→WAKE→LISTENING→PROCESSING→SPEAKING→COOLDOWN + barge-in"
project.sara.voice.latency.current: "2.1s end-to-end (down from 4-5s). Accepted as target met."
project.sara.voice.latency.breakdown: "VAD 400ms, STT (distil-whisper) 380ms, LLM 1200ms, TTS 200ms."
project.sara.voice.latency.optimization_plan: "Phases 1-2 COMPLETE. Phases 3-4 (LLM, parallelism) deferred."
project.sara.voice.stt_model: "distil-whisper-large-v3 on Jetson. fp16. ~380ms avg."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `project.sara.voice.latency.current` | Baseline latency and target captured. |
| S1T1 | `<plan_start>` | Reduce voice latency | High-level plan with profiling → optimization → validation phases. |
| S1T2 | `<mem_write>` | `project.sara.voice.latency.breakdown` | Per-stage latency numbers. Key diagnostic data. |
| S1T3 | `<self_check>` | LLM inference | distil-whisper VRAM question. Moderate confidence. |
| S1T4 | `<reflect>` | — | VAD threshold recommendation in known range. Confident, no hedging needed. |
| S1T5 | `<mem_write>` | `project.sara.voice.latency.optimization_plan` | David's 3-step plan with deferred phases. |
| S2T1 | `<mem_read>` | `project.sara.voice.latency.*` | Recall optimization context for results discussion. |
| S2T1 | `<mem_update>` | `project.sara.voice.latency.breakdown` | Updated with actual distil-whisper numbers. |
| S2T2 | `<mem_update>` | `project.sara.voice.latency.current` | New latency: 2.1s. David accepts as target met. |
| S2T2 | `<mem_write>` | `project.sara.voice.stt_model` | New STT model deployed. Slow decay — infrastructure change. |
