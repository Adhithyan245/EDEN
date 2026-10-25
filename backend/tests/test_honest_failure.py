"""A crash inside the build pipeline must be reported, never papered over."""

from __future__ import annotations

import asyncio

from app import main
from app.agents.intent import IntentResult, IntentType
from app.agents.router import Route, RoutingDecision
from app.agents.task import TaskIntent, create_task
from app.session import Session


class _WS:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.events.append(data)


class _NoChatLLM:
    name = "no-chat"

    def __init__(self) -> None:
        self.calls = 0

    async def stream_reply(self, messages, system, *, model=None, intent=None):
        self.calls += 1
        yield '{"emotion": "happy", "response": "I built your app!"}'


def test_crashed_build_is_reported_not_handed_to_chat(monkeypatch):
    task = create_task(user_request="build a counter", intent=TaskIntent.BUILD)
    decision = RoutingDecision(
        route=Route.AGENT,
        intent=IntentResult(intent=IntentType.BUILD, confidence=1.0, raw_text="build a counter"),
        task=task,
        reason="test",
    )

    async def route(*_a, **_k):
        return decision

    async def assess(*_a, **_k):
        return type("C", (), {"needs": False, "question": None})()

    async def crash(**_k):
        raise RuntimeError("boom")

    llm = _NoChatLLM()
    monkeypatch.setattr(main._ROUTER, "route", route)
    monkeypatch.setattr(main._CLARIFY, "assess", assess)
    monkeypatch.setattr(main._ORCHESTRATOR, "run", crash)
    monkeypatch.setattr(main, "LLM", llm)

    ws = _WS()
    asyncio.run(main._handle_user_message(ws, Session(), "build a counter"))

    replies = [e["response"] for e in ws.events if e.get("type") == "response_ready"]
    assert replies and "nothing was built" in replies[0]
    assert not any("I built your app" in r for r in replies)
    assert llm.calls == 0  # the chat model was never asked to cover for the crash
