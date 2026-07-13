# EDEN — Architecture Document

> **EDEN** — *Everything Done Effortlessly, Naturally.*
> A futuristic AI companion (JARVIS / FRIDAY / EDITH-inspired) built as a live demonstration of modern AI for a Generative AI guest lecture.

This document defines *how EDEN is put together*. It is intentionally opinionated and demo-first: every architectural choice is judged against one question — **"What creates the best live demonstration while staying reliable?"**

---

## 1. Design Principles

| # | Principle | Why it matters for the demo |
|---|-----------|------------------------------|
| 1 | **Demo impact first** | The audience must *feel* they are watching a thinking machine, not reading a chat log. |
| 2 | **Reliability over completeness** | A crash in front of 100 students is unrecoverable. Every live path has a graceful fallback. |
| 3 | **Show the reasoning** | AI agents are the lecture topic — the *process* (plan → tools → execute → validate) is the product, not just the answer. |
| 4 | **Modular & extensible** | Each capability (voice, avatar, agents, builder) is a swappable module so we can cut scope without breaking the whole. |
| 5 | **Cloud-first, fail-soft** | Online APIs give the full experience; connectivity loss degrades gracefully to cached/offline behavior instead of failing. |

---

## 2. System Overview

EDEN is a **client–server system** with a thin, cinematic browser frontend and a Python orchestration backend that streams *events* (not just text) to drive the UI.

```
┌───────────────────────────────────────────────────────────────────────┐
│                         BROWSER (React + TS)                            │
│                                                                         │
│  ┌──────────┐  ┌───────────────┐  ┌───────────────┐  ┌──────────────┐  │
│  │ Boot /   │  │  HUD Interface │  │ Agent Activity │  │  Reactive    │  │
│  │ Wake FX  │  │  (glass panels)│  │  Visualizer    │  │  AI Avatar   │  │
│  └──────────┘  └───────────────┘  └───────────────┘  └──────────────┘  │
│        ▲              ▲                    ▲                  ▲          │
│   Web Speech     Conversation        Agent event         Audio-driven   │
│   API (STT)        display            timeline           orb (Three.js) │
└────────┬───────────────────────────────────┬────────────────┬──────────┘
         │ mic text / control                 │ event stream   │ TTS audio
         │                                     │ (WebSocket)    │
         ▼                                     ▼                ▼
┌───────────────────────────────────────────────────────────────────────┐
│                       BACKEND (Python · FastAPI)                        │
│                                                                         │
│  ┌────────────────┐   ┌──────────────────┐   ┌──────────────────────┐  │
│  │  Session /      │   │  Agent Orchestr. │   │  Voice Service       │  │
│  │  WebSocket Gate │──▶│  (Claude tool    │──▶│  (ElevenLabs TTS +   │  │
│  │                 │   │   loop + events) │   │   fallback synth)    │  │
│  └────────────────┘   └────────┬─────────┘   └──────────────────────┘  │
│                                │                                        │
│                 ┌──────────────┼───────────────┐                        │
│                 ▼              ▼               ▼                         │
│         ┌────────────┐  ┌────────────┐  ┌──────────────┐                │
│         │  Tools     │  │  Memory    │  │  App Builder │                │
│         │  Registry  │  │  (session +│  │  Sandbox     │                │
│         │            │  │  lecture)  │  │  (templates) │                │
│         └────────────┘  └────────────┘  └──────────────┘                │
└────────────────────────────────┬────────────────────────────────────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    ▼                            ▼
             ┌────────────┐              ┌────────────────┐
             │ Claude API │              │  ElevenLabs API │
             │ (reasoning │              │  (TTS voice)    │
             │  + agents) │              └────────────────┘
             └────────────┘
```

**Key idea:** the backend does not return a single answer. It emits a **stream of typed events** (`plan_started`, `tool_selected`, `tool_result`, `validation`, `token`, `speech_chunk`, …) over a WebSocket. The frontend is an *event renderer* — this is what makes the agent's thinking visible and cinematic.

---

## 3. Component Responsibilities

### 3.1 Frontend (React + TypeScript)
- **Boot / Wake sequence** — black screen → cinematic power-on animation triggered by the wake phrase.
- **HUD Interface** — glassmorphism panels: conversation, system status, agent activity. Apple Vision Pro / Iron Man HUD aesthetic.
- **AI Avatar** — an abstract reactive *orb/core* (Three.js / react-three-fiber) that pulses and reacts to speech amplitude and EDEN's state (idle / listening / thinking / speaking). No photorealistic face — this is more reliable, more premium, and on-theme.
- **Agent Activity Visualizer** — a live pipeline (Request → Planning → Tool Selection → Execution → Validation → Response) that lights up from backend events.
- **Voice I/O** — Web Speech API for speech recognition (incl. wake-phrase match); plays TTS audio streamed from the backend.

### 3.2 Backend (Python · FastAPI)
- **Session / WebSocket Gateway** — one WebSocket per demo session; routes user input in, streams events out.
- **Agent Orchestrator** — runs the Claude tool-use loop; translates each step of the loop into UI events. This is the heart of EDEN.
- **Tools Registry** — declarative set of tools the agent can call (lecture lookup, app-builder actions, system info, etc.).
- **Voice Service** — turns EDEN's text into speech via ElevenLabs (streamed), with pre-generated clips for scripted lines and a browser-synth fallback.
- **Memory** — lightweight session memory (conversation) + a small curated **lecture knowledge base** for the assistant role.
- **App Builder Sandbox** — constrained, template-driven code generation + validation + run, used by the "build me an app" demo.

### 3.3 External Services
- **Claude API** — reasoning, conversation, and agentic tool use (see [Technology Decisions](02-technology-decisions.md)).
- **ElevenLabs** — cinematic text-to-speech.

---

## 4. The Event Protocol (the demo's backbone)

Every interaction is a sequence of events on the WebSocket. The frontend renders each type distinctly.

| Event | Emitted when | UI effect |
|-------|--------------|-----------|
| `state` | EDEN changes mode | Avatar shifts: idle / listening / thinking / speaking |
| `plan_started` / `plan_step` | Agent begins/updates its plan | Planning node lights up; plan steps stream in |
| `tool_selected` | Agent chooses a tool | Tool Selection node highlights the chosen tool |
| `tool_result` | A tool returns | Execution node shows result summary |
| `validation` | Agent checks its output | Validation node shows pass/retry |
| `token` | Response text streams | Conversation panel types out the answer |
| `speech_chunk` | TTS audio ready | Avatar speaks; audio plays; orb reacts to amplitude |
| `error` / `fallback` | Something failed | Silent switch to fallback path; optional subtle status |

This single protocol serves **all four demos** (conversation, agent viz, software builder, lecture assistant) — they differ only in which tools run.

---

## 5. Reliability & Fallback Architecture

Per the requirement: *online-primary, fail gracefully, no full offline build.*

| Live path | Primary | Fallback | Trigger |
|-----------|---------|----------|---------|
| Speech recognition | Web Speech API | On-screen text input / spacebar push-to-talk | API unavailable / noisy room |
| Wake trigger | Voice phrase match | Manual "wake" key / click | Recognition fails |
| Reasoning | Claude API (streamed) | Cached responses for scripted demo moments | Network / API error |
| Voice output | ElevenLabs (streamed) | Pre-generated audio clips → browser SpeechSynthesis | API error / latency |
| App builder | Live generation + validation | Pre-generated known-good project replay | Generation/validation fails |
| Whole demo | Live EDEN | **"Presentation mode"** — scripted, cached walkthrough | Total connectivity loss |

**Cached demo layer:** key scripted lines (boot greeting, canned Q&A) have pre-generated text *and* audio, so the signature moments always land even offline. A single `DEMO_MODE` flag forces the fully-cached path for a guaranteed-safe run.

---

## 6. Data & Trust Boundaries

- **No secrets in the browser.** API keys (Claude, ElevenLabs) live only in the backend `.env`. The frontend only talks to our backend.
- **Sandboxed builder.** Generated code is written to an isolated working directory, validated (typecheck/build) before any "run", and never executed with elevated privileges. Supported app types are whitelisted.
- **Ephemeral memory.** Session memory is in-process; lecture knowledge is a static curated file. No user PII is persisted.

---

## 7. Runtime Modes

| Mode | Purpose | How set |
|------|---------|---------|
| `LIVE` | Full experience, all APIs | default |
| `SAFE` | Live reasoning, but scripted builder + cached signature lines | env flag — recommended for the actual lecture |
| `PRESENTATION` | Fully cached/scripted, zero external dependency | env flag — emergency fallback |

The architecture lets you rehearse in `LIVE` and present in `SAFE`, dropping to `PRESENTATION` only if the venue network dies.

---

## 8. Why this architecture wins the demo

- **The event stream makes cognition visible** — the single most important thing for a lecture *about* AI agents.
- **The orb avatar is reliable and premium** — no uncanny-valley face, no heavy model to load, reacts live to audio.
- **Everything degrades instead of breaking** — the show goes on even when the wifi doesn't.
- **One protocol, four demos** — minimal surface area to build and test in a week.

See next: [Technology Decisions](02-technology-decisions.md).
