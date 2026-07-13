# EDEN — Repository Structure

The layout follows the modules named in the brief (`frontend/ backend/ agents/ voice/ avatar/ tools/ memory/ docs/`) mapped onto a clean, buildable project. Backend capability modules live **inside** `backend/` as packages (so Python imports work and there's one runnable service); the frontend mirrors the same capability names as feature folders. This keeps the conceptual modularity the brief asks for without splitting the app into hard-to-run pieces.

```
EDEN/
├── README.md                     # What EDEN is + how to run it
├── .gitignore
│
├── docs/                         # ← the blueprint (this deliverable)
│   ├── 01-architecture.md
│   ├── 02-technology-decisions.md
│   ├── 03-repository-structure.md
│   ├── 04-mvp-feature-breakdown.md
│   └── 05-development-plan.md
│
├── backend/                      # Python · FastAPI orchestration service
│   ├── requirements.txt
│   ├── .env.example              # ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, EDEN_MODE=...
│   ├── run.sh                    # uvicorn app.main:app --reload
│   └── app/
│       ├── main.py               # FastAPI app + WebSocket endpoint + CORS
│       ├── config.py             # env, runtime mode (LIVE/SAFE/PRESENTATION)
│       ├── events.py             # typed event schema (Pydantic) — the protocol
│       ├── session.py            # per-connection session + conversation state
│       │
│       ├── agents/               # ── agent orchestration (the core) ──
│       │   ├── orchestrator.py   # Claude tool-use loop → emits UI events
│       │   ├── prompts.py        # system prompts / personas per role
│       │   └── pipeline.py       # plan→select→execute→validate→respond mapping
│       │
│       ├── voice/                # ── text-to-speech ──
│       │   ├── tts.py            # ElevenLabs streaming client
│       │   ├── fallback.py       # cached-clip + browser-synth signalling
│       │   └── clips/            # pre-generated audio for scripted lines
│       │
│       ├── tools/                # ── agent tools registry ──
│       │   ├── registry.py       # tool definitions + dispatch
│       │   ├── lecture.py        # answer/explain from knowledge base
│       │   ├── builder.py        # app-builder tool actions
│       │   └── system.py         # status/system-info tools
│       │
│       ├── memory/               # ── memory ──
│       │   ├── conversation.py   # session conversation history
│       │   └── knowledge.py      # curated lecture knowledge base loader
│       │
│       ├── builder/              # ── AI software builder sandbox ──
│       │   ├── sandbox.py        # isolated workdir, write/validate/run
│       │   ├── templates/        # whitelisted app scaffolds (React SPA)
│       │   │   └── react-spa/
│       │   └── prebuilt/         # known-good fallback builds per app type
│       │
│       └── cache/                # ── reliability layer ──
│           └── demo_responses.json  # cached answers for scripted moments
│
├── frontend/                     # React + TypeScript + Vite
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx               # mode router: boot → interface
│       ├── config.ts             # WS url, feature flags
│       │
│       ├── lib/
│       │   ├── socket.ts         # WebSocket client + event dispatch
│       │   ├── events.ts         # TS event types (mirror of backend events.py)
│       │   └── audio.ts          # TTS playback + amplitude analyser
│       │
│       ├── state/
│       │   └── edenStore.ts      # global state (mode, messages, agent steps)
│       │
│       ├── features/
│       │   ├── boot/             # ── wake + cinematic boot sequence ──
│       │   │   └── BootSequence.tsx
│       │   ├── avatar/           # ── reactive AI core (Three.js) ──
│       │   │   ├── AvatarOrb.tsx
│       │   │   └── orb.shader.ts
│       │   ├── hud/              # ── glassmorphism interface shell ──
│       │   │   ├── Interface.tsx
│       │   │   ├── ConversationPanel.tsx
│       │   │   └── SystemStatus.tsx
│       │   ├── agents/           # ── agent activity visualizer ──
│       │   │   └── AgentPipeline.tsx
│       │   ├── voice/            # ── speech input ──
│       │   │   ├── useSpeechInput.ts   # Web Speech API + wake phrase
│       │   │   └── PushToTalk.tsx      # fallback control
│       │   └── builder/          # ── software builder view ──
│       │       └── BuilderStage.tsx    # file tree + code + preview
│       │
│       └── styles/
│           └── globals.css       # Tailwind + glass utilities
│
└── scripts/
    ├── pregenerate_clips.py      # render scripted lines via ElevenLabs → clips/
    └── seed_prebuilt.sh          # build the fallback app(s) into prebuilt/
```

---

## Notes on the mapping

- **The brief's module names are all present.** `agents/ voice/ tools/ memory/ avatar/` appear as backend packages and/or frontend features. `frontend/ backend/ docs/` are top-level as specified.
- **`avatar/` is a frontend concern** (it's a rendered visual), so it lives under `frontend/src/features/avatar/`. Everything cognitive (`agents`, `tools`, `memory`, `voice`) is backend.
- **One protocol, two sides:** `backend/app/events.py` (Pydantic) and `frontend/src/lib/events.ts` (TypeScript) are deliberate mirrors — the single source of truth for the event contract described in the architecture doc.
- **Reliability is a first-class folder:** `backend/app/cache/`, `voice/clips/`, and `builder/prebuilt/` hold the pre-generated assets that power the fallback modes.
- **`scripts/`** holds one-off prep tasks (rendering audio clips, seeding the fallback build) run before demo day, not at runtime.

## Runtime shape

- **Two processes**, each started with one command: `uvicorn` (backend, default `:8000`) and `vite` (frontend, default `:5173`). The frontend opens a WebSocket to the backend.
- **No build/deploy pipeline** for the MVP — it runs on the presenter's laptop (see [Technology Decisions §10](02-technology-decisions.md)).

See next: [MVP Feature Breakdown](04-mvp-feature-breakdown.md).
