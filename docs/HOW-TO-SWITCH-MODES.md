# EDEN — Mode Switching Reference

Quick guide for switching EDEN between its three runtime modes and connecting real API keys.

---

## The three modes at a glance

| Mode | LLM | TTS | External calls | Use for |
|------|-----|-----|----------------|---------|
| `SAFE` | Gemini if key, else Mock | Browser (ElevenLabs only if explicitly enabled) | Optional | **The actual lecture** |
| `LIVE` | Gemini (requires key) | ElevenLabs if key, else Browser | Required | Rehearsal, ideal conditions |
| `PRESENTATION` | Scripted (cache only) | Browser | **None** | Emergency parachute (network dead) |

---

## 1. Set up your API key

Edit `backend/.env` (created from `.env.example`):

```env
# Get your free key at https://aistudio.google.com/apikey
GEMINI_API_KEY=AIza...
```

Then restart the backend. Run `python scripts/verify_setup.py` to confirm detection.

---

## 2. Switch modes

Edit `EDEN_MODE` in `backend/.env`:

```env
EDEN_MODE=SAFE          # recommended default — real Gemini, browser voice
EDEN_MODE=LIVE          # real Gemini + ElevenLabs (if key present)
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

A successful Gemini live check looks like:
```
[ OK ] EDEN_MODEL_VOICE=gemini-2.5-flash (voice) — available
[ OK ] EDEN_MODEL_BUILDER=gemini-2.5-pro (builder) — available
[ OK ] Gemini stream OK  model='gemini-2.5-flash'  replied: 'READY'
```

To list every model available to your key:
```powershell
python scripts\verify_setup.py --models
```

**Verified model IDs (confirmed by live probe on 2026-07-14):**
| Env var | Value | TTFT | Notes |
|---------|-------|------|-------|
| `EDEN_MODEL_VOICE` | `gemini-3.1-flash-lite` | 0.66 s | Only sub-second model on the free API tier |
| `EDEN_MODEL_BUILDER` | `gemini-3.1-flash-lite` | 0.66 s | Default; upgrade to `gemini-2.5-pro` on a paid plan |

`gemini-2.5-flash` / `gemini-2.5-flash-lite` are blocked for new API key users (404). All pro models require a paid plan (free tier quota = 0 RPM). `gemini-3.5-flash` is a thinking model with 10–20 s TTFT — unsuitable for voice.

---

## 4. Provider selection logic (auto-detected at startup)

```
EDEN_MODE=PRESENTATION          -> ScriptedLLM  (always, no network)
GEMINI_API_KEY set              -> GeminiLLM    (with graceful fallback to Mock on init error)
(neither)                       -> MockLLM      (dev never blocked)

ELEVENLABS_API_KEY set
  AND mode != PRESENTATION
  AND EDEN_VOICE_ENABLED=true   -> ElevenLabsTTS
(otherwise)                     -> BrowserTTS   (always available)
```

No code changes are needed to switch providers — only `.env` values.

---

## 5. Fallback ladder (what degrades gracefully)

| Failure | LIVE | SAFE | PRESENTATION |
|---------|------|------|--------------|
| No Gemini key | → Mock (warning) | → Mock (warning) | N/A (scripted) |
| Gemini API error mid-turn | → canned reply | → canned reply | N/A |
| ElevenLabs API error mid-turn | → browser TTS | → browser TTS | N/A |
| Full network loss | all API calls fail → see above | all API calls fail → see above | **unaffected** |

---

## 6. Quick test sequence (with a real key)

1. Add `GEMINI_API_KEY=AIza...` to `backend/.env`.
2. `cd backend && uvicorn app.main:app --reload`
3. Open `http://localhost:8000/diagnose` — expect `"llm_ok": true, "llm_sample": "READY..."`.
4. Open `http://localhost:5173`, type "Hello EDEN", hit Send.
5. Watch the orb transition: idle → thinking → speaking, and hear browser TTS reply.

---

*Full provider spec: `docs/06-demo-modes-and-providers.md`. Runtime env vars: `backend/.env.example`.*
