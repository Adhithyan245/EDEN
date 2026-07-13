# EDEN — Technology Decisions

Each decision below is judged against the project's optimization order: **(1) demo impact, (2) reliability, (3) visual quality, (4) clean architecture — without over-engineering.** Every choice states the reasoning and the fallback.

---

## 1. Frontend framework — **React + TypeScript + Vite**

**Decision:** React 18 + TypeScript, bundled with Vite.

**Reasoning:** Required by the brief, and the right call anyway. Vite gives instant HMR (fast iteration in a 1-week build), TypeScript prevents whole classes of demo-day bugs, and React's ecosystem covers everything we need (animation, 3D, WebSocket). No SSR/Next.js — this is a single-page kiosk app, not a website; SSR would be over-engineering.

---

## 2. Styling & animation — **Tailwind CSS + Framer Motion**

**Decision:** Tailwind for layout/glassmorphism, Framer Motion for UI motion.

**Reasoning:** Glassmorphism (`backdrop-blur`, translucent panels, subtle borders) is trivial and consistent in Tailwind. Framer Motion gives us the smooth, spring-based transitions that sell the "premium" feel (panels sliding in, the boot sequence, agent nodes pulsing) with very little code. Together they deliver the Apple Vision Pro / Iron Man HUD look fast.

**Rejected:** hand-rolled CSS animations (slower to build, less consistent), heavy component libraries like MUI (wrong aesthetic — too "web app," not "HUD").

---

## 3. AI Avatar — **Abstract reactive orb via react-three-fiber (Three.js)**

**Decision:** An animated 3D energy core/orb that reacts to audio amplitude and EDEN's state — **not** a humanoid face.

**Reasoning:** This is the highest-leverage visual decision.
- **Reliability:** no rigging, no lip-sync engine, nothing to fail live.
- **Impact:** a glowing core that pulses as EDEN "breathes," "thinks," and "speaks" reads as unmistakably JARVIS/FRIDAY.
- **Cost:** an audio-reactive shader orb is a few hundred lines, loads instantly, and looks expensive.

**Rejected:** talking-head avatars (D-ID / ReadyPlayerMe) — uncanny, slow to load, a live-failure risk, and off-brand for a "system intelligence."

---

## 4. Backend framework — **Python FastAPI + WebSockets**

**Decision:** FastAPI, async, with a WebSocket endpoint as the primary channel.

**Reasoning:** Required, and ideal for our streaming event model. FastAPI's native async + WebSocket support lets us stream the agent's `plan → tool → execute → validate → respond` events and TTS audio to the browser in real time. Pydantic gives us typed, validated event schemas shared conceptually with the TS frontend. Uvicorn runs it with one command.

**Rejected:** Flask (weaker async/WebSocket story), Django (far too heavy for a demo).

---

## 5. Reasoning & agents — **Claude (Anthropic API)**

**Decision:** Claude via the official Anthropic Python SDK, using its **tool-use loop** to power the agent.

**Model tiering (deliberate):**

| Role | Model | Why |
|------|-------|-----|
| Voice conversation & lecture assistant | **`claude-sonnet-5`** | Fast, low-latency, cheap (intro pricing through 2026-08-31) — latency is felt directly in a voice loop. |
| Agent orchestration & software builder | **`claude-opus-4-8`** | Strongest reasoning and coding; the builder demo needs the best code generation. |
| (Optional) trivial classification | `claude-haiku-4-5` | If we need cheap intent routing. |

**Reasoning:** Claude's tool-use API *is* the agent — each iteration of the loop (the model requesting a tool, us executing it, feeding the result back) maps one-to-one onto the agent-visualization pipeline the lecture is about. We stream the loop as UI events. Adaptive thinking (`thinking: {type: "adaptive"}`) is on for the agent so we can surface real reasoning. Sonnet 5 keeps the conversational turns snappy.

**Key API notes (current):** use adaptive thinking (not `budget_tokens`); stream responses; set `output_config.effort` (`high`/`xhigh` for the builder). Keys stay server-side.

**Rejected:** OpenAI/other (single-vendor simplicity with ElevenLabs already chosen; Claude is the strongest coding model for the builder and integrates cleanly with the tool-loop visualization). Fully local LLM (quality + setup cost too high for one week; only justified if offline were mandatory — it isn't).

---

## 6. Speech-to-Text — **Browser Web Speech API**

**Decision:** `webkitSpeechRecognition` in the browser for STT and wake-phrase detection.

**Reasoning:** Zero-latency, zero-cost, no backend audio plumbing, works out of the box in Chrome (our demo browser). It handles both the wake phrase ("Good afternoon") via client-side string matching and ongoing dictation. Keeping STT in the browser removes a whole class of streaming-audio complexity from the backend.

**Fallback:** on-screen text input + push-to-talk (spacebar), always available. If recognition is flaky in a noisy hall, we type — the rest of EDEN is unaffected.

**Rejected:** cloud Whisper / Deepgram (adds latency, cost, and an audio-upload pipeline for marginal gain in a controlled demo). Custom wake-word engine like Porcupine (over-engineering — phrase matching on the transcript is enough).

---

## 7. Text-to-Speech — **ElevenLabs (streamed), layered fallback**

**Decision:** ElevenLabs streaming TTS for EDEN's voice; a deep, calm, JARVIS-like preset.

**Reasoning:** This is the difference between "chatbot with audio" and "AI companion." ElevenLabs is the clear leader in cinematic, natural voice — it's the single biggest audio-impact lever. Streamed so speech begins quickly; the orb reacts to its amplitude.

**Fallback ladder:** pre-generated ElevenLabs clips for scripted lines (boot greeting, key demo beats) → browser `SpeechSynthesis` for anything live if the API is down. The signature lines always sound premium because they're pre-rendered.

**Rejected:** browser-synth-only (robotic — kills the vibe), OpenAI TTS (good, but ElevenLabs is more cinematic and we're already multi-vendor-minimal with Claude).

---

## 8. AI Software Builder — **Constrained, template-assisted agent with validation**

**Decision:** A real Claude-driven agent that turns a spoken app idea into working code, but operating in a *controlled* environment: whitelisted app types, reusable templates/scaffolds, generated-code validation before "run," and a pre-generated fallback.

**Reasoning:** The brief wants a *genuinely interactive* builder (audience suggests the idea) that is also *reliable*. The resolution: constrain the surface, not the interactivity.
- **Supported types** (whitelisted): simple single-page apps — attendance tracker, task manager, expense tracker, and similar CRUD/list UIs. The agent adapts the audience's idea onto a known-good React scaffold.
- **Templates** provide the project skeleton (Vite + React + Tailwind) so the agent generates *components and logic*, not boilerplate — faster and far more reliable.
- **Validation gate:** generated code is typechecked/built before we claim "running." On failure the agent self-corrects once, then falls back.
- **Fallback:** a pre-generated known-good build of the requested type replays if live generation fails — the audience still sees their idea become an app.

**Reasoning for the constraint:** unbounded "build anything" live is a coin-flip; constrained-but-adaptive is impressive *and* dependable, which matches optimization priorities (impact + reliability).

---

## 9. Transport — **WebSocket (primary), HTTP (setup only)**

**Decision:** One WebSocket per session for the bidirectional event stream; plain HTTP only for health checks / static assets.

**Reasoning:** The demo *is* a stream of events (plan, tools, tokens, audio). WebSocket is the natural fit and keeps the frontend a simple event renderer. SSE was considered but WebSocket's bidirectionality (user can interrupt/steer) is worth it.

---

## 10. Tooling & Ops

| Concern | Choice | Reason |
|---------|--------|--------|
| Package mgmt (FE) | npm + Vite | standard, fast |
| Package mgmt (BE) | `uv` or `venv` + `requirements.txt` | simple, reproducible |
| Config | `.env` (backend only) | keys never reach the browser |
| Run | `uvicorn` (BE) + `vite` (FE), one script each | one-command startup for demo day |
| Formatting | Prettier + ESLint / Ruff | clean, low-friction |

**No Docker, no CI/CD, no cloud deploy for the MVP** — this runs on the presenter's laptop. Adding infra would be over-engineering against a 1-week deadline.

---

## 11. Decision Summary

| Layer | Choice | Primary fallback |
|-------|--------|------------------|
| Frontend | React + TS + Vite | — |
| Styling/Motion | Tailwind + Framer Motion | — |
| Avatar | Three.js reactive orb | static pulsing CSS orb |
| Backend | FastAPI + WebSocket | — |
| Reasoning | Claude Sonnet 5 (voice) / Opus 4.8 (builder) | cached responses |
| STT | Web Speech API | text / push-to-talk |
| TTS | ElevenLabs streaming | pre-gen clips → browser synth |
| Builder | Constrained Claude agent + templates + validation | pre-generated build |
| Transport | WebSocket | — |

See next: [Repository Structure](03-repository-structure.md).
