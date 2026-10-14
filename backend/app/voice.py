"""Shared TTS delivery helper.

Extracted from main.py so both the conversational pipeline and the agent
orchestrator can speak through the same code path without duplication.
"""

from __future__ import annotations

import base64
import logging

from fastapi import WebSocket

from . import events
from .providers.base import TTSProvider

log = logging.getLogger("eden.voice")


async def speak(websocket: WebSocket, tts: TTSProvider, text: str) -> None:
    """Voice ``text`` via the selected TTS provider, falling back to the browser.

    Emits ``speech_audio`` (ElevenLabs path) or ``speak`` (browser path).
    Silently falls back to browser voice on any TTS failure so the pipeline
    is never blocked by a single failed synthesis call.
    """
    if getattr(tts, "engine", "browser") == "browser":
        await websocket.send_json(events.speak(text))
        return
    try:
        audio = await tts.synthesize(text)
        if audio:
            b64 = base64.b64encode(audio).decode("ascii")
            await websocket.send_json(events.speech_audio(b64))
        else:
            await websocket.send_json(events.speak(text))
    except Exception as exc:  # noqa: BLE001
        log.warning("TTS failed (%s); falling back to browser voice", exc)
        await websocket.send_json(events.speak(text))
