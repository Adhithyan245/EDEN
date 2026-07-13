"""Browser TTS provider — the always-available default voice.

Produces no server audio; instead the backend emits a `speak` event and the
frontend voices it with the browser's built-in SpeechSynthesis. Requires no
credentials and never fails to be available.
"""

from __future__ import annotations

from typing import Optional


class BrowserTTS:
    name = "browser"
    engine = "browser"

    async def synthesize(self, text: str) -> Optional[bytes]:
        return None  # delegate speech to the browser
