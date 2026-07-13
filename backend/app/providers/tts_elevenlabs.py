"""ElevenLabs TTS provider — the optional premium voice layer.

Only selected when an ElevenLabs key is present and voice is enabled (and not
in PRESENTATION mode). Returns MP3 bytes; on any failure the caller falls back
to browser speech for that turn, so this never breaks the demo.
"""

from __future__ import annotations

from typing import Optional

import httpx

from ..config import settings

_API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


class ElevenLabsTTS:
    name = "elevenlabs"
    engine = "server_audio"

    def __init__(self) -> None:
        self._voice_id = settings.elevenlabs_voice_id
        self._api_key = settings.elevenlabs_api_key

    async def synthesize(self, text: str) -> Optional[bytes]:
        url = _API.format(voice_id=self._voice_id)
        headers = {"xi-api-key": self._api_key or "", "content-type": "application/json"}
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.content  # MP3 audio bytes
