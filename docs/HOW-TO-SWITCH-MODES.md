# EDEN — Mode Switching Reference

Quick guide for switching EDEN between its three runtime modes and connecting real API keys.

---

## The three modes at a glance

| Mode | LLM | TTS | External calls | Use for |
|------|-----|-----|----------------|---------|
| `SAFE` | Claude if key, else Mock | Browser (ElevenLabs only if explicitly enabled) | Optional | **The actual lecture** |
| `LIVE` | Claude (requires key) | ElevenLabs if key, else Browser | Required | Rehearsal, ideal conditions |
| `PRESENTATION` | Scripted (cache only) | Browser | **None** | Emergency parachute (network dead) |

---

## 1. Set up your API key

Edit `backend/.env` (created from `.env.example`):

```env
# Option A — direct API key (get from console.anthropic.com)
ANTHROPIC_API_KEY=sk-ant-...

# Option B — you're already authenticated via Claude Code / `claude` CLI
# The Anthropic SDK picks up the token automatically.
EDEN_ASSUME_ANTHROPIC=true
```

Then restart the backend. Run `python scripts/verify_setup.py` to confirm detection.

---

## 2. Switch modes

Edit `EDEN_MODE` in `backend/.env`:

```env
EDEN_MODE=SAFE          # recommended default — real Claude, browser voice
EDEN_MODE=LIVE          # real Claude + ElevenLabs (if key present)
EDEN_MODE=PRESENTATION  # fully scripted, zero network, emergency use only
```

The change takes effect on backend restart (no frontend rebuild needed).

---

## 3. Verify the active providers

**Static check (no network):**
```powershell
python scripts\verify_setup.py
```

**Live connectivity test (fires a real streaming call):**
```powershell
python scripts\verify_setup.py --live
```

**In-browser JSON check (backend must be running):**
```
http://localhost:8000/health     # mode + resolved provider names
http://localhost:8000/diagnose   # fires a test stream; shows llm_ok + first reply
```

A successful Claude live check looks like:
```
[ OK ] Anthropic stream OK  -> model replied: 'READY'
```

---

## 4. Provider selection logic (auto-detected at startup)

```
EDEN_MODE=PRESENTATION              -> ScriptedLLM  (always, no network)
ANTHROPIC_API_KEY set
  OR EDEN_ASSUME_ANTHROPIC=true     -> ClaudeLLM    (with graceful fallback to Mock on init error)
(neither)                           -> MockLLM      (dev never blocked)

ELEVENLABS_API_KEY set
  AND mode != PRESENTATION
  AND EDEN_VOICE_ENABLED=true       -> ElevenLabsTTS
(otherwise)                         -> BrowserTTS   (always available)
```

No code changes are needed to switch providers — only `.env` values.

---

## 5. Fallback ladder (what degrades gracefully)

| Failure | LIVE | SAFE | PRESENTATION |
|---------|------|------|--------------|
| No Anthropic key | → Mock (warning) | → Mock (warning) | N/A (scripted) |
| Claude API error mid-turn | → canned reply | → canned reply | N/A |
| ElevenLabs API error mid-turn | → browser TTS | → browser TTS | N/A |
| Full network loss | all API calls fail → see above | all API calls fail → see above | **unaffected** |

---

## 6. Quick test sequence (with a real key)

1. Add `ANTHROPIC_API_KEY=sk-ant-...` (or `EDEN_ASSUME_ANTHROPIC=true`) to `backend/.env`.
2. `cd backend && uvicorn app.main:app --reload`
3. Open `http://localhost:8000/diagnose` — expect `"llm_ok": true, "llm_sample": "READY..."`.
4. Open `http://localhost:5173`, type "Hello EDEN", hit Send.
5. Watch the orb transition: idle → thinking → speaking, and hear browser TTS reply.

---

*Full provider spec: `docs/06-demo-modes-and-providers.md`. Runtime env vars: `backend/.env.example`.*
