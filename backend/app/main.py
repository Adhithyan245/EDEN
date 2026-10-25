"""EDEN backend entrypoint: FastAPI app + the WebSocket event stream.

Conversation spine: a client connects over WebSocket, sends a user message,
and EDEN streams back reasoning state, response tokens, and speech — using
whichever providers the factory selected for the current DEMO MODE.
Runs end-to-end with zero credentials (mock LLM + browser TTS).

Agent routing: when EDEN_AGENT_ENABLED=true, BUILD requests are intercepted
before the conversational pipeline and routed to the Orchestrator, which drives
the full plan → generate → execute → verify → narrate lifecycle.

Intent-aware pipeline: detected intent is threaded through LLM generation and
the narrator so INFORMATION_QUERY responses get more token headroom and a
separate voice summary; CHAT/CONVERSATION stays short and natural.
"""

from __future__ import annotations

import asyncio
import logging

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from . import events
from .builder.preview import previews
from .config import settings
from .guard import CLOSE_FORBIDDEN_ORIGIN, CLOSE_UNAUTHORIZED, guard
from .memory import build_memory_manager
from .perception import is_wake_phrase, resolve_scope
from .prompts.eden_personality import build_system_prompt
from .providers import factory
from .session import PendingClarification, Session
from .tools.portguard import kill_stale_backend_on_port
from .tools.filesystem import resolve_within
from .tools.shell import kill_orphaned_dev_servers
from .utils import parse_llm_response
from .voice import speak as _speak_voice

# Agent infrastructure — only imported when EDEN_AGENT_ENABLED=true so the
# conversational-only path has zero overhead and zero import risk.
if settings.agent_enabled:
    from .agents.clarification import clarification_manager as _CLARIFY
    from .agents.edit_orchestrator import edit_orchestrator as _EDIT_ORCHESTRATOR
    from .agents.intent import IntentResult, IntentType
    from .agents.narrator import narrate_stage as _narrate
    from .agents.orchestrator import orchestrator as _ORCHESTRATOR
    from .agents.router import Route, RoutingDecision, router as _ROUTER
    from .agents.task import TaskIntent, create_task
    from .builder.active_project import project_manager as _PROJECTS

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("eden")

# A stale backend process from an earlier run can still be LISTENING on our
# port (Windows does not guarantee only one process may bind it); if so, an
# already-open frontend connection can silently stick to that old process and
# serve outdated code. Clear it before this process binds the same port.
kill_stale_backend_on_port(settings.port)

# A previous backend process (crash, --reload, an earlier demo run) may have
# left Vite dev servers running with no session left to kill them. Sweep them
# before this process launches any new one.
kill_orphaned_dev_servers()

app = FastAPI(title="EDEN", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(guard.allowed_origins) or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Providers chosen once at startup from mode + credential availability.
LLM = factory.build_llm()
TTS = factory.build_tts()

# Research agent for INFORMATION_QUERY requests.
RESEARCH = factory.build_research_agent()

# Long-term memory. Provider-independent: it holds no LLM; the active provider
# is passed into update calls. Safe no-op if disabled or if anything fails.
MEMORY = build_memory_manager()

# Strong references to fire-and-forget memory-update tasks. asyncio only holds
# a weak reference to a task, so without this a pending background update can be
# garbage-collected mid-flight; keeping it here until it finishes prevents that.
_MEMORY_TASKS: set = set()

# System prompt built once; user name comes from config.
SYSTEM_PROMPT = build_system_prompt(settings.user_name or "there")


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "mode":   settings.mode.value,
        "llm":    LLM.name,
        "tts":    TTS.name,
        "agent":  settings.agent_enabled,
        "memory": MEMORY.health(),
    }


@app.get("/diagnose")
async def diagnose(request: Request) -> dict:
    """Live connectivity check for the currently selected LLM provider.

    Spends an LLM call, so a public deployment requires the access code in the
    ``X-EDEN-Access`` header, and an open public deployment (origin allow-list
    but no code) disables it.
    """
    if guard.access_code:
        if request.headers.get("x-eden-access") != guard.access_code:
            raise HTTPException(status_code=401, detail="access code required")
    elif guard.allowed_origins:
        raise HTTPException(status_code=404, detail="not available on this deployment")
    result: dict = {
        "mode": settings.mode.value,
        "llm":  LLM.name,
        "tts":  TTS.name,
    }
    try:
        tokens: list[str] = []
        async for t in LLM.stream_reply(
            [{"role": "user", "content": "Reply with exactly the word: READY"}],
            "You are a test probe. Follow instructions exactly.",
            model=settings.model_voice,
        ):
            tokens.append(t)
            if len(tokens) > 20:
                break
        raw = "".join(tokens)
        _, spoken = parse_llm_response(raw)
        result["llm_ok"]     = True
        result["llm_sample"] = spoken[:120]
        result["detail"]     = f"LLM ({LLM.name}) stream confirmed."
    except Exception as exc:  # noqa: BLE001
        result["llm_ok"] = False
        result["detail"] = f"LLM ({LLM.name}) failed: {exc}"
    return result


@app.get("/preview/{pid}/{path:path}")
async def preview(pid: str, path: str = "") -> FileResponse:
    """Serve a compiled app (its vite ``dist/``) by its unguessable preview id."""
    dist = previews.dist(pid)
    if dist is None or not dist.is_dir():
        raise HTTPException(status_code=404, detail="preview not found")
    target = resolve_within(dist, path) if path else dist / "index.html"
    if target is None:
        raise HTTPException(status_code=404, detail="not found")
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        # Single-page app: unknown paths fall back to the entry page.
        target = dist / "index.html"
    return FileResponse(target, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

# Longest user message accepted; a real request is a sentence or two.
_MAX_MESSAGE_CHARS = 2000


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    # Public-deployment checks (all no-ops unless configured; see guard.py).
    # Accept first so the browser receives the close code and can react.
    await websocket.accept(subprotocol=guard.subprotocol(websocket))
    if not guard.origin_allowed(websocket.headers.get("origin")):
        log.warning("rejected websocket from origin %r", websocket.headers.get("origin"))
        await websocket.close(code=CLOSE_FORBIDDEN_ORIGIN)
        return
    if not guard.authorized(websocket):
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    limiter = guard.message_limiter()
    session = Session()
    log.info(
        "client connected (mode=%s llm=%s tts=%s agent=%s)",
        settings.mode.value, LLM.name, TTS.name, settings.agent_enabled,
    )
    await websocket.send_json(
        events.ready(settings.mode.value, LLM.name, TTS.name, settings.user_name or "")
    )
    try:
        while True:
            msg  = await websocket.receive_json()
            kind = msg.get("type")
            if kind == "ping":
                await websocket.send_json(events.pong())
                continue
            if kind == "user_message":
                if not limiter.allow():
                    await _notice(websocket, "You're sending messages faster than I can keep up. "
                                             "Give me a few seconds.")
                    continue
                text = str(msg.get("text", ""))[:_MAX_MESSAGE_CHARS]
                await _handle_user_message(websocket, session, text)
                continue
            log.warning("unknown message type: %r", kind)
    except WebSocketDisconnect:
        log.info("client disconnected")
    except Exception as exc:  # noqa: BLE001
        log.exception("websocket error")
        try:
            await websocket.send_json(events.error(str(exc)))
        except Exception:
            pass


def _client_ip(websocket: WebSocket) -> str:
    return websocket.client.host if websocket.client else "unknown"


async def _notice(websocket: WebSocket, text: str) -> None:
    """Tell the user something without running the LLM (limits, busy)."""
    await websocket.send_json(events.response_ready(text))
    await _speak_voice(websocket, TTS, text)
    await websocket.send_json(events.state(events.State.IDLE))


# ---------------------------------------------------------------------------
# Clarification resume
# ---------------------------------------------------------------------------

async def _resume_after_clarification(
    websocket: WebSocket,
    session:   Session,
    answer:    str,
) -> None:
    """Treat ``answer`` as the reply to EDEN's pending question and build."""
    pend = session.pending_clarification
    session.pending_clarification = None
    if pend is None:  # defensive; the caller already checked
        return

    await websocket.send_json(events.state(events.State.THINKING))
    combined = (
        f"{pend.original_request}\n\n"
        f"(Clarification — {pend.question} Answer: {answer})"
    )
    task = create_task(user_request=combined, intent=TaskIntent.BUILD)
    decision = RoutingDecision(
        route  = Route.AGENT,
        intent = IntentResult(
            intent     = IntentType.BUILD,
            confidence = 1.0,
            raw_text   = combined,
            features   = pend.features,
        ),
        task   = task,
        reason = "clarification answered",
    )
    try:
        async with guard.agent_slot(_client_ip(websocket)) as refused:
            if refused:
                await _notice(websocket, refused)
                return
            await websocket.send_json(events.task_created(task.to_dict()))
            await _ORCHESTRATOR.run(
                websocket     = websocket,
                session       = session,
                decision      = decision,
                llm           = LLM,
                tts           = TTS,
                system_prompt = SYSTEM_PROMPT,
            )
    finally:
        await websocket.send_json(events.state(events.State.IDLE))


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

async def _handle_user_message(
    websocket: WebSocket,
    session:   Session,
    text:      str,
) -> None:
    text = text.strip()
    if not text:
        return

    session.add_user(text)
    await websocket.send_json(events.state(events.State.THINKING))

    # Resolve who EDEN is speaking to. A wake, or an explicit address to the
    # room, flips the session to public and it stays there (sticky).
    wake = is_wake_phrase(text)
    session.audience_scope = resolve_scope(text, session.audience_scope, is_wake=wake)

    # ------------------------------------------------------------------
    # Clarification resume — if EDEN asked a question last turn, this message
    # is the answer. Build directly from the original request + the answer.
    # ------------------------------------------------------------------
    if settings.agent_enabled and session.pending_clarification is not None:
        await _resume_after_clarification(websocket, session, text)
        return

    # ------------------------------------------------------------------
    # Agent routing — active only when EDEN_AGENT_ENABLED=true.
    # Wake phrases bypass routing (they are always conversational).
    # BUILD/EDIT intent → orchestrator (full pipeline, then return).
    # INFORMATION_QUERY → conversational pipeline with intent forwarded.
    # Everything else falls through to the conversational pipeline.
    # ------------------------------------------------------------------
    detected_intent = None  # carries intent into the conversational pipeline below

    if settings.agent_enabled and not wake:
        try:
            # Give the router the active project (if any) so it can tell an edit
            # of the running app apart from a request to build a new one.
            active = _PROJECTS.get(str(id(session)))
            active_summary = active.summary() if active else None

            decision = await _ROUTER.route(text, LLM, active_project_summary=active_summary)
            detected_intent = decision.intent.intent

            log.info(
                "intent=%s route=%s confidence=%.2f",
                detected_intent.value,
                decision.route.value,
                decision.intent.confidence,
            )

            await websocket.send_json(events.agent_routing(
                route      = decision.route.value,
                intent     = decision.intent.intent.value,
                confidence = decision.intent.confidence,
            ))

            if decision.route == Route.AGENT and decision.task is not None:
                if decision.task.intent == TaskIntent.EDIT:
                    # Show the constellation immediately so the audience sees the
                    # build environment before the 5-8 s edit-plan wait.
                    async with guard.agent_slot(_client_ip(websocket)) as refused:
                        if refused:
                            await _notice(websocket, refused)
                            return
                        await websocket.send_json(events.task_created(decision.task.to_dict()))
                        await _EDIT_ORCHESTRATOR.run(
                            websocket     = websocket,
                            session       = session,
                            decision      = decision,
                            llm           = LLM,
                            tts           = TTS,
                            system_prompt = SYSTEM_PROMPT,
                        )
                else:
                    # Understand first: a real engineer may ask ONE question
                    # before building if the answer changes the architecture.
                    clar = await _CLARIFY.assess(text, decision.intent.features, LLM)
                    if clar.needs and clar.question:
                        session.pending_clarification = PendingClarification(
                            original_request = text,
                            question         = clar.question,
                            features         = decision.intent.features,
                        )
                        await websocket.send_json(events.clarification_requested(clar.question))
                        await _narrate(
                            "clarify",
                            {"question": clar.question, "fallback": clar.question},
                            LLM, TTS, websocket, SYSTEM_PROMPT, session.audience_scope,
                        )
                        await websocket.send_json(events.state(events.State.IDLE))
                        return   # wait for the answer; build resumes next turn
                    # Show the planning phase immediately before the 4-5 s LLM wait.
                    async with guard.agent_slot(_client_ip(websocket)) as refused:
                        if refused:
                            await _notice(websocket, refused)
                            return
                        await websocket.send_json(events.task_created(decision.task.to_dict()))
                        await _ORCHESTRATOR.run(
                            websocket     = websocket,
                            session       = session,
                            decision      = decision,
                            llm           = LLM,
                            tts           = TTS,
                            system_prompt = SYSTEM_PROMPT,
                        )
                await websocket.send_json(events.state(events.State.IDLE))
                return   # ← skip conversational pipeline for BUILD/EDIT requests

        except Exception as exc:  # noqa: BLE001
            log.warning("agent routing failed (%s); falling back to conversation", exc)
            detected_intent = None  # reset so the fallback path is clean

    # ------------------------------------------------------------------
    # Conversational pipeline (unchanged spine from Day 0, now intent-aware)
    #
    # detected_intent is forwarded to:
    #   - LLM.stream_reply  → selects generation config (tokens, temperature)
    #   - voice delivery    → INFORMATION_QUERY gets display/voice split
    # ------------------------------------------------------------------
    if wake:
        marker = "[WAKE SEQUENCE] "
        log.info("wake sequence detected — injecting context")
    elif session.audience_scope == "public":
        marker = "[AUDIENCE: public] "
    else:
        marker = ""

    if marker:
        llm_messages = session.messages[:-1] + [
            {"role": "user", "content": f"{marker}{text}"}
        ]
    else:
        llm_messages = session.messages

    # ------------------------------------------------------------------
    # Memory retrieval (before the LLM, before research)
    # Pull only the memories relevant to this turn and append them to the
    # system prompt for this call. This never touches session history or the
    # message list, and returns "" when memory is disabled or nothing is
    # relevant — so the prompt is unchanged in that case.
    # ------------------------------------------------------------------
    memory_block = await MEMORY.retrieve_context(text)
    system_for_turn = SYSTEM_PROMPT + memory_block

    # ------------------------------------------------------------------
    # Research phase (INFORMATION_QUERY only)
    # Gather external knowledge before asking the LLM to respond. Sources are
    # kept alongside the context string so they can ride along to the
    # frontend on response_ready — research that isn't shown is research
    # that didn't happen, as far as the audience is concerned.
    # ------------------------------------------------------------------
    research_context = ""
    sources_payload: list[dict] = []
    if detected_intent is not None and detected_intent.value == "information_query":
        try:
            log.info("Research phase: gathering information for query: %s", text[:80])
            research_result = await RESEARCH.research(text)
            if research_result.status == "ok" and research_result.sources:
                research_context = research_result.context
                sources_payload = [
                    {"title": s.title, "url": s.url, "snippet": s.snippet or s.content[:200]}
                    for s in research_result.sources
                ]
                log.info(
                    "Research completed: %d sources, confidence=%s",
                    len(research_result.sources),
                    research_result.confidence,
                )
                # Inject research context into the user message
                enriched_content = f"{text}\n\n[Research context:\n{research_context}]"
                llm_messages = session.messages[:-1] + [
                    {"role": "user", "content": enriched_content}
                ]
            else:
                log.info("Research yielded no results; proceeding without context")
        except Exception as exc:  # noqa: BLE001
            log.warning("Research failed; proceeding without context: %s", exc)

    # Buffer the full LLM response. The personality layer returns
    # {"emotion":"…","response":"…"[,"voice_response":"…"]} — JSON must be
    # complete before parsing. intent is forwarded so the provider can tune
    # generation parameters (token budget, temperature) per request type.
    raw_parts: list[str] = []
    try:
        async for delta in LLM.stream_reply(
            llm_messages,
            system_for_turn,
            intent=detected_intent,
        ):
            raw_parts.append(delta)
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM stream failed: %s", exc)
        raw_parts = [
            '{"emotion":"concerned",'
            '"response":"That did not go according to plan. '
            'Fortunately, I am better at recovering than panicking."}'
        ]

    raw = "".join(raw_parts).strip()
    emotion_name, reply = parse_llm_response(raw)
    log.info("emotion=%s intent=%s reply=%r", emotion_name, detected_intent, reply[:80])

    # For INFORMATION_QUERY, extract a separate voice summary if the LLM
    # returned one (narrator addendum requested it). For all other intents
    # voice_text == reply so TTS behavior is completely unchanged.
    voice_text = _extract_voice_text(raw, reply, detected_intent)

    await websocket.send_json(events.emotion(emotion_name))

    # Stream the full display reply as tokens — frontend renders all of it.
    words = reply.split()
    for i, word in enumerate(words):
        chunk = word + (" " if i < len(words) - 1 else "")
        await websocket.send_json(events.token(chunk))

    session.add_assistant(reply)
    response_mode = (
        events.ResponseMode.INFORMATION
        if detected_intent is not None and detected_intent.value == "information_query"
        else events.ResponseMode.CHAT
    )
    await websocket.send_json(
        events.reply_done(reply, voice_response=voice_text, response_mode=response_mode)
    )
    await websocket.send_json(
        events.response_ready(
            reply,
            voice_response=voice_text,
            response_mode=response_mode,
            sources=sources_payload,
        )
    )

    # Speak only the voice text — short summary for long INFORMATION_QUERY
    # responses; identical to reply for all other intents.
    await websocket.send_json(events.state(events.State.SPEAKING))
    await _speak_voice(websocket, TTS, voice_text)
    await websocket.send_json(events.state(events.State.IDLE))

    # ------------------------------------------------------------------
    # Memory update (after the response — the last stage of the turn)
    # Fire-and-forget: the decision/extraction (and periodic summarization)
    # run in the background so they never delay the user-perceived response,
    # and the manager swallows its own errors so a memory hiccup can never
    # break the turn. The active provider is passed in — memory itself is
    # provider-independent.
    # ------------------------------------------------------------------
    intent_value = detected_intent.value if detected_intent is not None else None
    _task = asyncio.create_task(
        MEMORY.remember_turn(
            user_text=text,
            assistant_text=reply,
            intent=intent_value,
            llm=LLM,
            recent_messages=list(session.messages),
        )
    )
    _MEMORY_TASKS.add(_task)
    _task.add_done_callback(_MEMORY_TASKS.discard)


# ---------------------------------------------------------------------------
# Voice/display separation helper
# ---------------------------------------------------------------------------

def _extract_voice_text(
    raw: str,
    display_text: str,
    intent: "IntentType | None",
) -> str:
    """Return the text that should be spoken aloud.

    For INFORMATION_QUERY responses the LLM may return a ``voice_response``
    field containing a concise spoken summary. When present and the display
    text is long enough to warrant a split, we use it. In all other cases —
    including any JSON parse failure — we fall back to the full display text
    so TTS behavior is unchanged for CHAT, BUILD, and all other intents.
    """
    # Only attempt a split for information queries with long responses.
    _THRESHOLD = 60  # words — must match narrator._VOICE_SUMMARY_THRESHOLD
    if intent is None or intent.value != "information_query":
        return display_text
    if len(display_text.split()) < _THRESHOLD:
        return display_text

    import json  # local import — only on the INFORMATION_QUERY path
    try:
        data = json.loads(raw)
        voice = str(data.get("voice_response") or "").strip()
        if voice:
            log.info(
                "voice/display split: display=%d words, voice=%d words",
                len(display_text.split()), len(voice.split()),
            )
            return voice
    except (json.JSONDecodeError, AttributeError):
        pass

    return display_text