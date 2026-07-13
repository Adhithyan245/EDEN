"""The EDEN event protocol.

The backend never returns a single answer — it streams a sequence of typed
events to the frontend, which renders each one. This module is the single
source of truth for event shapes on the Python side; `frontend/src/lib/events.ts`
mirrors it on the TypeScript side.
"""

from __future__ import annotations

from typing import Any


# EDEN's high-level states (drive the avatar + status panel).
class State:
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


def event(type_: str, **data: Any) -> dict[str, Any]:
    """Build an event payload for the wire."""
    return {"type": type_, **data}


# Convenience builders for the events used so far. More are added as features land.
def ready(mode: str, llm: str, tts: str, user_name: str) -> dict[str, Any]:
    return event("ready", mode=mode, llm=llm, tts=tts, user_name=user_name)


def state(name: str) -> dict[str, Any]:
    return event("state", state=name)


def token(text: str) -> dict[str, Any]:
    return event("token", text=text)


def reply_done(text: str) -> dict[str, Any]:
    return event("reply_done", text=text)


def speak(text: str) -> dict[str, Any]:
    """Ask the browser to voice `text` with its built-in SpeechSynthesis."""
    return event("speak", text=text)


def speech_audio(audio_b64: str, mime: str = "audio/mpeg") -> dict[str, Any]:
    """Server-generated audio (e.g. ElevenLabs) for the browser to play."""
    return event("speech_audio", audio_b64=audio_b64, mime=mime)


def error(message: str) -> dict[str, Any]:
    return event("error", message=message)


def pong() -> dict[str, Any]:
    return event("pong")
