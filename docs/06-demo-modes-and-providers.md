# EDEN — Demo Modes & Provider Abstraction

This document formalizes two cross-cutting requirements that govern the whole build:

1. **DEMO MODE** — a three-level reliability contract so the live lecture never fails because of network/API issues.
2. **Provider abstraction** — EDEN never depends on a *specific* vendor being available. LLM and voice are pluggable behind interfaces, with always-available fallbacks.

Both are **hard requirements**, not optional polish.

---

## 1. DEMO MODE

EDEN runs in exactly one of three modes, chosen at startup via the `EDEN_MODE` env var (default `SAFE`). Mode is surfaced in the UI's system-status panel so the presenter always knows which mode is live.

| Mode | Reasoning | Voice | Tools / Builder | External APIs | Use for |
|------|-----------|-------|-----------------|---------------|---------|
| **LIVE** | Real Gemini, streamed | ElevenLabs if available, else browser | Real generation | Required (falls back per-call on error) | Rehearsal, ideal conditions |
| **SAFE** | Real Gemini if available, else mock | **Browser TTS by default** (ElevenLabs only if explicitly enabled) | Real, with cached/prebuilt fallback on failure | Optional — degrades gracefully | **The actual lecture (recommended default)** |
| **PRESENTATION** | Fully scripted responses, **no external calls** | Browser TTS (or pre-generated clips) | Prebuilt/replayed only | **None** | Emergency parachute if the venue network dies |

### Guarantees per mode
- **LIVE** — best quality; every live call still has a per-call fallback so a single API hiccup degrades that turn rather than crashing.
- **SAFE** — the presenter can *interact for real* (real Claude answers, real builder attempts), but nothing is *required* to be online: STT→text, TTS→browser, live-builder→prebuilt, LLM-error→cached response all kick in automatically.
- **PRESENTATION** — deterministic. Zero external dependencies. The signature moments (boot greeting, key Q&A, the builder demo) play from cached text/audio/prebuilt assets. Used only when connectivity is gone.

### The rule
> The live lecture must never fail because of network or API availability. Every critical moment has a scripted, offline-safe path reachable via PRESENTATION mode, and SAFE mode degrades each capability independently so one failure never cascades.

### Mode resolution at startup
`config.py` reads `EDEN_MODE`, then the provider factory selects concrete providers based on **mode + credential availability**:

```
EDEN_MODE=LIVE          + Gemini key present     → GeminiLLM
EDEN_MODE=LIVE/SAFE     + no Gemini key          → MockLLM (logs a warning)   ← dev never blocks
EDEN_MODE=PRESENTATION  (any)                    → ScriptedLLM (cache only)

ELEVENLABS key present + mode != PRESENTATION + voice enabled → ElevenLabsTTS
otherwise                                                     → BrowserTTS
```

Development is **never blocked** on external keys: with no credentials at all, EDEN runs end-to-end on `MockLLM` + `BrowserTTS`.

---

## 2. Provider Abstraction

EDEN talks to two kinds of external capability — **reasoning (LLM)** and **voice (TTS)** — only through interfaces. Concrete providers are chosen at runtime. This means:
- No vendor lock-in; swapping Claude→another LLM or ElevenLabs→another TTS is a one-file change.
- Development proceeds with mock/browser providers before any key is confirmed.
- The fallback ladder is just "pick a different provider."

### 2.1 LLM provider interface

```python
class LLMProvider(Protocol):
    name: str
    async def stream_reply(
        self, messages: list[Message], system: str, *, model: str | None = None
    ) -> AsyncIterator[str]:
        """Yield response text deltas."""
```

| Implementation | When used | Notes |
|----------------|-----------|-------|
| `GeminiLLM` | LIVE / SAFE with key | Google Gemini SDK, streamed. gemini-2.5-flash for voice turns, gemini-2.5-pro for the builder agent. |
| `ScriptedLLM` | PRESENTATION | Returns cached responses keyed by intent; streams them word-by-word for realism. |
| `MockLLM` | Dev / no key | Canned but plausible replies so the whole app runs offline. |

Provider selection lives in `providers/factory.py`. The rest of the app (orchestrator, session) only sees `LLMProvider`.

### 2.2 TTS provider interface

```python
class TTSProvider(Protocol):
    name: str
    engine: Literal["server_audio", "browser"]
    async def synthesize(self, text: str) -> bytes | None:
        """Return audio bytes (server_audio), or None to delegate to the browser."""
```

| Implementation | `engine` | When used | Fallback trigger |
|----------------|----------|-----------|------------------|
| `ElevenLabsTTS` | `server_audio` | key present, not PRESENTATION, voice enabled | on API error → BrowserTTS for that turn |
| `BrowserTTS` | `browser` | default everywhere else | always available (uses browser `SpeechSynthesis`) |

**ElevenLabs is strictly an optional premium layer.** With no ElevenLabs key, EDEN speaks via the browser's built-in `SpeechSynthesis` — the frontend receives a `speak` event and voices it locally. When the key is present and the turn succeeds, EDEN emits a `speech_audio` event carrying ElevenLabs audio. Either way the avatar reacts to amplitude.

### 2.3 How TTS reaches the browser

| Provider | Backend emits | Frontend does |
|----------|---------------|---------------|
| `ElevenLabsTTS` | `speech_audio` `{ audio_b64, mime }` | plays the audio; orb reacts to amplitude |
| `BrowserTTS` | `speak` `{ text }` | `window.speechSynthesis.speak(...)`; orb reacts to synthesis boundaries |

---

## 3. Impact on the repository

New/confirmed pieces (added to [structure](03-repository-structure.md)):

```
backend/app/
├── config.py                 # EDEN_MODE + credential-aware settings
├── providers/
│   ├── base.py               # LLMProvider / TTSProvider interfaces
│   ├── factory.py            # mode + availability → concrete providers
│   ├── llm_claude.py         # ClaudeLLM
│   ├── llm_scripted.py       # ScriptedLLM (PRESENTATION)
│   ├── llm_mock.py           # MockLLM (dev / no key)
│   ├── tts_elevenlabs.py     # ElevenLabsTTS (optional premium)
│   └── tts_browser.py        # BrowserTTS (default fallback)
└── cache/
    └── demo_responses.json   # scripted responses for SAFE/PRESENTATION
scripts/
└── verify_setup.py           # Day-0 API/credential verification
```

---

## 4. Day-0 API setup verification (requirement)

`scripts/verify_setup.py` is the first thing run. It reports — clearly and non-fatally — what's available, so the presenter knows which mode is realistic without blocking development:

- Python dependencies importable? ✅/❌
- `ANTHROPIC_API_KEY` present? (or an `ant` login profile detected?) → LLM = Claude vs Mock
- `ELEVENLABS_API_KEY` present? → Voice = ElevenLabs vs Browser
- Optional `--live` flag: makes one minimal real call to each present provider to confirm the key actually works.
- Prints the resolved provider set for each DEMO MODE and setup instructions for anything missing.

It **never exits non-zero for missing optional keys** — a missing key is a downgrade, not an error. See the [setup instructions in the README](../backend/README.md) and updated [Day 0 plan](05-development-plan.md#day-0).

---

*This document is authoritative for DEMO MODE and provider selection. Where it overlaps with [Architecture §5/§7](01-architecture.md), this document wins.*
