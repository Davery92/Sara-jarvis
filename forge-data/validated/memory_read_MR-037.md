## Memory State (Session 1 Start)
```
user.name: "David"
project.sara.voice: "Jetson Orin Nano. AIRHUG capture. Wake word + VAD + STT."
project.sara.voice.states: "IDLE→WAKE→LISTENING→PROCESSING→SPEAKING→COOLDOWN. Barge-in supported."
infra.mac_studio.models: "22B primary + 14B fast."
```
## SESSION 1
### Turn 1
**David:** drawing a diagram of Sara's voice pipeline for documentation. walk me through the full flow from audio capture to response

**Sara (internal generation stream):**
<mem_read key="project.sara.voice*">
  <mem_result>Jetson Orin Nano. AIRHUG capture. Wake word + VAD + STT. State machine: IDLE→WAKE→LISTENING→PROCESSING→SPEAKING→COOLDOWN. Barge-in supported.</mem_result>
</mem_read>
<mem_read key="infra.mac_studio.models">
  <mem_result>22B primary + 14B fast.</mem_result>
</mem_read>

**Sara (user-visible response):**
Full voice pipeline from memory:

1. **AIRHUG capture** on Jetson Orin Nano — continuous audio stream
2. **Noise gate** — filters ambient noise before processing
3. **Wake word detection** — transitions state from IDLE → WAKE
4. **VAD (Voice Activity Detection)** — WAKE → LISTENING, determines speech boundaries
5. **STT (Speech-to-Text)** — LISTENING → PROCESSING, transcribes the utterance
6. **Backend API call** — transcribed text sent to Sara's FastAPI backend
7. **LLM inference** — 14B fast model for routing, 22B primary for generation (Mac Studio)
8. **TTS** — generated response converted to speech
9. **PROCESSING → SPEAKING** — audio response played back
10. **SPEAKING → COOLDOWN** — brief cooldown period before returning to IDLE
11. **Barge-in** — user can interrupt during SPEAKING, jumps back to LISTENING

The Jetson handles steps 1-5 locally. Steps 6-8 hit the Mac Studio. Steps 9-11 are back on the Jetson. That's the split.

## Memory State (After Session 1)
```
[no changes — pure retrieval for documentation]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` (x2) | Voice pipeline + models | Full pipeline reconstruction from stored state. |
