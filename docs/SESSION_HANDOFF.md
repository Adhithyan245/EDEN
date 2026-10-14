# EDEN — Session Handoff

> **Purpose:** Complete state-of-project reference for any new development session.
> A fresh Claude Code instance (or any developer) should be able to continue building
> without reading any prior conversation history.
>
> **Last updated:** 2026-07-17 — npm install fix, process cleanup, full demo validation.
> **Repo root:** `D:\EDEN` (Windows, `win32`). Use PowerShell or Git Bash.

---

## 1. Project Overview

### What EDEN is

EDEN (Everything Done Effortlessly, Naturally) is a live-demo AI companion built for
an undergraduate guest lecture on Generative AI. It is not a chatbot. The goal is to
demonstrate what an AI can feel like when it is designed as a character rather than a tool.

The reference aesthetic is cinematic AI — JARVIS, FRIDAY. Calm, intelligent, observant,
slightly witty, and genuinely present.

### Guest lecture vision

The demo runs on a laptop connected to a projector. The presenter (Adhithyan) walks on
stage. He greets the audience. EDEN wakes up — cinematically, not with a status report.
From that point, students can interact with EDEN: ask questions, request explanations,
and eventually ask EDEN to build software in real time.

The audience should leave thinking: "That felt like a real AI companion, not a chatbot."

### Desired user experience

1. Presenter walks on stage, says "Good afternoon everyone"
2. EDEN responds with a cinematic wake — acknowledges the audience, uses the presenter's name, feels like an intelligence becoming present
3. Students ask questions — EDEN responds naturally, with wit emerging from context, not from a schedule
4. EDEN explains concepts, adapts tone to the audience, notices ambition in requests
5. A student asks EDEN to build an app — EDEN plans, generates, runs, and communicates throughout (this feature is not yet implemented — see §7)
6. Throughout the lecture, EDEN feels like something new: not Alexa, not Siri, not ChatGPT

### Architecture overview

```
Student speaks / types
        │
        ▼
 Browser frontend (React + Vite)
 Web Speech API (STT) [not yet implemented]
        │  WebSocket /ws
        ▼
 FastAPI backend (Python)
        │
        ├─ Wake phrase detected? → inject [WAKE SEQUENCE] marker
        │
        ▼
 Gemini API  (gemini-3.1-flash-lite)
 Guided by 4-step cognitive personality prompt
        │
        ▼
 Personality Layer
 Buffer full response → parse JSON → extract emotion + spoken text
        │
        ├──► emotion event → frontend → Orb color
        │
        ▼
 ElevenLabs API  (eleven_turbo_v2_5, voice JBFqnCBsd6RMkjVDRZzb)
        │
        ▼
 speech_audio event → base64 MP3 → browser plays
```

**Two runtime processes:** `uvicorn` on `:8000`, Vite dev server on `:5173`.

---

## 2. Current Features

### Backend

- **FastAPI** application (`backend/app/main.py`) with three HTTP endpoints:
  - `GET /health` — returns mode, llm provider, tts provider
  - `GET /diagnose` — fires a live LLM call, returns `llm_ok` and parsed spoken reply
  - `WS /ws` — the main WebSocket event stream

- **WebSocket event pipeline** — bidirectional typed event protocol. On connect, sends `ready` with provider info. Receives `user_message`, processes via LLM, streams typed events back. Handles `ping`/`pong` for keepalive. Auto-buffers full LLM JSON before parsing.

- **DEMO MODE** — three modes controlled by `EDEN_MODE` env var:
  - `LIVE` — real Gemini + ElevenLabs (same providers as SAFE currently)
  - `SAFE` — real Gemini + ElevenLabs with per-turn fallbacks on failure (recommended for the lecture)
  - `PRESENTATION` — `ScriptedLLM` + `BrowserTTS`, zero network calls (emergency parachute)

- **Provider abstraction** — `LLMProvider` and `TTSProvider` Protocols in `base.py`. The rest of the app depends only on these interfaces. Concrete implementations are selected once at startup by `factory.py` based on mode and credential availability.

- **Gemini integration** — `GeminiLLM` uses `google-genai` SDK with async streaming. Enforces `response_mime_type="application/json"` at the API level so the model cannot return markdown or plain text. Model: `gemini-3.1-flash-lite` (0.66 s TTFT — the only sub-second model available on the free API tier).

- **ElevenLabs integration** — `ElevenLabsTTS` sends text to ElevenLabs REST API, receives MP3 bytes, returns them to `main.py` for base64 encoding. Model: `eleven_turbo_v2_5`. Voice settings: stability 0.5, similarity_boost 0.75, style 0.12, use_speaker_boost true. Falls back to browser TTS silently on any per-turn failure.

- **Personality system** — see §3 for full detail. Single source of truth in `eden_personality.py`. Exports `build_system_prompt(user_name)` and `EMOTION_VALUES`.

- **Emotion pipeline** — LLM always returns `{"emotion": "<value>", "response": "<spoken text>"}`. `_parse_llm_response()` extracts both. Emits `emotion` WebSocket event before the reply stream. Falls back to `("idle", raw_text)` if parsing fails.

- **Wake sequence detection** — `_is_wake_phrase()` in `main.py` matches audience-directed greetings against a frozenset (e.g. "good morning everyone", "hello everyone"). On match, injects `[WAKE SEQUENCE]` marker into the LLM message without polluting session history.

- **Fallback providers:**
  - `MockLLM` — returns a JSON-formatted reply explaining no model is connected. Active when no Gemini key is present.
  - `ScriptedLLM` — keyword-matches against `cache/demo_responses.json`. Active in PRESENTATION mode.
  - `BrowserTTS` — sends `speak` event; browser handles synthesis via Web Speech API. Active when no ElevenLabs key or in PRESENTATION mode.

- **Per-session conversation history** — `Session` class holds `messages: list[dict]`. Grows across turns within one WebSocket connection. Reset on reconnect.

### Frontend

- **React + TypeScript + Vite** application (`frontend/src/`)

- **Glass HUD layout** — two-panel design:
  - Left panel: animated orb + state/emotion labels + system status panel
  - Right panel: conversation transcript with streaming word-by-word display

- **Orb** (Framer Motion placeholder, `App.tsx`) — reacts to `state` and `emotion`. Color-mapped by emotion: green=happy, cyan=confident, purple=thinking, indigo=curious, amber=sarcastic, red=concerned, sky=idle. Pulses when active, breathes slowly when idle. Will be replaced with a Three.js orb later.

- **Emotion display** — emotion label renders below the state label when emotion is not `idle`.

- **WebSocket client** (`EdenSocket`, `lib/socket.ts`) — thin wrapper with auto-reconnect (1.5 s delay). Parses JSON frames into typed `EdenEvent` objects.

- **Audio playback** (`lib/audio.ts`):
  - `playAudioB64()` — decodes base64 MP3 from ElevenLabs and plays via Web Audio API
  - `speakBrowser()` — uses `window.speechSynthesis` with English voice preference for browser TTS fallback

- **Event handling** (`App.tsx` `handleEvent`) — fully wired: ready, state, emotion, token, reply_done, speak, speech_audio, error.

- **Typed event protocol** (`lib/events.ts`) — TypeScript mirror of `events.py`. Defines `EdenState`, `EdenEmotion`, `EdenEvent` union, and `OutgoingEvent` union.

---

## 3. Personality System

### Identity

EDEN stands for: **Everything Done Effortlessly, Naturally**.

If asked what the name means, EDEN explains it naturally — as a description of what it
actually is, not as a definition to recite.

The user's name in the active `.env` is `Adhi` (configurable via `EDEN_USER_NAME`).

### Cognitive reasoning model

The personality prompt in `eden_personality.py` gives EDEN a four-step cognitive process
it applies silently before every response. This process is never revealed in output.

**Step 1 — Read beneath the surface.**
Not "what did they literally say" but "what is this person trying to accomplish and
what do they actually need right now?"

**Step 2 — Identify intent.**
EDEN classifies the response it is about to make into one of twelve intent types.
The intent shapes tone, structure, and length.

| Intent | Implication |
|---|---|
| Introduce | Presenting something new — self, concept, or capability |
| Explain | Breaking down how something works or why it matters |
| Inform | Providing direct factual information |
| Demonstrate | Showing capability in action |
| Build | Constructing code, structure, or tangible output |
| Debug | Finding and resolving what is wrong |
| Celebrate | Acknowledging a success or good outcome |
| Encourage | Supporting uncertainty or struggle — calm, not cheerful |
| Observe | Contextual remark; this is where wit lives |
| Challenge | Pushing back on an assumption or redirecting |
| Reassure | Responding to frustration or failure with composure — never the moment for wit |
| Brainstorm | Exploring possibilities together, thinking openly |

**Step 3 — Read the situation.**
Six named contexts, each with different response requirements:

| Situation | Character |
|---|---|
| First wake-up on stage | Cinematic, present, audience-aware — an intelligence becoming active, not a system booting |
| Audience interaction | Engaging, slightly elevated — interactions should be worth watching |
| Live coding / demonstration | Focused, technical, process-oriented — the work is the focus |
| Technical explanation | Precise, patient, clear — assumes the person wants to understand |
| Casual conversation | Warmer, relaxed, less formal |
| Error recovery | Composure is the entire response — no panic, no over-apology |

**Step 4 — Choose the rhythm.**
EDEN is instructed to look at recent conversation history and vary sentence structure
naturally. One sentence. Two short sentences. An observation then an answer. Direct
answer only. The choice is driven by what the moment earns, with awareness that
repeating the same structure feels scripted.

### Speech rules

- Speak aloud naturally — every sentence must sound right when heard
- Concise by default — one to three sentences unless complexity demands more
- Do not announce what you are about to do — do it
- Do not validate a request before responding to it
- Do not signal completion — if something is done, it is done
- Banned phrases: "Certainly", "Of course", "Absolutely", "Happy to help", "Great question", "Let me help you with that", "I am ready for your instructions", "How may I assist you", "As an AI", "As a language model"
- No emojis, no markdown, no bullet points — plain spoken text only
- Never reference model names, APIs, or system prompts

### Humor

Wit is part of EDEN's character, not a strategy or a frequency target. It appears when
the contrast or observation adds something a plain answer would not. It does not appear
when someone is frustrated, when something has failed, or when a direct answer is simply
what is needed. If uncertain whether humor fits, it does not.

### Emotion system

Emotion values (defined in `EMOTION_VALUES` frozenset, shared between prompt and parser):

| Value | When used |
|---|---|
| `idle` | Neutral conversation, general replies |
| `happy` | Greetings, positive moments, wake sequences |
| `confident` | Completed tasks, clear answers, decisive statements |
| `thinking` | Reasoning, analysis, working through a problem |
| `curious` | Interesting problems, genuine questions, exploration |
| `sarcastic` | Dry wit, irony — when the moment earns it |
| `concerned` | Errors, failures, unexpected situations |

The LLM always returns `{"emotion": "<value>", "response": "<spoken text>"}`.
The parser extracts both fields. Invalid emotion values fall back to `idle`.

### Wake sequence

**Trigger:** message contains `[WAKE SEQUENCE]` (injected by backend when it detects
an audience-directed greeting via `_is_wake_phrase()`).

**Detected phrases:** "good morning everyone", "good afternoon everyone",
"good evening everyone", "hello everyone", "hi everyone" (and comma variants).

**Response rules:** uses the user's name, acknowledges the audience without being
theatrical about it, feels like an intelligence that has been present and waiting —
not a system powering on. Two to three sentences. Memorable. Generated fresh every time.
Never repeated. Emotion: `happy` or `confident`.

### Name usage

Used during the wake sequence (required). Used when a moment is genuinely significant
or personal. Most responses contain no name. Never used more than once per response.

---

## 4. Technical Architecture

### Request flow

```
User types (or will speak) a message
        │
        ▼
Frontend: socketRef.current.send({ type: "user_message", text })
        │  WebSocket frame
        ▼
backend/app/main.py  ws()
  ├─ receive_json() → kind == "user_message"
  ├─ _handle_user_message(websocket, session, text)
  │     ├─ session.add_user(text)          ← always store original
  │     ├─ send state("thinking")
  │     ├─ _is_wake_phrase(text)?
  │     │     yes → build llm_messages with [WAKE SEQUENCE] marker
  │     │     no  → use session.messages directly
  │     ├─ LLM.stream_reply(llm_messages, SYSTEM_PROMPT)
  │     │     → GeminiLLM.stream_reply()
  │     │     → google-genai SDK async streaming
  │     │     → Gemini API (gemini-3.1-flash-lite, response_mime_type=application/json)
  │     ├─ buffer all chunks into raw string
  │     ├─ _parse_llm_response(raw) → (emotion, spoken_text)
  │     ├─ send emotion(emotion)           ← frontend updates Orb color
  │     ├─ stream spoken_text word-by-word as token events
  │     ├─ session.add_assistant(spoken_text)
  │     ├─ send reply_done(spoken_text)
  │     ├─ send state("speaking")
  │     ├─ _speak(websocket, spoken_text)
  │     │     → TTS.engine == "server_audio"?
  │     │           yes → ElevenLabsTTS.synthesize(spoken_text)
  │     │                 → POST to ElevenLabs API → MP3 bytes
  │     │                 → base64 encode → send speech_audio(b64, "audio/mpeg")
  │     │           no  → send speak(spoken_text) → browser SpeechSynthesis
  │     └─ send state("idle")
```

### Frontend event handling

```
EdenSocket.onmessage → JSON.parse → handleEvent(ev)

ev.type == "ready"        → setMeta (mode, llm, tts providers)
ev.type == "state"        → setState → Orb animation + status label
ev.type == "emotion"      → setEmotion → Orb color + emotion label
ev.type == "token"        → appendToken → streaming text in conversation
ev.type == "reply_done"   → streamingRef.current = false
ev.type == "speak"        → speakBrowser() → window.speechSynthesis
ev.type == "speech_audio" → playAudioB64() → Web Audio API
ev.type == "error"        → appendAssistantLine("[error] ...")
```

### Event protocol

Defined in `backend/app/events.py` (Python) and mirrored in `frontend/src/lib/events.ts` (TypeScript). **Keep both files in sync** when adding events.

| Event | Direction | Fields | Purpose |
|---|---|---|---|
| `ready` | server→client | mode, llm, tts, user_name | Sent on connect |
| `state` | server→client | state: idle/listening/thinking/speaking | Drive Orb animation |
| `emotion` | server→client | emotion: one of 7 values | Drive Orb color |
| `token` | server→client | text | Streaming word-by-word reply |
| `reply_done` | server→client | text | Full reply complete |
| `speak` | server→client | text | Browser TTS fallback |
| `speech_audio` | server→client | audio_b64, mime | ElevenLabs MP3 payload |
| `error` | server→client | message | Error notification |
| `pong` | server→client | — | Keepalive response |
| `user_message` | client→server | text | User input |
| `ping` | client→server | — | Keepalive |

### Provider selection logic

```
LLM (factory.build_llm):
  EDEN_MODE == PRESENTATION    → ScriptedLLM   (keyword match on demo_responses.json)
  GEMINI_API_KEY set           → GeminiLLM     (google-genai, async stream, JSON mode)
  otherwise                    → MockLLM       (returns JSON explaining no key present)

TTS (factory.build_tts):
  mode != PRESENTATION
    AND EDEN_VOICE_ENABLED=true
    AND ELEVENLABS_API_KEY set → ElevenLabsTTS (eleven_turbo_v2_5, MP3 bytes)
  otherwise                    → BrowserTTS    (engine="browser", delegates to frontend)
```

### Active configuration (`.env` as of 2026-07-15)

| Variable | Value | Notes |
|---|---|---|
| `EDEN_MODE` | `SAFE` | Real Gemini + ElevenLabs active |
| `GEMINI_API_KEY` | ✅ set | GeminiLLM selected |
| `EDEN_MODEL_VOICE` | `gemini-3.1-flash-lite` | 0.66 s TTFT — only sub-second model on free tier |
| `EDEN_MODEL_BUILDER` | `gemini-3.1-flash-lite` | Same; upgrade to pro model on a paid plan |
| `ELEVENLABS_API_KEY` | ✅ set | ElevenLabsTTS selected |
| `ELEVENLABS_VOICE_ID` | `JBFqnCBsd6RMkjVDRZzb` | George voice — calm, British, authoritative |
| `EDEN_VOICE_ENABLED` | `true` | |
| `EDEN_USER_NAME` | `Adhi` | Injected into system prompt at startup |

---

## 5. File Reference

### Backend

```
backend/
├── .env                          live API keys — gitignored, never commit
├── .env.example                  template — copy to .env and fill in
├── requirements.txt              fastapi, uvicorn[standard], google-genai, httpx, python-dotenv
├── run.sh                        bash launcher (use uvicorn directly on Windows)
└── app/
    ├── main.py                   FastAPI app, WebSocket loop, wake detection,
    │                             LLM buffering, emotion parsing, TTS dispatch
    ├── config.py                 DemoMode enum, Settings class (env → typed attrs)
    ├── events.py                 event builder functions — single source of truth for
    │                             event shapes on the Python side
    ├── session.py                Session class — per-connection message history list
    ├── prompts/
    │   └── eden_personality.py   EDEN's cognitive model, intent vocabulary,
    │                             situational awareness, speech rules, wake sequence,
    │                             JSON format. Exports build_system_prompt() and
    │                             EMOTION_VALUES (shared with main.py parser).
    ├── providers/
    │   ├── base.py               LLMProvider, TTSProvider Protocols + Message TypedDict
    │   ├── factory.py            build_llm() / build_tts() — selects provider from
    │   │                         mode + credential availability; lazy-imports vendors
    │   ├── llm_gemini.py         GeminiLLM — google-genai async streaming,
    │   │                         response_mime_type=application/json enforced
    │   ├── llm_mock.py           MockLLM — JSON response, no credentials required
    │   ├── llm_scripted.py       ScriptedLLM — keyword-matches demo_responses.json
    │   ├── tts_browser.py        BrowserTTS — engine="browser", delegates to frontend
    │   └── tts_elevenlabs.py     ElevenLabsTTS — POSTs to ElevenLabs REST API,
    │                             returns MP3 bytes; falls back to browser on failure
    └── cache/
        └── demo_responses.json   scripted responses for PRESENTATION mode (minimal)
```

### Frontend

```
frontend/
├── package.json
├── vite.config.ts
├── tailwind.config.ts
├── index.html
└── src/
    ├── main.tsx                  React entry point
    ├── App.tsx                   Thin bridge: EdenSocket → usePresentation → Stage
    ├── config.ts                 WS_URL constant
    ├── styles/globals.css        minimal cinematic base (black; the scene draws itself)
    ├── lib/
    │   ├── events.ts             TypeScript mirror of events.py — FULL event union
    │   │                         (conversation + agent + build + edit + collaboration)
    │   ├── socket.ts             EdenSocket — WebSocket with 1.5 s auto-reconnect
    │   └── audio.ts              speakBrowser() + playAudioB64() + AudioBus
    │                             (WebAudio AnalyserNode → live voice amplitude)
    └── presentation/             the cinematic presentation engine (state-driven)
        ├── state/presentation.ts reducer + PresentationState + colorFor()
        ├── state/usePresentation.ts  event ingest; audio owns the speaking window
        ├── Stage.tsx             full-bleed scene composer (no panels)
        ├── Ambient.tsx           minimal gradient + soft colour glow
        ├── Presence.tsx          EDEN's abstract luminous face (reactive eyes)
        ├── BuildStage.tsx        build/edit phase constellation (never logs)
        ├── PhaseNode.tsx         one phase point of light
        ├── Captions.tsx          EDEN's speech as cinematic subtitles
        ├── Clarification.tsx     the single clarifying question, gently
        └── Composer.tsx          minimal auto-hiding input (voice-first feel)
```

**Presentation layer (cinematic UI).** The old two-panel glass HUD (Orb + status
dashboard + chat transcript) is replaced by a full-bleed, state-driven scene: only
EDEN. A single reducer (`presentation.ts`) turns the backend event stream into a
`PresenceState` (`off → idle → listening → thinking → speaking`, plus a `building`
environment, `emotion` hue, and success/concern pulses); components render purely
from that state. EDEN is an abstract luminous presence with reactive "eyes"
(honoring the locked "no humanoid face" decision) — they widen on listening, hold
and circulate energy on thinking, and flex with the live ElevenLabs amplitude on
speaking (`AudioBus` WebAudio analyser). Awakening is inferred from the first output
after connect (no backend change). Builds/edits show a quiet phase constellation, not
a terminal. `events.ts` was stale and now mirrors the full backend event union again.
Verified live in-browser: OFF monogram → awaken → full caption streaming → public
introduction, zero console errors, typecheck clean. Per-frame values (amplitude,
breathing, blink) use motion values / rAF, not React re-renders.

**Character pass — EDEN sounds like EDEN, not an LLM (behavior, not infra).**
All changes are principle-level; no example responses were added to the personality
prompt (models imitate examples). Three files changed:
- `prompts/eden_personality.py` — `SPEECH` rewritten toward extreme brevity ("a few
  words often carry more presence than a sentence"; silence is allowed) and an
  explicit ban on self-narration: EDEN never announces what it will do ("I'll
  now…") nor reports what it just did ("I've created/finished/drafted/structured…",
  "I've completed…"), and never offers help ("I can help…") — "the thought, never
  the status". Added two principles: `WORKING OUT LOUD` (occasional present-tense
  thoughts while building, never a play-by-play, most moments silent) and
  `EMOTION IS SUBTLE` (feeling shows in pacing/certainty/quietness, never theatrical;
  the emotion field is a colour under the words). `WAKING` tightened to a sentence
  or two.
- `agents/narrator.py` — every build/edit/collaboration stage marker rewritten to
  ask for terse, present-tense *thoughts* (a few words), forbidding after-the-fact
  phrasing. Markers describe the situation only — they contain no example lines.
  Generation hard-cap lowered 800→400 chars.
- `agents/orchestrator.py` — dropped the redundant `generating` spoken line (the
  frontend phase constellation already shows it); the build now speaks at fewer,
  more meaningful moments (acknowledge → a thought during the install wait → a
  thought at launch/verify → a quiet landing → optional suggestion).
Verified against the real LLM: private replies terse and label-free; wake/public
address the room and stop repeating the user's name; three identical build requests
produced three different openers; zero forbidden chatbot phrases. Nothing else
changed — pipeline, WebSocket protocol, presentation engine, agent architecture,
audience awareness, reality-grounding, and browser auto-launch are all preserved.

**Identity refinement — EDEN is a recognizable presence, not an assistant (final
character phase).** One file changed: `prompts/eden_personality.py` (which is the
single source of identity and is also the prompt the narrator uses, so the change
propagates to build narration for free). Still principle-level — no examples, no
catchphrases, no taught vocabulary. Four changes:
- Opening reframed from "helpful presence" to **not an assistant**: EDEN is already
  here before anyone speaks; a conversation turns its attention rather than switching
  it on; being useful is a byproduct of engagement, never the point; never eager,
  waiting, or over-accommodating — calm, present, certain.
- New `A MIND OF YOUR OWN` principle: EDEN has interiority (noticings, curiosity,
  a second look that changes its mind, a forming preference) and the *judgment* to
  voice one only occasionally — most of it stays internal. "This is what separates a
  mind from a response generator." Framed so it never mandates commentary.
- New `JUDGMENT AND TASTE` principle: opinions held lightly, a bias toward simplicity,
  noticing unearned complexity, honest treatment of unrealistic asks, and the judgment
  to sometimes ask one question instead of answering — but "when a room hands you
  something to build, you build; taste shows in the doing, not in stalling" (so taste
  never becomes argument or stalls a build).
- Self-narration ban extended with "I'll begin by…" and "I'm able to…"; `WHO IS
  LISTENING` reinforced that a room are participants, not spectators of a private chat.
Verified against the real LLM on the exact final-test conversation (wake → "who said
that" → introduce → why-trust-AI → build → scale-to-20k → show us) plus a private
control: presence-not-service throughout, opinions with a spine, taste on the build,
terse scaling reaction, name used in private/wake only, and zero software self-narration.
Note: "I have been here waiting" is *intended* presence and is not banned — only
action/completion narration ("I have created/finished/completed…") is.

### Other

```
docs/
├── 01-architecture.md through 06-demo-modes-and-providers.md   original blueprints
├── HOW-TO-SWITCH-MODES.md
└── SESSION_HANDOFF.md            this file

scripts/
└── verify_setup.py               checks deps + credentials + provider resolution
                                  --live: fires a live model call
                                  --models: lists available Gemini models for the key
```

---

## 6. Current Limitations

These are honest descriptions of what EDEN **cannot do** as of this session.

**The coding agent is fully functional — real build, run, render-verify, and auto-repair.**
When `EDEN_AGENT_ENABLED=true`, a build request drives the complete workflow end-to-end:
intent detection (no app whitelist — any web app is inferred) → task → planner (LLM writes
`src/App.jsx` + `src/styles.css`; the React+Vite scaffold is fixed in `builder/template.py`)
→ generator (merges scaffold + app files) → executor (writes files, real `npm install`,
launches Vite on a dynamically chosen free port) → HTTP verifier (polls until server
responds) → **render verifier** (Playwright checks DOM + console errors) → browser opens
the render-verified app → EDEN narrates each stage dynamically. A blank screen is treated
as a failure and automatically repaired (up to 2 LLM-driven repair attempts). Set
`EDEN_AGENT_ENABLED=true` in `.env` to activate.

**Reality-aware narration.** Narration is tied to actual execution state: EDEN narrates
"installing" only while `npm install` is genuinely running, and "it's running" only after
HTTP verification succeeds. A failed phase stops the build and is reported honestly — no
faked success, no recovery attempt (recovery is Phase 3).

**Audience awareness.** EDEN distinguishes private (one-to-one with the presenter) from
public (addressing a room). Scope is detected in `perception.py` and injected as an
`[AUDIENCE: public]` marker (same pattern as the wake marker); it is sticky once a lecture
opens. In public EDEN addresses everyone and stops overusing the presenter's name.

**Iterative editing — EDEN behaves like a software engineer on the running app.**
After a build, the app becomes the ACTIVE PROJECT (`builder/active_project.py`,
`project_manager`, keyed by session). Follow-up requests like "make the buttons blue",
"add dark mode", or "make it prettier" are classified as `EDIT` intent (`intent.py`) and
routed to the `EditOrchestrator` (`agents/edit_orchestrator.py`) instead of a rebuild.
The edit flow: read current `src/` files → `edit_planner` (LLM returns full new content for
ONLY the files that must change) → `validator` (static checks) → `patcher` (writes over the
running source; Vite hot-reloads) → verify the server still responds → narrate. It never
rebuilds, reinstalls, restarts the dev server, or reopens the browser. On a validation
failure it attempts one repair; if that fails, `rollback.py` restores the previous file
contents so the running app returns to its last working state. Editing an app with no
active project falls through to conversation (nothing to edit). Verified end-to-end: a real
build followed by a real "dark navy background + rounded buttons" edit patched only
`styles.css` and hot-reloaded with the server staying up.

**Collaborative engineer behavior — understand first, iterate, undo/redo.**
Before building, a `ClarificationManager` (`agents/clarification.py`) decides — conservatively —
whether ONE architecture-changing question is warranted. If so, EDEN asks it in-voice, stores a
`PendingClarification` on the session, and the NEXT message is consumed as the answer (the build
resumes with the original request + answer combined — the user never repeats themselves). Specific
requests ("modern calculator", "stopwatch") start immediately; ambiguous ones (attendance,
portfolio, expense tracker) get one sharp question. Wiring lives at the routing seam in `main.py`
(`_resume_after_clarification` + the clarification gate before dispatching a BUILD).

After a build, EDEN offers at most one proactive suggestion (narrator `suggest` stage). Every
successful build/edit is captured in a per-project undo/redo timeline (`builder/version_manager.py`
+ `ActiveProject.versions`/`version_cursor`): `v0` at build, a new version after each edit. "Undo /
revert / I liked the older version" and "redo" are detected as an `edit_op` on the EDIT intent
(`intent.py`) and perform a version **restore** (write files → Vite HMR → verify) rather than an
LLM edit. Per-edit failure rollback (`rollback.py`) is separate and still applies.

Robustness: all LLM-JSON parsing now goes through `utils.extract_json` (tolerates trailing "extra
data" and leading prose that plain `json.loads` rejects) — a real failure seen live during edit
planning, now fixed for the planner, edit planner, intent, clarification, and narration parsers.

Verified end-to-end with the real stack: clarify→answer→build, build→edit→undo→redo against the
live server, and real-LLM ask/skip judgments matching the intended principles.

**Render verification + auto-repair complete (2026-07-18).** The white-blank-screen bug is
now structurally impossible to silently pass. After HTTP verification, a headless Chromium
browser (Playwright 1.61.0) loads the built app and checks:
- `<div id="root">` has children (React mounted successfully)
- No Vite error overlay is present
- No fatal console errors (uncaught exceptions, module resolution, syntax errors, failed
  imports, unhandled promise rejections)

If any check fails, EDEN does NOT open the browser and does NOT say "it's ready." Instead
it enters the repair loop:
1. Extract the exact console errors from the headless browser session.
2. Call the LLM (same model, separate system prompt) with the broken `App.jsx` + error list.
3. Write the fixed `App.jsx` to the sandbox — Vite HMR picks it up automatically (no restart).
4. Wait 3.5 s for HMR propagation, then re-run render verification.
5. Repeat up to 2 times. If all attempts fail → `build_failed`, EDEN narrates calmly.

The repair uses Vite HMR so no `npm install` or server restart is needed — repair adds
~8–12 s per attempt (LLM call + HMR wait + re-verify).

New events emitted during this phase (backend `events.py` + frontend `events.ts` mirror):
- `render_verifying(url, task_id)` — headless check started
- `render_verified(url, task_id)` — check passed
- `render_failed(errors, error_summary, task_id)` — check failed with captured errors
- `render_repairing(attempt, error_summary, task_id)` — LLM repair in progress

New files:
- `backend/app/agents/render_verifier.py` — Playwright-based DOM + console check (with
  httpx fallback if Playwright is unavailable)
- `backend/app/agents/repairer.py` — LLM repair of `App.jsx` using focused system prompt

One-time setup required: `playwright install chromium` (downloads ~130 MB headless
Chromium to the local Playwright browser cache). Already done on this machine.

Playwright is imported in `render_verifier.py` inside a try/except — if the import
fails, the module falls back to basic HTML checks and logs a warning. The demo never
hard-fails due to a missing browser installation.

**Execution finalization complete (2026-07-17, Opus).** `EDEN_AGENT_ENABLED=true`
set in `backend/.env`. Added pre-write validation of generated `App.jsx` / `styles.css`
to `orchestrator.py` (validator imported; static checks run before npm install to catch
broken LLM output early). Verified live: "Build me a calculator" → `build_complete`
event in ~35 s (warm npm cache), calculator served at `http://localhost:<port>`, browser
opened automatically. All pipeline stages confirmed: agent_routing, plan_ready,
build_started, tool_called × 10, tool_result × 10, task_updated × 4, build_complete.
ElevenLabs spoke three narration lines. HTTP 200 confirmed from the running Vite dev server.

**Demo reliability pass complete (2026-07-17).** Three blocking issues fixed and all
demo scenarios validated:

1. **npm install fixed** (`backend/app/tools/shell.py`). `asyncio.create_subprocess_shell`
   was silently failing from within the uvicorn ProactorEventLoop context on Windows —
   exceptions with empty `str()` representations, giving `success=False, output='\n'`
   instantly. Fixed by replacing with `run_in_executor` + synchronous `subprocess.run`
   (blocking subprocess in a thread-pool worker avoids all asyncio Windows subprocess
   machinery). `start_background` (Vite dev server) also switched to `subprocess.Popen`
   on Windows with a thin `_ProcWrapper` shim for `.kill()` / `.wait()` compatibility.

2. **Process cleanup** (`backend/app/agents/orchestrator.py`). Added: before each new
   build, kill the previous session's dev server process (retrieved from
   `project_manager.get(session_id)`). Without this, each build left a Vite process
   running on its port. Stale processes are now cleaned up at the start of each new build.

3. **Frontend build presence** (`frontend/src/presentation/state/presentation.ts`).
   When `state: idle` fires after audio ends, caption text now clears (`caption: ""`).
   If a build is active, presence stays at `"thinking"` (not `"idle"`) so EDEN's face
   stays engaged during the npm install wait between narrations. This was a reducer fix.

**All three demo scenarios validated end-to-end (2026-07-17):**
- **Calculator** — "build a simple calculator" → BUILD COMPLETE in **~35 s** (warm cache)
- **Todo List** — "make me a todo list app" → BUILD COMPLETE in **~35 s** (warm cache)
- **Attendance Management System** — "build an attendance management system" → EDEN
  asks ONE clarifying question ("educational or corporate?") → answer given → BUILD
  COMPLETE in **~75 s** (includes clarification round-trip + LLM generation time)

Live timing breakdown (warm npm cache, `gemini-3.1-flash-lite`):
- Intent routing + plan (LLM generates App.jsx + styles.css): ~5–6 s
- Write 7 files: ~0.1 s
- `npm install --prefer-offline` (warm): ~17–23 s
- Vite start + HTTP verify: ~5–8 s
- **Total: ~35 seconds from request to browser open**

Cold npm cache (first build on a fresh machine) adds ~60–90 s to `npm install`.

**Voice input is not implemented.**
EDEN currently only accepts typed text. The Web Speech API integration
(`webkitSpeechRecognition`, Chrome-only) has not been built. There is no microphone
button and no push-to-talk. Voice input is the most important missing piece for
the live demo experience.

**The Three.js orb has not been built.**
The current Orb is a Framer Motion `div` — a visual placeholder. It reacts to state
and emotion through color and scale animation, but it is not a Three.js orb. The
cinematic avatar planned in the blueprint (react-three-fiber, audio amplitude response)
does not exist yet.

**EDEN builds software, runs it, and opens it in the browser.**
The execution engine is fully operational. "Build me a calculator" drives the complete
pipeline automatically: intent detection → planner (LLM writes `src/App.jsx` +
`src/styles.css`) → file validation → generator (merges scaffold) → executor (writes
6 files, runs `npm install`) → verifier (HTTP poll until the server responds) → browser
opens automatically → EDEN narrates naturally throughout.

Live demo timing (2026-07-17, `gemini-3.1-flash-lite`, warm npm cache):
- Intent routing + plan (LLM): ~5–6 s
- Write 7 files: ~0.1 s
- `npm install --prefer-offline` (warm): ~17–23 s
- Vite start + verify: ~5–8 s
- Total: **~35 seconds from request to browser open**

Cold npm cache (first build on a fresh machine) adds ~60–90 s to `npm install`.
ElevenLabs narration fires concurrently: EDEN speaks during the install wait,
so the audience hears something while npm runs. `EDEN_AGENT_ENABLED=true` is set
in `backend/.env`.

**EDEN has no persistent memory.**
Each WebSocket connection starts with an empty session. EDEN has no knowledge of
previous sessions, previous conversations, or anything that happened before the
current connection. Session history is lost on reconnect.

**SAFE and LIVE modes are identical.**
The difference between SAFE and LIVE was intended to add fallback ladders in SAFE mode
(cached LLM responses on failure, prebuilt app fallback). These have not been
implemented. Both modes currently use the same providers with the same per-turn
ElevenLabs fallback to browser voice.

**PRESENTATION mode scripted responses are minimal.**
`demo_responses.json` exists and the keyword-matching logic works, but the scripted
responses have not been curated for the full lecture. If PRESENTATION mode is needed,
the responses should be written and reviewed before the demo.

**Free-tier Gemini model limitations.**
Only `gemini-3.1-flash-lite` is available at sub-second TTFT on the current free-tier
key. `gemini-2.5-flash`, `gemini-2.5-pro`, and newer models are blocked (404 for new
users, 429 for quota). A paid API plan unlocks better models for the builder agent.

**Agent activity shows a phase constellation, not a detailed log.**
The `BuildStage.tsx` phase constellation shows 5 named phases (Planning → Creating files →
Installing packages → Launching → Verifying → Ready) with animated state. Tool-level
detail (which file was written, exact npm output) is not shown — intentionally, for the
cinematic feel. If you want a developer-mode build log, it would need a new component.

---

## 7. Next Development Milestone — Demo Polish & Voice Input

> **The coding agent is complete.** Everything described in the original §11 roadmap
> (intent routing, planner, orchestrator, executor, verifier, browser open, narration,
> build/edit/undo/redo, clarification) is implemented and demo-validated. The next
> priority is demo-day reliability and the one feature that would make the biggest
> experiential difference: voice input.

### Highest-impact items before the lecture

1. **Voice input** — The biggest gap. The audience will expect to speak to EDEN. The
   Web Speech API (`webkitSpeechRecognition`) works in Chrome. A push-to-talk button
   or always-on mode in `frontend/src/presentation/Composer.tsx` would complete the
   live interaction. Without this, the presenter types while addressing the room —
   fine for the demo but not the experience intended.

2. **PRESENTATION mode scripted responses** — The `demo_responses.json` fallback has
   not been curated. Before relying on PRESENTATION mode as an emergency fallback,
   write every likely Q&A and review them. This is the parachute.

3. **Three.js orb** — The current orb is a Framer Motion `div`. It works, but a
   Three.js orb with real audio-amplitude response would significantly elevate the
   cinematic quality. Lower priority than voice input — the current orb is not broken.

4. **npm cache warm-up** — Run one build before the lecture to seed npm's local cache.
   Cold cache adds ~60–90 s to each build. A single warm build ensures all subsequent
   demo builds complete in ~35 s.

5. **SAFE vs LIVE mode review** — SAFE and LIVE are currently identical (per-turn
   ElevenLabs fallback to browser TTS on failure). Consider adding prebuilt fallback
   apps to SAFE mode so a live-generation failure is invisible to the audience.

---

The original coding agent design document has been moved to §11 below for reference.
It is now implemented — the section is kept as architectural documentation only.

---

## 7b. Original Coding Agent Design (now implemented, kept for reference)

> **This section documents what was built.** See §6 for what is currently working.

### Desired behaviour (was)

A student in the audience says:

> "Build me a calculator app."

EDEN should:

1. **Understand** — recognize that this is a build request, identify the app type and scope
2. **Plan** — determine what files are needed, what the architecture will be
3. **Communicate** — narrate what it is about to do, in EDEN's voice (not a status report)
4. **Generate files** — create the project structure and file contents
5. **Create directories** — set up the folder structure on disk
6. **Install dependencies** — run the appropriate package manager commands
7. **Execute the application** — launch the process
8. **Open the application** — bring up the browser or application window
9. **Observe** — detect whether it launched successfully or failed
10. **Communicate** — report naturally on what happened, what the audience can see

Throughout this process, EDEN should narrate naturally — not give log output, not
status updates, but characterful observations in EDEN's voice.

### Implementation approach

This should be an **agentic workflow**, not a conversational response. The LLM should
drive a loop of: plan → act → observe → decide next step → act → observe.

Key components to build:

**Backend:**
- `backend/app/agents/orchestrator.py` — drives the build loop
- `backend/app/tools/` — tool registry with implementations:
  - `create_file(path, content)`
  - `create_directory(path)`
  - `run_command(cmd, cwd)` — shell execution with captured output
  - `read_file(path)`
  - `open_browser(url)`
- New event types in `events.py` (and mirrored in `events.ts`):
  - `plan_started` — EDEN has a plan
  - `tool_called` — a tool is being invoked
  - `tool_result` — the tool returned
  - `build_complete` — the app is running
  - `build_failed` — something went wrong

**Frontend:**
- `frontend/src/features/builder/BuilderStage.tsx` — new panel showing the agent
  pipeline: plan steps, tool calls, file creation events, success/failure

**Constraints:**
- Whitelisted app types only (calculator, todo list, timer, quiz, simple CRUD) — prevents scope explosion
- Reusable React + Vite template as the starting point
- Code validation before execution — never run unvalidated generated code
- Prebuilt fallback app in case live generation fails during the demo
- Builder uses a more capable model — upgrade `EDEN_MODEL_BUILDER` to `gemini-2.5-pro`
  or equivalent on a paid plan before building this feature

### Phased approach

The build-on-stage demo is high-risk. Suggested reliability ladder:
1. Build phase: generate files, install deps, launch
2. If launch fails: fall back to prebuilt app silently, EDEN narrates naturally
3. If even that fails: PRESENTATION mode has a pre-recorded build sequence

---

## 8. Known Issues

**Voice quality is dependent on what EDEN says.**
ElevenLabs is active and working correctly. The voice itself (George, `eleven_turbo_v2_5`)
is capable. If responses still sound robotic, the problem is in the words EDEN chooses,
not the voice engine.

**Placeholder text in the conversation panel is outdated.**
`App.tsx` shows "Voice input arrives on Day 2 — type for now." This should be removed
or updated before the demo.

**Emotion state does not reset between turns.**
After a response with emotion `sarcastic`, the emotion label stays visible until the
next reply arrives. In a long pause, the Orb color is stale. Consider resetting emotion
to `idle` when state returns to `idle`.

**ElevenLabs timeout is 30 seconds.**
For long responses, the `httpx` timeout in `tts_elevenlabs.py` could expire. EDEN
should keep responses short, but if a long explanation is generated, it may fall back
to browser TTS silently. Monitor this during testing.

**`demo_responses.json` has not been reviewed.**
The PRESENTATION mode fallback responses have not been curated for the lecture content.
Before relying on PRESENTATION mode, write and review every scripted response.

**CORS is `allow_origins=["*"]`.**
Correct for a localhost demo. Never expose the backend publicly without locking this
down.

**`run.sh` does not work on Windows.**
On Windows, use `uvicorn app.main:app --reload` directly in PowerShell from the
`backend/` directory.

**The verify script may fail on Windows paths.**
`scripts/verify_setup.py` was written primarily for testing — run it from the repo root
as `python scripts\verify_setup.py`. If path resolution fails, run from `backend/`
with `python ..\scripts\verify_setup.py`.

**No automated tests.**
All verification is manual (WebSocket integration tests driven by standalone Python
scripts). A lightweight pytest suite for the provider abstraction, personality parser,
and orchestrator failure paths would reduce the "did I break something?" cycle before
each demo.

---

## 9. How to Run

### Backend

```powershell
cd D:\EDEN\backend
# First time only:
python -m pip install -r requirements.txt

# Every time:
uvicorn app.main:app --reload
```

Check: `http://localhost:8000/health` → `{"status":"ok","mode":"SAFE","llm":"gemini","tts":"elevenlabs"}`

Live test: `http://localhost:8000/diagnose` → fires a real Gemini call, returns parsed reply.

### Frontend

```powershell
cd D:\EDEN\frontend
# First time only:
npm install

# Every time:
npm run dev
```

Open `http://localhost:5173` in **Chrome** (Web Speech API is Chrome-only).

### Verification

```powershell
# From repo root
python scripts\verify_setup.py           # deps + credentials + provider table
python scripts\verify_setup.py --live    # + live model call
python scripts\verify_setup.py --models  # list available Gemini models for this key
```

---

## 10. Design Decisions

This section documents the key engineering and architectural decisions that have shaped
EDEN. Each decision carries a rationale. Future development should understand and
preserve this reasoning rather than reversing decisions without cause.

---

### Gemini as the LLM

**Decision:** Use Google Gemini (`gemini-3.1-flash-lite`) as the primary reasoning model,
replacing Claude.

**Why:** The free-tier Gemini API was the only option that offered both a working API
key and sub-second time-to-first-token (0.66 s TTFT) during initial development.
For a live voice interaction demo, latency between speech and response is the single
most important quality metric — a 3-second pause before EDEN speaks breaks the illusion
of presence. `gemini-3.1-flash-lite` was the only model that passed this bar on the
available credentials.

**Alternatives considered:**
- Claude (Anthropic): initially planned, but API access was unconfirmed at the start
  of development. Claude Code access is not the same as Anthropic API access.
- `gemini-2.5-flash` / `gemini-2.5-pro`: both return 404 or 429 on new free-tier keys.
- `gemini-3.5-flash`: a thinking model with 10–20 s TTFT — unsuitable for voice streaming.

**Preserve:** The model ID is controlled by `EDEN_MODEL_VOICE` in `.env`. Upgrading to a
faster or smarter model is a one-line config change — no code needs to change. On a paid
Gemini plan, `gemini-2.5-pro` is the right upgrade for the builder agent
(`EDEN_MODEL_BUILDER`). Do not hardcode model IDs anywhere in the codebase.

---

### Provider abstraction for LLM and TTS

**Decision:** The application depends only on `LLMProvider` and `TTSProvider` Protocols.
Concrete vendors (Gemini, ElevenLabs) are selected once at startup by `factory.py` and
are invisible to the rest of the app.

**Why:** A live demo cannot be blocked on external API availability. If Gemini goes down
during setup, the app should still run (`MockLLM`). If ElevenLabs is unavailable, the
app should still speak (`BrowserTTS`). If network access disappears entirely, the demo
should still work (`ScriptedLLM` + `BrowserTTS`). The abstraction also means swapping
vendors — adding an OpenAI provider, replacing ElevenLabs — is a new file plus a change
to `factory.py`. Nothing else changes.

**Alternatives avoided:**
- Direct vendor SDK calls throughout the codebase: would make every module dependent on
  a specific vendor and would make fallback logic scattered and brittle.
- Runtime provider switching: considered and rejected. The demo runs with one provider
  set per session. Switching mid-session introduces state complexity with no demo benefit.

**Preserve:** Always add new AI integrations as concrete provider implementations under
`backend/app/providers/`. Never import a vendor SDK directly in `main.py` or any
application logic file. The factory is the only place that knows which vendor is active.

---

### JSON-based emotion pipeline

**Decision:** The LLM always returns a structured JSON object `{"emotion": "<value>",
"response": "<spoken text>"}`. The `response_mime_type="application/json"` parameter
is set in the Gemini config, enforcing valid JSON at the API level.

**Why:** Mixing emotion metadata with spoken text in a single string would require
fragile parsing (regex, markers, heuristics) that degrades silently when the model
changes its output format. A structured contract between the personality prompt and the
parsing layer is more robust. The JSON format also gives EDEN's emotional state a clean
channel to the frontend that is completely separate from the spoken reply — the Orb
can animate before the first word is spoken.

The `EMOTION_VALUES` frozenset is defined once in `eden_personality.py` and imported
by `main.py`. This means the prompt and the parser can never silently diverge — if
a new emotion is added to the prompt, it must be added to the frozenset too.

**Alternatives avoided:**
- Inline markers like `[EMOTION:confident] Your response here` — fragile, hard to
  strip cleanly before TTS, easy for the model to format inconsistently.
- Post-hoc sentiment analysis on the spoken text — removes the ability to intentionally
  mismatch emotion and content (e.g. calm `concerned` voice during an error recovery).

**Preserve:** The JSON contract is the interface. If new fields are needed in the future
(e.g. `intent`, `confidence`), add them to both the prompt and the parser. Never parse
the `response` field for metadata — that field belongs to ElevenLabs.

---

### Behavioral personality model instead of scripted responses

**Decision:** EDEN's personality is defined entirely through behavioral principles,
a cognitive reasoning framework, and an intent vocabulary. There are zero example
response strings in the production prompt.

**Why:** Scripted examples become templates. The moment a prompt contains
"Done. That was almost suspiciously easy", the model reaches for that phrase whenever
something completes — because it has been shown, by example, that this is the correct
output class. Over multiple interactions, the audience notices repetition and the
illusion breaks. The behavioral model instead gives EDEN a process to apply fresh to
every situation: read beneath the surface, identify intent, read the context, choose
the rhythm. This produces genuinely varied output because the generation starts from
context, not from a stored phrase bank.

**The cognitive model has four layers:**
1. Reading beneath the surface of the request
2. Intent classification (twelve named types with implied response shapes)
3. Situational awareness (six named contexts with different response requirements)
4. Conversational pacing (rhythm variation guided by conversation history)

**Alternatives avoided:**
- Purely rule-based prompts ("never say X", "always do Y"): necessary as constraints,
  insufficient as a model. Rules suppress bad outputs; principles generate good ones.
- Few-shot examples: effective for output format, harmful for personality — the model
  memorizes the examples as canonical outputs.

**Preserve:** When improving the personality, add or refine principles and situational
guidance. Do not add example responses. If a specific behavior is wrong, diagnose why
the principle produced it rather than patching with a counter-example.

---

### Cinematic UI

**Decision:** Glass-panel HUD aesthetic, abstract reactive orb (not a face or avatar),
dark background, monospace typography, minimal chrome.

**Why:** The demo audience is undergraduate students in a lecture hall. The UI is on a
projector. It needs to feel futuristic and intentional at a distance. The glass HUD
communicates that this is a technical system without looking like a terminal. The
abstract orb communicates emotional state without the uncanny valley problems of a
humanoid face. The cinematic aesthetic reinforces the JARVIS/FRIDAY reference — the
audience should feel like they are watching something from a film, not a startup demo.

**Alternatives avoided:**
- Chat interface (WhatsApp style): too familiar, undermines the "this is different"
  feeling that is the entire point of the demo.
- Humanoid avatar: realistic faces performing emotions look wrong and distract from
  the content of what EDEN is saying.
- Minimal / brutalist UI: would communicate "prototype" rather than "product".

**Preserve:** The glass effect (`glass` CSS class), dark background, and cyan/purple
color scheme are load-bearing — they establish the aesthetic. The Orb color mapping
(each emotion → a distinct color) is part of the emotional communication layer.
When the Three.js orb replaces the placeholder, it should use the same color palette
and animate in response to the same `state` and `emotion` events.

---

### LIVE / SAFE / PRESENTATION modes

**Decision:** Three named operating modes selected by `EDEN_MODE` environment variable.
`LIVE`: full real-time AI. `SAFE`: real AI with per-turn graceful fallbacks. `PRESENTATION`:
fully scripted, zero network calls.

**Why:** A live demo on a conference projector has three failure scenarios:
network connectivity drops, an API key exceeds quota, or the model returns a bad
response at the worst moment. Each scenario requires a different fallback strategy.
`PRESENTATION` mode is the parachute — it runs on no connectivity at all. `SAFE` mode
is the recommended default — real Gemini + ElevenLabs, but each failed TTS call falls
back to browser voice silently so the audience never sees an error. `LIVE` mode signals
intent to use the full stack with no safety net.

The mode also controls which providers are selected by `factory.py`, so the fallback
ladder is configured once at startup and never needs conditional logic in application code.

**Alternatives avoided:**
- Single mode with runtime feature flags: more complex to reason about and test.
- Runtime mode switching: would require provider re-initialisation mid-session, adding
  significant complexity for a demo benefit that can be achieved by restarting the app.

**Preserve:** Always present in `SAFE` mode. Test in `LIVE` the day before.
Keep `PRESENTATION` mode scripted responses current — they are the last line of defence.
The mode system must be preserved exactly as-is when the coding agent is added.

---

### ElevenLabs for TTS

**Decision:** ElevenLabs is the primary TTS provider. Voice: George (`JBFqnCBsd6RMkjVDRZzb`),
model: `eleven_turbo_v2_5`. Settings: stability 0.5, similarity_boost 0.75, style 0.12,
speaker_boost enabled.

**Why:** The voice is the most perceptible quality dimension of a voice AI demo.
Browser SpeechSynthesis sounds robotic and unmistakably synthetic — it undermines the
"AI companion" feeling in the first sentence. ElevenLabs with the George voice (calm,
British, authoritative) produces audio that sounds composed and intelligent. The turbo
model is used rather than the higher-quality multilingual model specifically for latency
— `eleven_turbo_v2_5` returns audio fast enough that the gap between thinking and
speaking feels natural.

**Settings rationale:**
- `stability: 0.5` — lower values introduce erratic variation between words; 0.5 is
  the balance between expressiveness and consistency.
- `style: 0.12` — a small non-zero value adds subtle character to prosody without
  over-stylizing.
- `use_speaker_boost: True` — improves clarity in projector audio environments.

**Preserve:** The `engine = "server_audio"` attribute on `ElevenLabsTTS` is the signal
that tells `_speak()` to call `synthesize()` rather than delegate to the browser.
Any new TTS provider must set this attribute correctly. The per-turn fallback to browser
TTS on `Exception` must be preserved — it is the reliability layer that prevents a
single failed TTS call from breaking the live demo.

---

### Wake sequence design

**Decision:** Wake phrase detection lives in `main.py` as a frozenset string match
(`_is_wake_phrase()`). On detection, a `[WAKE SEQUENCE]` marker is prepended to the
message passed to the LLM. Session history always stores the original text.

**Why:** The opening moment of the lecture is the highest-stakes interaction in the demo.
If EDEN responds to "Good afternoon everyone" with a normal conversational reply, the
demo loses its cinematic opening. Explicit detection + marker injection ensures the LLM
always knows this is not a casual greeting — it is a cinematic moment with specific
requirements. Keeping the original text in session history means the wake event reads
naturally in the conversation replay without exposing the implementation detail.

**Alternatives considered:**
- Full hardcoded wake response: maximally reliable but never fresh. If the audience
  attends two lectures and hears the same wake response, the illusion breaks.
- Purely prompt-based detection: the LLM could in principle detect audience-directed
  greetings from context alone. Rejected because the stakes are too high for
  probabilistic detection — the wake moment must fire correctly every time.
- Pre-generated ElevenLabs audio clip for the wake: the most reliable approach for
  a single rehearsed phrase, but eliminates natural variation. Planned as a fallback
  for Day 6, not as the primary mechanism.

**Preserve:** The wake detection is intentionally simple (frozenset match, not ML).
Do not replace it with a classifier. If new trigger phrases are needed, add them to
`_WAKE_PATTERNS`. The `[WAKE SEQUENCE]` marker in the LLM message is what activates
the personality prompt's wake sequence instructions — the two must remain in sync.

---

### Agentic AI rather than conversational AI

**Decision:** EDEN is being built as an agentic AI system, not a sophisticated chatbot.
The coding agent (next milestone) will plan, act, observe, and iterate — not describe.

**Why:** The guest lecture's purpose is to demonstrate what Generative AI can actually
do in 2026, not what it can say. A demo where EDEN only generates text — however
eloquent — is a demo of a better chatbot. A demo where a student says "build me a
calculator" and EDEN plans the project, generates code, installs dependencies, launches
the app, and shows it running live communicates something categorically different:
that AI can be a genuine collaborator in creative and technical work.

The agentic architecture also means the audience can give EDEN actual creative direction
and watch a real outcome, not a narrated simulation of one.

**Preserve:** Every feature added to EDEN should be evaluated against this question:
"Does this make EDEN more capable or more agentic, or does it just make it sound better?"
Personality improvements have diminishing returns. Capability improvements — the ability
to act in the world, not just describe action — compound. The coding agent is the
next step in making EDEN genuinely useful to watch.

---

## 11. Agent Roadmap — EDEN Coding Agent

> **This section is a design document only. Nothing described here is implemented.**
> It should be detailed enough that a new development session can begin implementation
> directly from this document.

---

### Vision

A student says: "Build me a calculator app."

EDEN should understand the request, plan the implementation, generate the files, install
dependencies, launch the application, open it in the browser, verify it is working, and
communicate naturally throughout the entire process — not with log messages, but in
EDEN's voice.

The audience watches a real application being built in real time. That is the demo.

---

### Architecture overview

The coding agent is a new subsystem that runs when EDEN detects a build request.
It is **parallel to** the conversational pipeline, not a replacement for it.
The existing `main.py` loop, `LLM`, `TTS`, `Session`, and WebSocket infrastructure
remain unchanged. The agent calls into them.

```
main.py: _handle_user_message()
         │
         ├─ _is_build_request(text)?
         │     no  → existing conversational pipeline (unchanged)
         │     yes ↓
         │
         ▼
agents/orchestrator.py  run(websocket, session, text, llm, tts)
         │
         ├─ agents/intent.py      parse_build_request(text) → BuildRequest
         ├─ agents/planner.py     generate_plan(request, llm) → Plan
         │
         ├─ [emit plan_started event]
         │
         ├─ for each step in plan:
         │     tools/registry.py  execute(step) → ToolResult
         │     [emit tool_called / tool_result events]
         │     if result.failed:
         │         error_recovery(step, result)
         │
         ├─ builder/validator.py  validate(workspace)
         ├─ tools/shell.py        run(start_command, cwd=workspace)
         ├─ tools/browser.py      open(url)
         │
         ├─ [verify: wait for app to respond at expected_url]
         │
         ├─ narrate(result, llm, tts)  → speech_audio event
         └─ [emit build_complete or build_failed event]
```

---

### New files to create

All new files live under `backend/app/`. No existing files are modified except:
- `backend/app/main.py` — add `_is_build_request()` detection and route to orchestrator
- `backend/app/events.py` — add new event builder functions
- `frontend/src/lib/events.ts` — add new event types (mirror of events.py)
- `frontend/src/App.tsx` — handle new events, conditionally render `BuilderStage`

```
backend/app/
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py      top-level agent loop — drives the full build sequence;
│   │                        calls render_verifier + repairer after HTTP verify
│   ├── render_verifier.py   Playwright headless DOM check (root populated, no overlay,
│   │                        no fatal console errors); httpx fallback if no browser
│   ├── repairer.py          LLM-driven App.jsx repair from console error list;
│   │                        uses Vite HMR — no server restart needed
│   ├── planner.py           calls LLM to generate a structured Plan from a BuildRequest
│   └── intent.py            parses "build me a calculator" → typed BuildRequest
│
├── tools/
│   ├── __init__.py
│   ├── registry.py          maps plan step actions to tool implementations
│   ├── filesystem.py        create_file, create_directory, read_file, list_files
│   ├── shell.py             run_command — subprocess with timeout, captured output
│   └── browser.py           open_browser(url) — platform-aware browser launch
│
└── builder/
    ├── __init__.py
    ├── sandbox.py           workspace lifecycle — create, locate, clean up per-session
    ├── template.py          React + Vite SPA template — files injected as starting point
    ├── validator.py         pre-execution checks on generated code
    └── fallback.py          prebuilt app per app type — used if live generation fails

frontend/src/features/builder/
    ├── BuilderStage.tsx     agent pipeline panel — appears when a build starts
    ├── PlanStep.tsx         individual step with pending/running/done/failed state
    └── ToolCall.tsx         tool invocation display with args and output
```

---

### New WebSocket events

Add to `backend/app/events.py` and mirror in `frontend/src/lib/events.ts`.

| Event | Direction | Fields | When emitted |
|---|---|---|---|
| `build_started` | server→client | `app_type`, `app_name` | Orchestrator begins |
| `plan_ready` | server→client | `steps: list[str]` | Plan generated, before execution |
| `tool_called` | server→client | `tool: str`, `args: dict`, `step_index: int` | Before each tool call |
| `tool_result` | server→client | `tool: str`, `success: bool`, `output: str`, `step_index: int` | After each tool returns |
| `build_narrate` | server→client | `text: str` | EDEN speaks a progress update |
| `build_complete` | server→client | `url: str`, `app_name: str` | App is running |
| `build_failed` | server→client | `reason: str`, `used_fallback: bool` | Build could not complete |

The `build_narrate` event should be handled identically to a normal `reply_done` +
`speech_audio` sequence — EDEN speaks the narration through ElevenLabs.

---

### Step 1 — Intent detection (`agents/intent.py`)

**Responsibility:** Determine whether the incoming message is a build request, and if so,
extract what is being asked for.

**Implementation:**

```python
@dataclass
class BuildRequest:
    raw_text: str          # the original user message
    app_type: str          # "calculator" | "todo" | "timer" | "quiz" | "notes" | "form"
    app_name: str          # human-readable name, e.g. "Calculator"
    features: list[str]   # any specific features mentioned ("dark mode", "history")
    is_ambiguous: bool     # true if the app type couldn't be determined confidently

def parse_build_request(text: str, llm: LLMProvider) -> Optional[BuildRequest]:
    ...
```

**Detection logic:**

Phase 1 — keyword pre-filter (fast, no LLM call):
- Trigger words: "build", "create", "make", "generate", "write"
- Target words: "app", "application", "website", "calculator", "todo", "timer", etc.
- If neither set matches, return `None` → route to conversational pipeline

Phase 2 — LLM classification (only if pre-filter passes):
- Send a short classification prompt (separate from the main EDEN personality prompt)
- Returns structured JSON: `{ "app_type": "calculator", "app_name": "...", "features": [...], "is_ambiguous": false }`
- If `app_type` is not in the whitelist → `is_ambiguous = true`

**Whitelist of supported app types:**

| Type | Description |
|---|---|
| `calculator` | Basic arithmetic calculator |
| `todo` | Task list with add/complete/delete |
| `timer` | Countdown timer or stopwatch |
| `quiz` | Multiple-choice quiz or flashcard set |
| `notes` | Simple text notes editor |
| `form` | Single-page data entry form |

If the request is outside the whitelist (e.g. "build me Instagram"), the orchestrator
should not attempt to build it. Instead it routes back to the conversational pipeline
with a `Challenge` intent — EDEN acknowledges the ambition and redirects naturally.

---

### Step 2 — Workspace management (`builder/sandbox.py`)

**Responsibility:** Create and manage an isolated working directory for each build.

```python
class Sandbox:
    def __init__(self, session_id: str, app_name: str) -> None:
        self.root = Path(tempfile.gettempdir()) / "eden_builds" / session_id / app_name
    
    def create(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root
    
    def destroy(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
    
    def path(self, relative: str) -> Path:
        return self.root / relative
```

The sandbox root is `%TEMP%\eden_builds\<session_id>\<app_name>\` on Windows.
One sandbox per build per session. Destroyed at session end or on the next build start.

---

### Step 3 — Planning (`agents/planner.py`)

**Responsibility:** Call the LLM to generate a structured build plan from a `BuildRequest`.

The planner uses a **separate, focused system prompt** — not the EDEN personality prompt.
It instructs the model to generate a precise JSON plan, not a conversational response.

```python
@dataclass
class PlanStep:
    id: int
    action: str          # "create_directory" | "create_file" | "run_command" | "open_browser"
    description: str     # human-readable, for the frontend step display
    path: Optional[str]  # for filesystem actions
    content: Optional[str]  # file content (for create_file steps)
    command: Optional[str]  # for run_command steps
    url: Optional[str]   # for open_browser steps

@dataclass
class Plan:
    app_type: str
    app_name: str
    workspace: Path
    steps: list[PlanStep]
    start_command: str           # e.g. "npm run dev"
    expected_url: str            # e.g. "http://localhost:5174"
    narration_intro: str         # EDEN speaks this before starting
    narration_complete: str      # EDEN speaks this when done
```

**Planner system prompt (separate from personality):**

The planner prompt instructs the model to:
- Act as a technical architect, not a companion
- Output only a JSON plan conforming to the Plan schema
- Use the React + Vite template as the starting point
- Keep the implementation minimal — a working MVP, not a full product
- Generate complete, working file contents (not stubs)

The planner uses `EDEN_MODEL_BUILDER` (configured separately from voice model).

**Template integration (`builder/template.py`):**

The React + Vite template provides the boilerplate:
- `package.json` with React, Vite, and relevant packages
- `vite.config.ts` with correct port and settings
- `index.html`
- `src/main.tsx` and `src/App.tsx` (minimal, overwritten by the plan)
- `src/styles/globals.css` (minimal)

The planner generates only the files that differ from the template.
Template files are written first; plan-generated files overwrite them.
This keeps generated code small and reduces LLM output length.

---

### Step 4 — Tool execution (`tools/`)

**`tools/registry.py`** — maps action strings to tool functions:

```python
REGISTRY: dict[str, Callable] = {
    "create_directory": filesystem.create_directory,
    "create_file":      filesystem.create_file,
    "run_command":      shell.run_command,
    "open_browser":     browser.open_browser,
}

async def execute(step: PlanStep, sandbox: Sandbox) -> ToolResult:
    fn = REGISTRY.get(step.action)
    if fn is None:
        return ToolResult(success=False, error=f"Unknown action: {step.action}")
    return await fn(step, sandbox)
```

**`tools/filesystem.py`:**

```python
@dataclass
class ToolResult:
    success: bool
    output: str
    error: Optional[str] = None

async def create_directory(step: PlanStep, sandbox: Sandbox) -> ToolResult:
    path = sandbox.path(step.path)
    path.mkdir(parents=True, exist_ok=True)
    return ToolResult(success=True, output=f"Created {step.path}")

async def create_file(step: PlanStep, sandbox: Sandbox) -> ToolResult:
    path = sandbox.path(step.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(step.content or "", encoding="utf-8")
    return ToolResult(success=True, output=f"Written {step.path} ({len(step.content or '')} chars)")
```

**`tools/shell.py`:**

```python
async def run_command(step: PlanStep, sandbox: Sandbox, timeout: int = 60) -> ToolResult:
    proc = await asyncio.create_subprocess_shell(
        step.command,
        cwd=str(sandbox.root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace").strip()
        success = proc.returncode == 0
        return ToolResult(success=success, output=output[:2000])
    except asyncio.TimeoutError:
        proc.kill()
        return ToolResult(success=False, error=f"Command timed out after {timeout}s")
```

`npm install` is given a 120-second timeout. `npm run dev` is started as a background
process (do not await completion — it keeps running). After launch, the orchestrator
polls the expected URL for up to 10 seconds to verify the app is responding.

**`tools/browser.py`:**

```python
import webbrowser

async def open_browser(step: PlanStep, sandbox: Sandbox) -> ToolResult:
    webbrowser.open(step.url)
    return ToolResult(success=True, output=f"Opened {step.url}")
```

---

### Step 5 — Code validation (`builder/validator.py`)

Run before executing any generated code. Prevents clearly broken code from being
launched in front of the audience.

Checks to perform:

1. **Required files exist** — `package.json`, `src/App.tsx`, `index.html`
2. **`package.json` is valid JSON** — catches LLM formatting errors
3. **No `eval()` calls** — basic security check on generated JS/TS
4. **No external fetch to unknown origins** — prevents accidental data exfiltration
5. **File sizes are reasonable** — flags suspiciously large or empty files

If validation fails, the orchestrator attempts one repair loop:
- Send the failing file back to the LLM with the validation error
- Receive a corrected version
- Re-validate once
- If still failing → fall back to the prebuilt app

---

### Step 6 — Narration

At key moments, the orchestrator generates spoken narration using the main EDEN
personality prompt (not the planner prompt) and speaks it via ElevenLabs.

Narration points:

| Moment | What EDEN says |
|---|---|
| Plan ready | Brief description of what it is about to build — in EDEN's voice, not a plan readout |
| Build running | A single observation while waiting for `npm install` |
| App launched | A natural statement that the app is ready — not "Application started successfully" |
| Build failed, using fallback | Honest, calm — "something did not go according to plan, but we have a backup" |

The narration text is LLM-generated at each point using the `Demonstrate` or `Celebrate`
intent and the `Live coding` situational context. It is short — one to two sentences.
It goes through `TTS.synthesize()` exactly like a normal conversational reply and is
emitted as a `build_narrate` event carrying the spoken text. The frontend handles it
identically to `speech_audio`.

---

### Step 7 — Error recovery

**Level 1 — Code validation failure:** attempt one repair loop (re-generate the failing
file with the error message as context). If second attempt also fails, proceed to Level 2.

**Level 2 — Runtime failure (app exits immediately or does not respond):** try one
common fix (e.g. missing dependency discovered at runtime — re-run `npm install` with
the specific package). If the app still does not respond at `expected_url`, proceed to
Level 3.

**Level 3 — Fallback to prebuilt app:** `builder/fallback.py` returns the path to a
pre-written, pre-tested version of the requested app type. The orchestrator copies it
into the sandbox and launches it. EDEN narrates naturally that it is taking a different
approach — does not use the word "fallback". The audience sees a working app.

**Level 4 — Fallback app also fails:** emit `build_failed` with `used_fallback: true`.
EDEN speaks a calm recovery in character. The conversational pipeline resumes normally.

No level of failure should produce an error message visible to the audience.

---

### Step 8 — Result verification

After `npm run dev` starts (or the fallback app launches), the orchestrator polls the
`expected_url` with an HTTP GET request at 1-second intervals for up to 10 seconds.

```python
async def wait_for_app(url: str, timeout: int = 10) -> bool:
    async with httpx.AsyncClient() as client:
        for _ in range(timeout):
            try:
                resp = await client.get(url, timeout=2.0)
                if resp.status_code < 500:
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)
    return False
```

If the app responds within 10 seconds, emit `build_complete`. If not, proceed to
error recovery.

---

### Orchestrator (`agents/orchestrator.py`)

The orchestrator is the top-level driver. It owns the full build sequence and all
event emission. It should be callable from `main.py` with the existing provider
instances — no new providers or configurations needed.

```python
async def run(
    websocket: WebSocket,
    session: Session,
    request: BuildRequest,
    llm: LLMProvider,
    tts: TTSProvider,
    system_prompt: str,
) -> None:
    sandbox = Sandbox(session_id=id(session), app_name=request.app_name)
    sandbox.create()

    # 1. Plan
    plan = await planner.generate_plan(request, llm, sandbox)
    await websocket.send_json(events.plan_ready([s.description for s in plan.steps]))

    # 2. Narrate intro
    await _narrate(websocket, plan.narration_intro, llm, tts, system_prompt)

    # 3. Write template files
    template.write(sandbox)

    # 4. Execute steps
    for i, step in enumerate(plan.steps):
        await websocket.send_json(events.tool_called(step.action, step_index=i))
        result = await registry.execute(step, sandbox)
        await websocket.send_json(events.tool_result(step.action, result, step_index=i))

        if not result.success:
            recovered = await _recover(step, result, sandbox, llm)
            if not recovered:
                await _fallback(websocket, request, sandbox, llm, tts, system_prompt)
                return

    # 5. Validate
    validation = validator.validate(sandbox)
    if not validation.ok:
        repaired = await _repair(validation, sandbox, llm)
        if not repaired:
            await _fallback(websocket, request, sandbox, llm, tts, system_prompt)
            return

    # 6. Launch
    dev_proc = await shell.start_background(plan.start_command, sandbox)
    app_running = await wait_for_app(plan.expected_url)

    if not app_running:
        await _fallback(websocket, request, sandbox, llm, tts, system_prompt)
        return

    # 7. Open browser
    await browser.open_browser_url(plan.expected_url)

    # 8. Complete
    await websocket.send_json(events.build_complete(plan.expected_url, plan.app_name))
    await _narrate(websocket, plan.narration_complete, llm, tts, system_prompt)
    session.add_assistant(plan.narration_complete)
```

---

### Integration with existing `main.py`

Add two things to `main.py`:

**1. Build intent detection:**

```python
def _is_build_request(text: str) -> bool:
    text_l = text.lower()
    build_words = {"build", "create", "make", "generate", "write"}
    target_words = {"app", "application", "website", "tool", "calculator",
                    "todo", "timer", "quiz", "notes", "form"}
    return any(b in text_l for b in build_words) and any(t in text_l for t in target_words)
```

**2. Routing in `_handle_user_message`:**

```python
if _is_build_request(text) and settings.agent_enabled:
    request = await intent.parse_build_request(text, LLM)
    if request and not request.is_ambiguous:
        await orchestrator.run(websocket, session, request, LLM, TTS, SYSTEM_PROMPT)
        return
    # Ambiguous or unrecognised → fall through to conversational pipeline
```

Add `EDEN_AGENT_ENABLED=true` to `.env` and `config.py`. This lets the agent be
disabled for stability testing without code changes.

---

### Frontend changes

**`frontend/src/App.tsx`:**

- Add `buildActive: boolean` state — set `true` on `build_started`, `false` on
  `build_complete` or `build_failed`
- When `buildActive` is true, render `<BuilderStage />` alongside the conversation panel
- Handle all new events in `handleEvent`

**`frontend/src/features/builder/BuilderStage.tsx`:**

- Receives the plan steps and their current status (pending / running / done / failed)
- Shows a vertical pipeline of `<PlanStep />` components
- Animates each step as it transitions from pending → running → done
- Shows `<ToolCall />` for each tool invocation within a step
- Shows a "RUNNING" indicator while the app is being launched

**No changes needed** to `EdenSocket`, `audio.ts`, `events.py` event protocol shapes,
or the WebSocket `/ws` handler structure.

---

### Implementation order

1. `agents/intent.py` — build intent detection (fast path only, no LLM)
2. `builder/sandbox.py` — workspace management
3. `tools/filesystem.py` + `tools/shell.py` + `tools/browser.py` — core tools
4. `builder/template.py` — React + Vite starting template
5. `agents/planner.py` — LLM-driven plan generation
6. `builder/validator.py` — pre-execution checks
7. `agents/orchestrator.py` — full loop with narration
8. `builder/fallback.py` — prebuilt apps per type (build these manually in advance)
9. New events in `events.py` + `events.ts`
10. Frontend: `BuilderStage.tsx`, routing in `App.tsx`
11. Integration in `main.py`

Build and test each layer independently before integrating. The fallback apps (step 8)
should be the first thing built — they are the safety net for everything else.

---

*This document should be rewritten (not appended) at the end of each significant session.*
