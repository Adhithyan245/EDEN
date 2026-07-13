# EDEN — 7-Day Development Plan

A day-by-day plan sequenced to **de-risk the demo early**: get the spine working end-to-end first (so there's always *something* to show), layer impact next, and reserve the final days for the reliability/fallback work that makes it demo-safe. Each day ends with a concrete, demoable checkpoint.

**Guiding rule:** never end a day without a working slice. Build vertically (thin end-to-end paths), not horizontally.

---

## Day 0 (setup)
**Goal: verified environment, provider abstraction, DEMO MODE, hello-world stream — none of it blocked on external keys.**
- Scaffold repo per [structure](03-repository-structure.md): FastAPI app + Vite React app.
- Implement **DEMO MODE** (`LIVE` / `SAFE` / `PRESENTATION`) in `config.py` and the **provider abstraction** (`providers/base.py` + `factory.py`) per [Demo Modes & Providers](06-demo-modes-and-providers.md).
- Concrete providers: `MockLLM` (dev/no-key), `ClaudeLLM` (activates when `ANTHROPIC_API_KEY` present), `BrowserTTS` (default), `ElevenLabsTTS` (activates when `ELEVENLABS_API_KEY` present — optional premium layer).
- **API setup verification:** `scripts/verify_setup.py` reports dependency + credential status, prints the resolved provider set per mode and setup instructions; `--live` optionally pings present providers. Never fails on a missing optional key.
- `.env.example` + `backend/README.md` with Anthropic (key **or** `ant` login) and ElevenLabs setup instructions.
- Get a WebSocket echoing a server event → rendered in the browser.
- **Checkpoint:** `verify_setup.py` runs and reports status; browser connects to backend and displays a server-sent event; EDEN runs end-to-end on mock LLM + browser TTS with **zero keys configured**.

---

## Day 1 — Conversation spine (P0: F3 + F2 text-only)
**Goal: talk to Claude and see a streamed answer.**
- Define the event protocol (`events.py` + `events.ts`) — `state`, `token`, `error`.
- Backend: Claude client (Sonnet 5), streamed response → `token` events.
- Frontend: minimal conversation panel that renders streamed tokens; text input to send a message.
- Session/conversation memory (in-process).
- **Checkpoint:** type a question → watch Claude's answer stream into the panel.

---

## Day 2 — Voice in/out (P0: F2 full + F4 basic)
**Goal: speak to EDEN and hear it reply.**
- Frontend: Web Speech API hook (`useSpeechInput`) — mic → transcript → send. Push-to-talk fallback control.
- Backend: ElevenLabs streaming TTS → `speech_chunk` events; frontend audio playback (`audio.ts`).
- Avatar orb v1 (Three.js): idle/listening/thinking/speaking states + amplitude reaction to TTS.
- **Checkpoint:** full voice loop — say something, EDEN answers aloud, orb reacts.

---

## Day 3 — HUD + Boot/Wake (P0: F1 + HUD shell)
**Goal: the cinematic front door and the premium look.**
- Glassmorphism interface shell (Tailwind): conversation panel, system status, layout.
- Boot sequence: black screen → wake-phrase detection ("Good afternoon") → boot animation (Framer Motion) → personalized greeting (pre-generate the clip via `scripts/pregenerate_clips.py`).
- Wire manual-wake fallback.
- **Checkpoint:** cold start → say "Good afternoon" → cinematic boot → "Good afternoon, Adhithyan" → HUD live. *This is the demo opening, done.*

---

## Day 4 — Agent visualization (P1: F5)
**Goal: make the thinking visible — the lecture's centerpiece.**
- Backend: convert the Claude tool-use loop in `orchestrator.py` into pipeline events (`plan_started`, `plan_step`, `tool_selected`, `tool_result`, `validation`).
- Implement 1–2 simple tools in `tools/` (e.g. lecture lookup, system status) so the loop has something real to call.
- Frontend: `AgentPipeline.tsx` — the Request→Planning→Tools→Execution→Validation→Response visualizer, lighting up from events, in sync with the spoken answer.
- **Checkpoint:** ask a question that uses a tool → watch the full reasoning pipeline animate as EDEN answers.

---

## Day 5 — Software builder (P1: F6)
**Goal: audience idea → running app.**
- Backend `builder/`: React SPA template scaffold; builder tools (`create_file`, `write_code`, `validate`, `run`) in the agent loop, using Opus 4.8.
- Whitelist + adapt logic: map an arbitrary idea onto the nearest supported type (attendance/tasks/expenses/CRUD).
- Validation gate (typecheck/build) before declaring "running"; one self-correction retry.
- Frontend `BuilderStage.tsx`: file tree + streaming code + live preview.
- Seed the pre-generated fallback build (`scripts/seed_prebuilt.sh`).
- **Checkpoint:** speak an app idea → EDEN plans, writes files live, validates, launches a working preview (with fallback if it fails).

---

## Day 6 — Lecture assistant + reliability hardening (P1: F7 + all fallbacks)
**Goal: complete the feature set and make it demo-safe.**
- Curate the lecture knowledge base (`memory/knowledge.py`) + wire F7 into the voice loop.
- Build the reliability layer end to end:
  - Cached responses for scripted moments (`cache/demo_responses.json`).
  - Pre-generate all signature audio clips.
  - Fallback ladders: STT→text, TTS→clips→synth, live-builder→prebuilt.
  - `SAFE` and `PRESENTATION` runtime modes (`config.py`).
- Error handling pass: every WebSocket/API failure degrades, never white-screens.
- **Checkpoint:** pull the wifi mid-demo → EDEN keeps going in fallback/`SAFE` mode.

---

## Day 7 — Rehearsal, polish, buffer
**Goal: a rehearsed, reliable show.**
- Full dress rehearsals of the demo script, end to end, multiple times.
- Tune: voice preset, animation timing, boot pacing, latency.
- P2 polish *only if stable*: system status panel (F8), SFX (F9).
- Prepare the physical run: which browser, mic check, network plan, `SAFE` mode as the default for the live run, `PRESENTATION` mode ready as the emergency parachute.
- Write a one-page run-of-show cheat sheet (the exact phrases to say).
- **Checkpoint:** a clean, timed, rehearsed run in `SAFE` mode with fallbacks verified.

---

## Sequencing rationale
- **Days 1–3 build the spine** (conversation → voice → boot/HUD): by mid-week there is already a genuinely impressive standalone demo (a talking, cinematic AI), so the deadline risk is capped early.
- **Days 4–5 add the lecture payload** (agent viz + builder) — the highest-impact, highest-risk features — while there's still time to adapt.
- **Days 6–7 are reliability and rehearsal**, because a demo that works once in dev but fails live is worthless. Half the remaining time is deliberately spent making it *not break*.

## Cut-scope ladder (if behind schedule)
Drop from the bottom up, protecting the spine:
1. Drop all P2 (F8–F11).
2. Simplify the builder (F6) to fewer whitelisted types or lean harder on the pre-generated build.
3. Reduce agent viz (F5) to a scripted-but-real single-tool example.
4. **Never cut** F1–F4 (wake, voice, event backbone, avatar) — that *is* EDEN.

## Daily discipline
- Start each day by confirming yesterday's checkpoint still works (guard against regressions).
- Commit at each checkpoint.
- Keep a running `SAFE`-mode path working from Day 3 onward — don't leave reliability to the end even though the dedicated hardening is Day 6.

---

*End of blueprint. Implementation begins after sign-off — starting with Day 0 setup and the Day 1 conversation spine.*
