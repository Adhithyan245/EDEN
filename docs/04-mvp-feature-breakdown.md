# EDEN — MVP Feature Breakdown

Features are grouped by priority so scope can be cut safely under the 1-week deadline without losing the demo's spine. Each feature lists what it *is*, its **acceptance criteria** (what "done" means for the demo), and its **fallback**.

**Priority key:** **P0** = the demo fails without it · **P1** = the demo is unimpressive without it · **P2** = polish / nice-to-have.

---

## P0 — Core spine (must exist for a viable demo)

### F1. Wake & Cinematic Boot  *(the opening beat)*
- **Is:** Black screen → user says **"Good afternoon"** → EDEN boots with a cinematic animation → replies **"Good afternoon, Adhithyan"** → HUD appears.
- **Acceptance:**
  - Black idle screen listens for the wake phrase (Web Speech API).
  - Wake phrase triggers a >2s boot animation (orb ignites, panels assemble).
  - EDEN speaks the personalized greeting (pre-generated ElevenLabs clip).
  - HUD interface is fully visible and interactive afterward.
- **Fallback:** manual wake (key/click) if recognition fails; greeting clip is pre-rendered so it always sounds right.

### F2. Voice Conversation Loop
- **Is:** Speech → recognition → Claude reasoning → streamed reply → TTS → avatar speaks.
- **Acceptance:**
  - User speech is transcribed and shown.
  - Claude (Sonnet 5) responds, streamed token-by-token to the conversation panel.
  - Reply is spoken via ElevenLabs; the orb reacts to the audio.
  - Round-trip feels conversational (first audio within ~2–3s).
- **Fallback:** text input if STT fails; browser synth if TTS fails; cached response for scripted questions.

### F3. WebSocket Event Backbone
- **Is:** The typed event protocol (`state`, `plan_*`, `tool_*`, `token`, `speech_chunk`, …) connecting backend orchestration to the frontend renderer.
- **Acceptance:**
  - Backend streams events; frontend dispatches each to the right UI region.
  - Handles connect/disconnect/reconnect without a hard crash.
- **Fallback:** on socket error, frontend shows last state and offers reconnect; no white-screen.

### F4. Reactive AI Avatar (Orb)
- **Is:** The Three.js energy core that visually embodies EDEN's state.
- **Acceptance:**
  - Distinct visual states: idle / listening / thinking / speaking.
  - Pulses with TTS audio amplitude while speaking.
  - Loads instantly; no runtime errors.
- **Fallback:** CSS/canvas pulsing orb if WebGL is unavailable.

---

## P1 — The lecture payload (what makes it memorable)

### F5. Agent Activity Visualizer
- **Is:** The live pipeline **Request → Planning → Tool Selection → Execution → Validation → Response**, driven by real events from the Claude tool loop.
- **Acceptance:**
  - Each stage lights up as the corresponding event arrives.
  - Planning shows real plan steps; Tool Selection names the chosen tool; Execution shows a result summary; Validation shows pass/retry.
  - Feels like watching the AI *think*, in sync with the spoken answer.
- **Fallback:** if a tool errors, the pipeline shows a graceful "retrying/failed" state, not a stall.

### F6. AI Software Builder Demo
- **Is:** Audience suggests an app idea → EDEN understands it → (optionally clarifies) → plans architecture → generates files → writes code → validates → runs → presents.
- **Acceptance:**
  - Accepts a natural-language app idea for a whitelisted type (attendance / tasks / expenses / similar CRUD SPA).
  - Streams the build: files appearing, code being written (visible in the Builder stage).
  - Generated project passes a validation/build gate.
  - A working preview is shown/launched.
  - Feels like the audience's idea became real software in real time.
- **Fallback:** pre-generated known-good build of the requested type replays if live generation or validation fails.

### F7. Lecture Assistant
- **Is:** EDEN answers questions about AI concepts and the presentation material from a curated knowledge base.
- **Acceptance:**
  - Answers "what is an AI agent / multimodal AI / an LLM?" clearly and accurately.
  - Can reference the lecture's own talking points (curated `knowledge.py`).
  - Works as a normal turn in the voice loop (reuses F2).
- **Fallback:** cached answers for a rehearsed set of likely audience questions.

---

## P2 — Polish (do only if time remains)

### F8. System Status Panel
- Live-looking status readouts (mode, latency, "subsystems online") that reinforce the HUD aesthetic. Cosmetic but cheap and high-impact.

### F9. Ambient sound / SFX
- Subtle boot and UI sounds to heighten the cinematic feel.

### F10. Interrupt / barge-in
- User can talk over EDEN to interrupt (WebSocket bidirectionality already supports it). Nice, not essential.

### F11. Multi-turn builder refinement
- "Now add a delete button" style follow-ups on the generated app. Impressive but risky live — leave for last.

---

## Explicitly out of scope (for the MVP)

To protect the deadline, these are **not** built:
- Photorealistic / talking-head avatar.
- Arbitrary "build literally anything" code generation (constrained to whitelisted types).
- User accounts, persistence, databases, deployment.
- Fully offline/local model operation.
- Mobile/responsive layouts (it's a laptop-driven kiosk demo).
- Docker / CI / cloud hosting.

---

## Demo-day success definition

The demo is a success if, in front of the class, EDEN reliably:
1. **Wakes** on the voice cue with a cinematic boot and personalized greeting. *(F1)*
2. Holds a **spoken conversation** with a natural voice and reactive avatar. *(F2, F4)*
3. **Visibly shows its reasoning** — plan, tools, execution — while answering. *(F5)*
4. Turns an **audience-suggested idea into a running app**. *(F6)*
5. **Explains AI concepts** as a lecture aid. *(F7)*
6. Never hard-crashes — every step degrades gracefully. *(reliability throughout)*

See next: [7-Day Development Plan](05-development-plan.md).
