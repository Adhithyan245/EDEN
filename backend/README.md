# EDEN Backend

Python · FastAPI · WebSocket event stream. Talks to LLM and voice vendors only
through the provider abstraction, and runs in one of three **DEMO MODEs**
(`LIVE` / `SAFE` / `PRESENTATION`). See [`docs/06-demo-modes-and-providers.md`](../docs/06-demo-modes-and-providers.md).

## Setup

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # optional — defaults run with no keys
```

## Verify the environment (Day 0)

From the repo root:

```bash
python scripts/verify_setup.py          # status only
python scripts/verify_setup.py --live   # also ping present providers
```

This reports which providers each mode will use and prints setup instructions
for anything missing. **Missing optional keys are not errors** — EDEN falls
back to a mock LLM and browser voice, so you can build and demo the full flow
with zero credentials.

## API access

EDEN needs **none** of these to run, but each unlocks a higher-fidelity layer:

### Anthropic (Claude) — reasoning
Either:
- Set `ANTHROPIC_API_KEY` in `.env` (get a key from the Anthropic Console), **or**
- If you use `ant auth login` (a profile, no key), set `EDEN_ASSUME_ANTHROPIC=true`
  in `.env` — the Anthropic SDK picks up the profile automatically.

Without either, reasoning uses the **mock LLM** (development is not blocked).

### ElevenLabs (voice) — optional premium layer
- Set `ELEVENLABS_API_KEY` (and optionally `ELEVENLABS_VOICE_ID`) in `.env`.

Without it, EDEN speaks via the browser's built-in **SpeechSynthesis**.

## Run

```bash
./run.sh
# or:
uvicorn app.main:app --reload
```

- Health: `GET http://localhost:8000/health`
- WebSocket: `ws://localhost:8000/ws`

## Structure

```
app/
├── main.py            # FastAPI app + /ws event loop
├── config.py          # DEMO MODE + credential-aware settings
├── events.py          # the event protocol (mirrors frontend/src/lib/events.ts)
├── session.py         # per-connection conversation state
├── providers/         # LLM + TTS abstraction and implementations
│   ├── base.py        #   interfaces
│   ├── factory.py     #   mode + availability -> concrete providers
│   ├── llm_claude.py / llm_mock.py / llm_scripted.py
│   └── tts_elevenlabs.py / tts_browser.py
└── cache/
    └── demo_responses.json   # scripted answers (SAFE/PRESENTATION)
```
