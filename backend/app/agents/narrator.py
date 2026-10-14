"""Narrator — dynamic, reality-grounded spoken narration during a build.

EDEN stays alive and in character throughout the build. At each stage the
narrator calls the LLM with EDEN's full personality prompt plus a stage marker
describing exactly what is true *right now*, then delivers the result through the
normal voice pipeline (emotion → token stream → TTS).

Two guarantees:

  1. Reality. Each stage marker states the ground truth of the moment and
     forbids claiming anything that has not happened. The narrator is only ever
     invoked with a stage that matches the executor's actual progress, so EDEN
     cannot narrate imaginary events.

  2. Audience. When the session is public, a marker tells EDEN it is addressing
     a room, so it speaks to everyone rather than to one person.

Nothing here is hardcoded dialogue. The wording is generated fresh every time.
The only static text is a minimal fallback used if the LLM call itself fails —
and even that prefers per-build, model-written text when available.

Voice/display separation:

For INFORMATION_QUERY responses the narrator distinguishes between the full
display text (shown on screen) and a shorter voice summary (spoken aloud via
TTS). For all other intents the display and voice text are identical — no change
to existing behavior.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import WebSocket

from .. import events
from ..agents.intent import IntentType
from ..providers.base import LLMProvider, TTSProvider
from ..utils import parse_llm_response
from ..voice import speak as _speak

log = logging.getLogger("eden.agents.narrator")

# Approximate word count above which a separate voice summary is generated.
# Responses shorter than this are spoken in full regardless of intent.
_VOICE_SUMMARY_THRESHOLD = 60


# Each marker states what is TRUE at this moment and forbids overclaiming. Markers
# describe the situation and ask for brevity — they are NOT example lines to copy.
# The wording EDEN speaks is generated fresh from character, never from here.
#
# "generating" and "launching" below are UNUSED — no orchestrator call site
# narrates them anymore (the build pipeline goes acknowledged → installing →
# complete/failed directly; there is no separate "designing" narration point,
# and nothing launches a server to narrate). Left in place, unreachable,
# rather than rewritten or deleted, since this is prompt content (not a
# comment) and this pass changes documentation, not runtime behavior.
_STAGE_MARKERS: dict[str, str] = {
    "acknowledged": (
        "[AGENT STAGE: request-received] A build request just landed: {app_name}. Nothing "
        "exists yet. Answer with a few words — a reaction, not a plan. If the request is "
        "ambitious, you may note that in passing. Do not describe what you are about to do."
    ),
    "generating": (
        "[AGENT STAGE: designing] You are shaping {app_name} now — nothing on disk yet. A "
        "few words at most, present tense. Not a status report."
    ),
    "installing": (
        "[AGENT STAGE: installing] Dependencies are pulling in right now — a real wait, not "
        "finished. One short thought to fill it, a few words. Do not say it is done."
    ),
    "launching": (
        "[AGENT STAGE: launching] The server is coming up — not confirmed yet. A few words, "
        "present tense. Do not say it is running."
    ),
    "complete": (
        "[AGENT STAGE: verified-running] {app_name} is confirmed running in the browser — "
        "true and verified. A short line, and if it genuinely feels good, let a real flash "
        "of satisfaction show — brief, not a speech. Do not report that you built it."
    ),
    "failed": (
        "[AGENT STAGE: build-failed] It genuinely stopped: {reason}. Composed, quiet, "
        "honest — one line. No alarm, no over-apology, no logs."
    ),

    # --- Editing an already-running project ---------------------------------
    "edit_ack": (
        "[AGENT STAGE: edit-requested] A change to the running {app_name}: \"{change}\". "
        "Not done yet. A few words. Do not describe the steps."
    ),
    "editing": (
        "[AGENT STAGE: editing] Making that change now — in progress. A few words, present "
        "tense. Do not say it is done."
    ),
    "edit_complete": (
        "[AGENT STAGE: edit-verified] The change is in and {app_name} is still running — "
        "verified. A few words. It is simply updated; do not report the action."
    ),
    "edit_none": (
        "[AGENT STAGE: no-change-needed] \"{change}\" needed no change to {app_name}. One "
        "honest, short line. Do not pretend you changed anything."
    ),
    "edit_failed": (
        "[AGENT STAGE: edit-reverted] The change would not hold, so {app_name} is back as it "
        "was and still running. Composed, brief, honest — no logs."
    ),

    # --- Collaboration: clarify, suggest, undo/redo -------------------------
    "clarify": (
        "[AGENT STAGE: clarify] Before starting, ask one short question that gets at this: "
        "\"{question}\". Your own words, one line. Do not answer it yourself and do not "
        "start yet."
    ),
    "suggest": (
        "[AGENT STAGE: suggest] {app_name} is up. If one genuinely useful next step comes to "
        "mind, offer it in a few words — easy to wave off. If not, a short nod that it works "
        "is enough."
    ),
    "undo_done": (
        "[AGENT STAGE: reverted] {app_name} is back to the previous version, still running — "
        "true. A few words."
    ),
    "redo_done": (
        "[AGENT STAGE: reapplied] That change is back and {app_name} is running — true. A "
        "few words."
    ),
    "version_none": (
        "[AGENT STAGE: nothing-to-restore] Nothing further to move to for {app_name}; "
        "nothing changed. One honest, short line."
    ),

    # --- Render verification repair (UNUSED — see agents/render_verifier.py's
    # module note; no call site narrates this stage) -------------------------
    "render_repairing": (
        "[AGENT STAGE: render-fix] {app_name} came up but the page didn't render — "
        "a small problem in the generated code. A fix is in progress right now. "
        "A few words, present tense. Do not say it is fixed yet."
    ),
}

# Minimal, honest safety-net text — only used if the LLM call fails entirely.
_FALLBACKS: dict[str, tuple[str, str]] = {
    "acknowledged":     ("confident", "Starting on that now."),
    "generating":       ("thinking",  "Working through the design."),
    "installing":       ("thinking",  "Pulling in what it needs."),
    "launching":        ("thinking",  "Bringing the server up."),
    "complete":         ("happy",     "There it is."),
    "failed":           ("concerned", "That didn't come together this time."),
    "edit_ack":         ("confident", "Let me adjust that."),
    "editing":          ("thinking",  "Making the change now."),
    "edit_complete":    ("happy",     "There — it just updated."),
    "edit_none":        ("idle",      "That already holds — nothing to change there."),
    "edit_failed":      ("concerned", "That change didn't hold, so I put it back the way it was."),
    "clarify":          ("curious",   ""),
    "suggest":          ("idle",      "It's working well."),
    "render_repairing": ("thinking",  "Something small needs adjusting."),
    "undo_done":        ("confident", "Done — it's back to how it was."),
    "redo_done":        ("confident", "Brought that change back."),
    "version_none":     ("idle",      "There's nothing further to move to there."),
}

# System prompt addendum that asks for a voice summary alongside the full response.
# Injected only for INFORMATION_QUERY responses that exceed the word threshold.
_VOICE_SUMMARY_ADDENDUM = (
    "\n\nThis response will be displayed on screen AND spoken aloud. "
    "Return a JSON object with two fields:\n"
    "  \"response\": the full display answer (detailed, structured, complete)\n"
    "  \"voice_response\": a concise spoken summary — 1-3 natural sentences that "
    "capture the key insight, as a knowledgeable friend would say it aloud. "
    "No lists, no bullet points, no markdown in voice_response.\n"
    "If the response is already short, voice_response may equal response.\n"
    "Always include \"emotion\" as well."
)


async def narrate_stage(
    stage: str,
    context: dict,
    llm: LLMProvider,
    tts: TTSProvider,
    websocket: WebSocket,
    system_prompt: str,
    scope: str = "private",
    intent: Optional[IntentType] = None,
) -> str:
    """Generate and speak a narration for ``stage``. Returns the spoken text.

    ``context`` may include ``app_name``, ``reason`` (for failures), and an
    optional ``fallback`` (per-build, model-written text preferred over the
    generic safety-net if the live call fails).

    When ``intent`` is INFORMATION_QUERY, long responses are split into a full
    display text (streamed as tokens to the frontend) and a shorter voice summary
    (sent to TTS). For all other intents behavior is unchanged.
    """
    marker = _STAGE_MARKERS.get(stage)
    if not marker:
        return ""

    safe_ctx = {k: (v or "") for k, v in context.items()}
    try:
        message = marker.format(**safe_ctx)
    except KeyError:
        message = marker

    if scope == "public":
        message = (
            "[AUDIENCE: public] You are addressing a room of people, not one "
            "person. " + message
        )

    emotion, display_text, voice_text = await _generate(
        message, llm, system_prompt, stage, context, intent=intent
    )
    await _deliver(websocket, tts, emotion, display_text, voice_text)
    return voice_text


async def _generate(
    message: str,
    llm: LLMProvider,
    system_prompt: str,
    stage: str,
    context: dict,
    intent: Optional[IntentType] = None,
) -> tuple[str, str, str]:
    """Return (emotion, display_text, voice_text).

    For most intents display_text == voice_text. For INFORMATION_QUERY responses
    that exceed the word threshold, voice_text is a shorter spoken summary.
    """
    fallback_emotion, generic = _FALLBACKS.get(stage, ("idle", ""))
    fallback_text = str(context.get("fallback") or "").strip() or generic

    # Decide whether to request a voice/display split from the LLM.
    wants_split = intent == IntentType.INFORMATION_QUERY
    effective_system = system_prompt + _VOICE_SUMMARY_ADDENDUM if wants_split else system_prompt

    # Token cap: information queries get more room; build narration stays short.
    token_cap = 1200 if wants_split else 400

    try:
        raw_parts: list[str] = []
        async for chunk in llm.stream_reply(
            [{"role": "user", "content": message}],
            effective_system,
            intent=intent,
        ):
            raw_parts.append(chunk)
            if len("".join(raw_parts)) > token_cap:
                break

        raw = "".join(raw_parts).strip()
        emotion, display_text = parse_llm_response(raw)

        if not display_text:
            return fallback_emotion, fallback_text, fallback_text

        # Extract voice_response if the LLM returned it and the response is long
        # enough to warrant a split. Otherwise speak the full display text.
        voice_text = display_text
        if wants_split:
            voice_text = _extract_voice_response(raw, display_text)
            log.info(
                "narrator: INFORMATION_QUERY split — display=%d words, voice=%d words",
                len(display_text.split()),
                len(voice_text.split()),
            )
        else:
            log.info(
                "narrator: stage=%s intent=%s display=%d words",
                stage,
                intent.value if intent else "none",
                len(display_text.split()),
            )

        return emotion, display_text, voice_text

    except Exception as exc:  # noqa: BLE001
        log.warning("narrator LLM call failed for stage=%s (%s); using fallback", stage, exc)
        return fallback_emotion, fallback_text, fallback_text


def _extract_voice_response(raw: str, display_text: str) -> str:
    """Pull voice_response from the LLM JSON if present and the display text is long.

    Falls back to display_text when:
    - the LLM did not return a voice_response field
    - voice_response is empty
    - the display text is already short (under the word threshold)
    """
    if len(display_text.split()) < _VOICE_SUMMARY_THRESHOLD:
        return display_text

    import json  # local import — only needed on the INFORMATION_QUERY path
    try:
        data = json.loads(raw)
        voice = str(data.get("voice_response") or "").strip()
        if voice:
            return voice
    except (json.JSONDecodeError, AttributeError):
        pass

    return display_text


async def _deliver(
    websocket: WebSocket,
    tts: TTSProvider,
    emotion: str,
    display_text: str,
    voice_text: str,
) -> None:
    """Stream display_text as tokens to the frontend; speak voice_text via TTS.

    For most intents these are identical. For long INFORMATION_QUERY responses
    the frontend receives the full text while TTS receives the shorter summary.
    """
    if not display_text:
        return

    await websocket.send_json(events.emotion(emotion))

    # Stream full display text as tokens — the frontend renders all of it.
    words = display_text.split()
    for i, word in enumerate(words):
        chunk = word + (" " if i < len(words) - 1 else "")
        await websocket.send_json(events.token(chunk))

    await websocket.send_json(events.reply_done(display_text))
    await websocket.send_json(events.state(events.State.SPEAKING))

    # TTS receives only the voice text — short summary for long responses,
    # identical to display_text for everything else.
    await _speak(websocket, tts, voice_text)
    await websocket.send_json(events.state(events.State.THINKING))