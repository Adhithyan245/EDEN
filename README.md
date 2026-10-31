# EDEN — *Everything Done Effortlessly, Naturally*

A futuristic AI companion inspired by JARVIS, FRIDAY, and EDITH — built as a **live demonstration of modern AI** for a Generative AI guest lecture.

🌐 **Live demo:** [eden-alpha-sable.vercel.app](https://eden-alpha-sable.vercel.app) — the backend runs on Render's free tier, so the first request after a quiet spell can take up to a minute to wake it.

EDEN is **not** a chatbot and **not** a simple LLM wrapper. It is an interactive AI system that can **listen, reason, create, and collaborate** — showcasing voice interaction, AI agents, multimodal AI, and AI-assisted software creation through a premium, cinematic HUD.

## What EDEN does
- 🎙️ **Voice interaction** — wakes on a spoken cue, holds a natural spoken conversation.
- 🧠 **Visible reasoning** — shows its agent pipeline live (plan → tools → execute → validate → respond).
- 🛠️ **AI software builder** — turns an audience-suggested app idea into running code in real time.
- 🎓 **Lecture assistant** — explains AI concepts and answers questions.
- ✨ **Cinematic interface** — dark, glassmorphic Iron Man / Vision Pro-style HUD with a reactive AI core.

## Status
✅ **Implemented and deployed** — frontend on Vercel, backend on Render (Docker). See [`docs/`](docs/) for the original architecture and plan.

## Blueprint (read in order)
1. [Architecture](docs/01-architecture.md)
2. [Technology Decisions](docs/02-technology-decisions.md)
3. [Repository Structure](docs/03-repository-structure.md)
4. [MVP Feature Breakdown](docs/04-mvp-feature-breakdown.md)
5. [7-Day Development Plan](docs/05-development-plan.md)

## Stack (summary)
- **Frontend:** React + TypeScript + Vite · Tailwind + Framer Motion · Three.js (reactive orb avatar)
- **Backend:** Python + FastAPI · WebSocket event stream
- **AI:** Claude (Sonnet 5 for voice, Opus 4.8 for the builder agent) via the Anthropic API
- **Voice:** Web Speech API (STT) · ElevenLabs (TTS)
- **Reliability:** online-first with graceful fallbacks; `LIVE` / `SAFE` / `PRESENTATION` runtime modes

## Run (once implemented)
```bash
# backend
cd backend && uvicorn app.main:app --reload
# frontend
cd frontend && npm run dev
```

*Built as a demonstration of AI as an interactive system — one that listens, reasons, creates, and collaborates.*
