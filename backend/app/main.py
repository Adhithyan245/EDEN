"""EDEN backend entrypoint: FastAPI app + the WebSocket event stream.

Day-0/1 scope: a working conversation spine. A client connects over WebSocket,
sends a user message, and EDEN streams back reasoning state, response tokens,
and speech — using whichever providers the factory selected for the current
DEMO MODE. It runs end-to-end with zero credentials (mock LLM + browser TTS).
"""

from __future__ import annotations

import base64
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import events
from .config import settings
from .providers import factory
from .session import Session

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("eden")

app = FastAPI(title="EDEN", version="0.1.0")

# The frontend runs on the Vite dev server; allow it (and anything, since this
# is a laptop-local demo, not a public service).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Providers are chosen once at startup from mode + credential availability.
LLM = factory.build_llm()
TTS = factory.build_tts()

SYSTEM_PROMPT = (
    "You are EDEN (Everything Done Effortlessly, Naturally), a futuristic AI "
    "companion inspired by JARVIS and FRIDAY. You are speaking aloud, so keep "
    "replies concise, natural, and conversational — a sentence or two unless "
    f"more is truly needed. The user's name is {settings.user_name}. Be warm, "
    "calm, and precise."
)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "mode": settings.mode.value,
        "llm": LLM.name,
        "tts": TTS.name,
    }


@app.get("/diagnose")
async def diagnose() -> dict:
    """Live connectivity check for the currently selected LLM provider.

    Fires a single minimal streaming call and collects the first reply token to
    confirm the end-to-end path works.  Returns a machine-readable result with
    a human-readable ``detail`` field.  Never raises — errors are captured and
    returned in ``detail`` so the caller can display them without crashing.
    """
    result: dict = {
        "mode": settings.mode.value,
        "llm": LLM.name,
        "tts": TTS.name,
    }

    try:
        tokens: list[str] = []
        async for t in LLM.stream_reply(
            [{"role": "user", "content": "Reply with exactly the word: READY"}],
            "You are a test probe.  Follow instructions exactly.",
            model=settings.model_voice,
        ):
            tokens.append(t)
            if len(tokens) > 20:  # we only need to confirm streaming works
                break
        result["llm_ok"] = True
        result["llm_sample"] = "".join(tokens)[:120]
        result["detail"] = f"LLM ({LLM.name}) stream confirmed."
    except Exception as exc:  # noqa: BLE001
        result["llm_ok"] = False
        result["detail"] = f"LLM ({LLM.name}) failed: {exc}"

    return result


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    session = Session()
    log.info("client connected (mode=%s llm=%s tts=%s)", settings.mode.value, LLM.name, TTS.name)

    await websocket.send_json(
        events.ready(settings.mode.value, LLM.name, TTS.name, settings.user_name or "")
    )

    try:
        while True:
            msg = await websocket.receive_json()
            kind = msg.get("type")

            if kind == "ping":
                await websocket.send_json(events.pong())
                continue

            if kind == "user_message":
                await _handle_user_message(websocket, session, str(msg.get("text", "")))
                continue

            log.warning("unknown message type: %r", kind)
    except WebSocketDisconnect:
        log.info("client disconnected")
    except Exception as exc:  # noqa: BLE001 - keep the socket loop resilient
        log.exception("websocket error")
        try:
            await websocket.send_json(events.error(str(exc)))
        except Exception:
            pass


async def _handle_user_message(websocket: WebSocket, session: Session, text: str) -> None:
    text = text.strip()
    if not text:
        return

    session.add_user(text)
    await websocket.send_json(events.state(events.State.THINKING))

    # Stream the reply.
    reply_parts: list[str] = []
    try:
        async for delta in LLM.stream_reply(session.messages, SYSTEM_PROMPT):
            reply_parts.append(delta)
            await websocket.send_json(events.token(delta))
    except Exception as exc:  # noqa: BLE001 - LLM failure degrades gracefully
        log.warning("LLM stream failed: %s", exc)
        fallback = "I'm having trouble reaching my reasoning core right now."
        reply_parts = [fallback]
        await websocket.send_json(events.token(fallback))

    reply = "".join(reply_parts).strip()
    session.add_assistant(reply)
    await websocket.send_json(events.reply_done(reply))

    # Speak it.
    await websocket.send_json(events.state(events.State.SPEAKING))
    await _speak(websocket, reply)
    await websocket.send_json(events.state(events.State.IDLE))


async def _speak(websocket: WebSocket, text: str) -> None:
    """Voice `text` via the selected TTS provider, falling back to the browser."""
    if getattr(TTS, "engine", "browser") == "browser":
        await websocket.send_json(events.speak(text))
        return
    try:
        audio = await TTS.synthesize(text)
        if audio:
            b64 = base64.b64encode(audio).decode("ascii")
            await websocket.send_json(events.speech_audio(b64))
        else:
            await websocket.send_json(events.speak(text))
    except Exception as exc:  # noqa: BLE001 - premium voice failure -> browser voice
        log.warning("TTS failed (%s); falling back to browser voice", exc)
        await websocket.send_json(events.speak(text))
