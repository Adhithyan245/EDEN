"""Shared utilities used by both the conversational pipeline and the agent subsystem."""

from __future__ import annotations

import json
from typing import Any

from .prompts.eden_personality import EMOTION_VALUES


def extract_json(raw: str) -> Any:
    """Parse the first top-level JSON object from an LLM response.

    Tolerates two things models occasionally do even in JSON mode:
      - leading prose or code fences before the object, and
      - trailing content after it (which plain ``json.loads`` rejects with
        "Extra data").

    Skips to the first ``{`` and uses ``raw_decode`` so trailing bytes are
    ignored. Raises ``ValueError`` if no JSON object is present.
    """
    s = raw.strip()
    start = s.find("{")
    if start == -1:
        raise ValueError("no JSON object found in response")
    obj, _ = json.JSONDecoder().raw_decode(s[start:])
    return obj


def parse_llm_response(raw: str) -> tuple[str, str]:
    """Extract (emotion, spoken_text) from a JSON LLM response.

    The personality prompt instructs the model to always return:
        {"emotion": "<name>", "response": "<spoken text>"}

    Falls back to ("idle", raw) if the JSON cannot be parsed — this protects
    the pipeline when the mock or scripted provider returns plain text, or when
    the model occasionally produces malformed output.
    """
    try:
        data = extract_json(raw)
        emotion = data.get("emotion", "idle")
        if emotion not in EMOTION_VALUES:
            emotion = "idle"
        spoken = str(data.get("response", "")).strip()
        return emotion, spoken or raw
    except (json.JSONDecodeError, AttributeError, ValueError):
        return "idle", raw
