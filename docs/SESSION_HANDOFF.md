# EDEN — Session Handoff

> **Purpose:** This document lets a fresh Claude Code session (or any developer) continue building EDEN **without reading prior conversation history**. It is the single source of truth for current status. Update it at the end of each session.
>
> **Last updated:** Post-Day-0 — Claude provider hardening + diagnostics session.
> **Repo root:** `D:\EDEN` (Windows, `win32`). Shells available: PowerShell and Git Bash.

---

## 1. Current implementation status

| Area | Status |
|------|--------|
| Blueprint (docs 01–06) | ✅ Complete, signed off |
| Day 0 — scaffold, DEMO MODE, provider abstraction, verify script | ✅ Complete & verified end-to-end |
| Day 1 — text conversation spine (streaming) | ✅ Working (part of Day 0 delivery) |
| Claude provider hardening + diagnostics | ✅ Done this session (see §2b) |
| Day 2 — voice I/O + Three.js orb | ⛔ Not started (recommended next) |
| Day 3 — boot/wake + full HUD polish | ⛔ Not started |
| Day 4 — agent activity visualizer | ⛔ Not started |
| Day 5 — AI software builder | ⛔ Not started |
| Day 6 — lecture assistant + reliability hardening | ⛔ Not started |
| Day 7 — rehearsal + polish | ⛔ Not started |

**Verified working right now (with ZERO API keys):** a user types a message in the browser → EDEN streams a reply token-by-token → the reactive orb transitions `idle → thinking → speaking` → the browser speaks the reply. This was confirmed live in a real browser, not just in tests.

**Claude (LIVE mode) status:** Code is complete and hardened; `ClaudeLLM` will activate the moment `ANTHROPIC_API_KEY` (or `EDEN_ASSUME_ANTHROPIC=true`) is set in `backend/.env`. **LIVE mode has NOT yet been verified end-to-end** — no Anthropic API key was present in this session. See §8 for the exact verification steps.

---

## 2b. Claude provider hardening (this session)

- **`backend/.env` created** from `.env.example`. Fill in `ANTHROPIC_API_KEY` or set `EDEN_ASSUME_ANTHROPIC=true` to activate `ClaudeLLM`. No code changes needed — the factory auto-detects.
- **`llm_claude.py` hardened** — explicit `AuthenticationError` / `RateLimitError` / `APIConnectionError` logging; `thinking` parameter now only sent to models that support the extended-thinking API (prevents silent param-rejection on other models).
- **`/diagnose` endpoint added** to the backend — fires a real one-shot streaming call against the active LLM and returns `{"llm_ok": bool, "llm_sample": "...", "detail": "..."}`. Hit `http://localhost:8000/diagnose` after adding a key to confirm Claude is live.
- **`verify_setup.py --live`** upgraded — now runs an actual `AsyncAnthropic.messages.stream()` call (instead of just listing models) and prints the first reply fragment.
- **`docs/HOW-TO-SWITCH-MODES.md`** added — quick reference for mode switching, key setup, and the full test sequence.
- **Mock and Browser TTS fallbacks confirmed still working** — `health` and `diagnose` both return cleanly with no keys (`SAFE` + `MockLLM` + `BrowserTTS`).

**To activate real Claude:** add `ANTHROPIC_API_KEY=sk-ant-...` (or `EDEN_ASSUME_ANTHROPIC=true`) to `backend/.env`, restart the backend, and open `http://localhost:8000/diagnose`. Expect `"llm_ok": true` and a reply fragment.

**LIVE mode end-to-end verification was NOT completed this session** — no API key was available. The verification sequence is in §8 and must be done before starting Day 2.

---

## 2. Completed Day 0 work

- **Blueprint finalized** — 6 docs in `docs/`. Added `06-demo-modes-and-providers.md` (DEMO MODE + provider abstraction as hard requirements) and updated Day 0 in `05-development-plan.md`.
- **Backend scaffold** — FastAPI app with a `/ws` WebSocket that streams a typed **event protocol** (`ready`, `state`, `token`, `reply_done`, `speak`, `speech_audio`, `error`, `pong`). `/health` endpoint too.
- **DEMO MODE** — `LIVE` / `SAFE` / `PRESENTATION`, read from `EDEN_MODE` (default `SAFE`).
- **Provider abstraction** — `LLMProvider` / `TTSProvider` interfaces; `factory.py` selects concrete providers from **mode + credential availability**. Implementations: `ClaudeLLM`, `MockLLM`, `ScriptedLLM`, `ElevenLabsTTS`, `BrowserTTS`.
- **Frontend scaffold** — React + TS + Vite + Tailwind + Framer Motion. Glass HUD, placeholder reactive orb, streaming conversation panel, system-status panel, browser + server-audio playback. WebSocket client with auto-reconnect.
- **Day-0 verification** — `scripts/verify_setup.py` reports deps/credentials and resolved providers per mode; non-fatal on missing optional keys.
- **Verification performed:** backend compiles + WebSocket smoke test passes; frontend `npm run build` clean (390 modules, 0 errors); full flow confirmed in a live browser session.

---

## 3. Current architecture summary

Client–server, **event-stream driven**. The backend does not return a single answer — it streams typed *events* over a WebSocket and the frontend renders them. One protocol serves all planned demos.

```
Browser (React)  ── WebSocket /ws ──►  FastAPI backend  ──►  LLM provider (Claude | Mock | Scripted)
   │  renders events                       │                └─►  TTS provider (ElevenLabs | Browser)
   │  (orb, conversation, status)          │
   └─ Web Speech API (STT, Day 2)          └─ providers chosen by factory from EDEN_MODE + keys
```

**Key concepts** (full detail in `docs/01` and `docs/06`):
- **Event protocol** is the backbone — backend `app/events.py` mirrors frontend `src/lib/events.ts`. Keep them in sync when adding events.
- **Provider abstraction** — the app depends only on interfaces; vendors are swappable; no keys ⇒ mock/browser fallbacks so dev is never blocked.
- **DEMO MODE** — `LIVE`/`SAFE` behave the same for provider *selection* today (both use Claude+voice when available); `PRESENTATION` forces `ScriptedLLM` + `BrowserTTS` and makes **zero external calls**. (The richer per-mode fallback behavior — cached responses, prebuilt builder — is implemented in later days.)
- **Avatar** is an abstract reactive orb (currently a Framer Motion placeholder; upgrade to Three.js on Day 2), never a humanoid face.

**Runtime shape:** two processes — `uvicorn` (backend, `:8000`) and `vite` (frontend, `:5173`). Frontend opens `ws://localhost:8000/ws`.

---

## 4. Files created

```
D:\EDEN\
├── README.md                         # project overview
├── .gitignore
│
├── docs\
│   ├── 01-architecture.md
│   ├── 02-technology-decisions.md
│   ├── 03-repository-structure.md
│   ├── 04-mvp-feature-breakdown.md
│   ├── 05-development-plan.md         # 7-day plan (Day 0 marked done here in status table)
│   ├── 06-demo-modes-and-providers.md # DEMO MODE + provider abstraction spec
│   └── SESSION_HANDOFF.md             # THIS FILE
│
├── scripts\
│   └── verify_setup.py               # Day-0 env/API verification (run from repo root)
│
├── backend\
│   ├── requirements.txt              # fastapi, uvicorn[standard], anthropic, httpx, python-dotenv
│   ├── .env.example                  # copy to .env (all keys optional)
│   ├── README.md                     # backend setup + API-access instructions
│   ├── run.sh                        # uvicorn launcher (bash)
│   └── app\
│       ├── __init__.py
│       ├── main.py                   # FastAPI app + /ws loop + /health
│       ├── config.py                 # DemoMode enum + Settings (env-driven)
│       ├── events.py                 # event protocol builders (Python side)
│       ├── session.py                # per-connection conversation state
│       ├── providers\
│       │   ├── __init__.py
│       │   ├── base.py               # LLMProvider / TTSProvider Protocols + Message
│       │   ├── factory.py            # build_llm() / build_tts() / describe()
│       │   ├── llm_claude.py         # ClaudeLLM (AsyncAnthropic, streamed)
│       │   ├── llm_mock.py           # MockLLM (no key)
│       │   ├── llm_scripted.py       # ScriptedLLM (PRESENTATION, keyword match)
│       │   ├── tts_browser.py        # BrowserTTS (engine="browser")
│       │   └── tts_elevenlabs.py     # ElevenLabsTTS (engine="server_audio", httpx)
│       └── cache\
│           └── demo_responses.json   # scripted lecture answers (used by ScriptedLLM)
│
└── frontend\
    ├── package.json                  # react, react-dom, framer-motion, vite, tailwind, ts
    ├── vite.config.ts
    ├── tsconfig.json / tsconfig.node.json
    ├── tailwind.config.ts / postcss.config.js
    ├── index.html
    └── src\
        ├── main.tsx
        ├── App.tsx                   # the whole Day-0/1 UI (orb, chat, status, input)
        ├── config.ts                 # WS_URL (override via VITE_EDEN_WS)
        ├── vite-env.d.ts
        ├── styles\globals.css        # Tailwind + .glass utility
        └── lib\
            ├── events.ts             # TS mirror of backend events.py — KEEP IN SYNC
            ├── socket.ts             # EdenSocket (WebSocket + auto-reconnect)
            └── audio.ts              # speakBrowser() + playAudioB64()
```

**Not yet created** (referenced in blueprint, arrive in later days): `backend/app/agents/`, `backend/app/tools/`, `backend/app/memory/`, `backend/app/builder/`, `backend/app/voice/clips/`, frontend `features/` split (currently everything lives in `App.tsx`).

---

## 5. How to run the project

### Backend (from `D:\EDEN`)
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate                 # PowerShell
pip install -r requirements.txt
# optional: copy .env.example to .env and add keys
uvicorn app.main:app --reload          # serves http://localhost:8000, ws at /ws
```
Health check: open `http://localhost:8000/health` → `{"status":"ok","mode":"SAFE","llm":...,"tts":...}`.

### Frontend (separate terminal, from `D:\EDEN`)
```powershell
cd frontend
npm install
npm run dev                            # serves http://localhost:5173
```
Open `http://localhost:5173`, type a message, hit Send. With no keys you get the mock reply + browser voice.

### Day-0 verification (from `D:\EDEN`)
```powershell
python scripts\verify_setup.py         # status only
python scripts\verify_setup.py --live  # also pings present providers
```
Exit code: `0` if required deps present, `1` if a required dep (e.g. `anthropic`) is missing. Missing *keys* never cause a non-zero exit.

---

## 6. Current provider configuration

Providers are chosen at backend startup by `backend/app/providers/factory.py`:

```
LLM:
  EDEN_MODE=PRESENTATION            -> ScriptedLLM  (cache only, no network)
  has Anthropic access (see below)  -> ClaudeLLM    (model: EDEN_MODEL_VOICE, default claude-sonnet-5)
  otherwise                         -> MockLLM      (canned reply, dev not blocked)

TTS:
  mode != PRESENTATION AND voice enabled AND ELEVENLABS_API_KEY set -> ElevenLabsTTS (server audio)
  otherwise                                                         -> BrowserTTS   (browser SpeechSynthesis)
```

**"Anthropic access" = `ANTHROPIC_API_KEY` is set, OR `EDEN_ASSUME_ANTHROPIC=true`** (use the latter if you authenticate via `ant auth login` with a profile instead of a raw key — the Anthropic SDK picks the profile up automatically).

**Env vars** (`backend/.env`, all optional — see `backend/.env.example`):
| Var | Default | Effect |
|-----|---------|--------|
| `EDEN_MODE` | `SAFE` | `LIVE` / `SAFE` / `PRESENTATION` |
| `ANTHROPIC_API_KEY` | *(unset)* | enables ClaudeLLM |
| `EDEN_ASSUME_ANTHROPIC` | `false` | force ClaudeLLM via `ant` profile |
| `EDEN_MODEL_VOICE` | `claude-sonnet-5` | conversational model (low latency) |
| `EDEN_MODEL_BUILDER` | `claude-opus-4-8` | builder-agent model (Day 5) |
| `ELEVENLABS_API_KEY` | *(unset)* | enables ElevenLabsTTS |
| `ELEVENLABS_VOICE_ID` | `JBFqnCBsd6RMkjVDRZzb` | **placeholder — confirm a real voice** |
| `EDEN_VOICE_ENABLED` | `true` | set `false` to force browser voice |
| `EDEN_USER_NAME` | `Adhithyan` | used in greeting/system prompt |
| `EDEN_HOST` / `EDEN_PORT` | `0.0.0.0` / `8000` | backend bind |

**As of this handoff:** `backend/.env` exists (keys blank), so the running config is `SAFE` + `MockLLM` + `BrowserTTS`. To upgrade to real Claude: add `ANTHROPIC_API_KEY` (or `EDEN_ASSUME_ANTHROPIC=true`) to `backend/.env` and restart — no code changes needed, the factory auto-detects. See `docs/HOW-TO-SWITCH-MODES.md` for the full test sequence.

Model IDs are current as of the build: `claude-sonnet-5`, `claude-opus-4-8`, `claude-haiku-4-5`. Claude conversational turns run with `thinking: {type:"disabled"}` for latency (see `llm_claude.py`); the agent orchestrator (Day 4) should switch to adaptive thinking.

---

## 7. Remaining tasks (by day, from `docs/05`)

- **Day 2 — Voice I/O + orb:** Web Speech API STT hook (`features/voice/useSpeechInput`), push-to-talk fallback, replace placeholder orb with a Three.js/react-three-fiber audio-reactive orb. Frontend needs to send `{type:"user_message"}` from recognized speech (backend already handles it).
- **Day 3 — Boot/Wake + HUD:** black idle screen listening for wake phrase "Good afternoon" → cinematic boot (Framer Motion) → personalized greeting (pre-generate the clip). Manual-wake fallback.
- **Day 4 — Agent visualizer:** turn the Claude tool-use loop into pipeline events (`plan_started`, `tool_selected`, `tool_result`, `validation`) in a new `agents/orchestrator.py`; add `tools/` registry; build `features/agents/AgentPipeline.tsx`. **This requires new event types — add to both `events.py` and `events.ts`.**
- **Day 5 — Software builder:** `builder/sandbox.py` + React SPA template + whitelisted app types + validation gate + prebuilt fallback; `features/builder/BuilderStage.tsx`.
- **Day 6 — Lecture assistant + reliability:** curate `memory/knowledge.py`; wire cached responses into SAFE mode on LLM error; pre-generate signature audio clips; finalize `SAFE`/`PRESENTATION` fallback ladders and error handling.
- **Day 7 — Rehearsal + P2 polish** (system status realism, SFX). Present in `SAFE` mode; `PRESENTATION` ready as parachute.

---

## 8. Next recommended implementation step

### Immediate: verify Claude LIVE mode (blocker before Day 2)

This is a hard prerequisite. Do it first, before writing any Day 2 code.

```powershell
# 1. Add your key to backend/.env:
#    ANTHROPIC_API_KEY=sk-ant-...
#    (or EDEN_ASSUME_ANTHROPIC=true if authenticated via Claude Code)

# 2. Static check — should now show "llm=Claude" for LIVE/SAFE:
python scripts\verify_setup.py

# 3. Live streaming test — must print "Anthropic stream OK -> model replied: 'READY'":
python scripts\verify_setup.py --live

# 4. Start backend and hit the diagnose endpoint:
cd backend && uvicorn app.main:app --reload
# In browser: http://localhost:8000/diagnose
# Expect: {"llm_ok": true, "llm_sample": "READY...", ...}

# 5. Full browser test: open http://localhost:5173, type "Hello EDEN", confirm
#    the orb transitions idle -> thinking -> speaking and a real Claude reply streams in.
```

Only after step 5 passes is the "brain" validated. Then:

### After LIVE verification: start Day 2 (voice input + Three.js orb)

1. Add `frontend/src/features/voice/useSpeechInput.ts` using `webkitSpeechRecognition` — on a final transcript, call the same path the text input uses (`socket.send({type:"user_message", text})`). Add a mic button + push-to-talk (spacebar) fallback.
2. Set `state` to `listening` while the mic is active (frontend-local).
3. Replace the placeholder `Orb` in `App.tsx` with `features/avatar/AvatarOrb.tsx` (react-three-fiber). Drive it from `state` and audio amplitude (`lib/audio.ts` can expose an analyser node).
4. **Test in Chrome** — Web Speech API is Chrome-only (see §9).

---

## 9. Known issues & risks

- **LIVE mode not yet end-to-end verified (blocker).** No Anthropic API key was present in either session so far. `ClaudeLLM` code is complete and hardened, but the path `User Input → Claude → Event Stream → Frontend → Voice` has only been confirmed with `MockLLM`. Run the verification sequence in §8 before starting Day 2. **This is the only true blocker** — everything else degrades gracefully.
- **Dependency install location (Day 0 verification):** during verification, `anthropic` was `pip install`ed into the machine's global Python 3.11 (fastapi/uvicorn/httpx were already global). **Recommended:** create `backend/.venv` and `pip install -r requirements.txt` there for a clean, reproducible env, as the README instructs. Nothing is broken; this is hygiene.
- **`ELEVENLABS_VOICE_ID` default is a placeholder.** Before enabling ElevenLabs, confirm a real voice ID from the ElevenLabs account. TTS failures already fall back to browser voice per turn, so a bad ID degrades gracefully rather than crashing.
- **Web Speech API is Chrome-only** (`webkitSpeechRecognition`). The demo must run in Chrome. This is why the text input + push-to-talk fallback (Day 2) matters.
- **`LIVE` vs `SAFE` provider selection is currently identical.** By design for now — the meaningful SAFE-mode differences (cached-response fallback on LLM error, prebuilt builder) land in Days 5–6. Don't be surprised they resolve the same providers today.
- **`run.sh` is bash.** On Windows use `uvicorn app.main:app --reload` directly (PowerShell) or run `run.sh` in Git Bash.
- **Windows console shows `�` for non-ASCII** in some tool output (cp1252 rendering of UTF-8 em-dashes). Cosmetic only — the browser renders UTF-8 correctly. Scripts and mock text were switched to ASCII to avoid confusion.
- **CORS is `allow_origins=["*"]`** — fine for a laptop-local demo; do not expose this backend publicly.
- **No automated tests yet.** Verification so far is manual (compile + smoke test + live browser). Consider a lightweight pytest for the WebSocket loop if the builder/agent logic grows.
- **Reliability layers are scaffolded, not fully wired.** `demo_responses.json` exists and `ScriptedLLM` uses it, but cached-response-on-error (SAFE mode) and prebuilt-build fallback are Day 5–6 work. `PRESENTATION` mode already works (scripted + browser, zero network).
- **Secrets:** keys live only in `backend/.env` (gitignored) and never reach the browser. Keep it that way.

---

*Keep this file current: at the end of each session, update §1, §4, §7, and §8 so the next session starts cold with zero context loss.*
