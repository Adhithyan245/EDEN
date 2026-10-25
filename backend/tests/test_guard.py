"""Public-deployment guard: access code, origin allow-list, rate limits."""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

from app.guard import Guard, SlidingWindow


def _ws(protocols: str = "") -> SimpleNamespace:
    return SimpleNamespace(headers={"sec-websocket-protocol": protocols} if protocols else {})


def _code(code: str) -> str:
    return "code." + base64.urlsafe_b64encode(code.encode()).decode().rstrip("=")


def _guard(monkeypatch, **env) -> Guard:
    for k in ("EDEN_ACCESS_CODE", "EDEN_ALLOWED_ORIGINS", "EDEN_MAX_MESSAGES_PER_MINUTE",
              "EDEN_MAX_AGENT_TASKS_PER_HOUR", "EDEN_MAX_AGENT_TASKS_PER_IP_PER_HOUR"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Guard()


def test_open_by_default(monkeypatch):
    g = _guard(monkeypatch)
    assert g.authorized(_ws()) and g.origin_allowed("https://anything.example")
    assert g.subprotocol(_ws()) is None
    assert g.subprotocol(_ws("eden")) == "eden"


def test_access_code_required_when_set(monkeypatch):
    g = _guard(monkeypatch, EDEN_ACCESS_CODE="sesame-42")
    assert not g.authorized(_ws())
    assert not g.authorized(_ws(f"eden, {_code('wrong')}"))
    assert not g.authorized(_ws("eden, code.%%%"))
    assert g.authorized(_ws(f"eden, {_code('sesame-42')}"))


def test_access_code_with_non_ascii(monkeypatch):
    g = _guard(monkeypatch, EDEN_ACCESS_CODE="café ☕")
    assert g.authorized(_ws(f"eden, {_code('café ☕')}"))


def test_origin_allow_list(monkeypatch):
    g = _guard(monkeypatch, EDEN_ALLOWED_ORIGINS="https://eden.vercel.app, http://localhost:5173/")
    assert g.origin_allowed("https://eden.vercel.app")
    assert g.origin_allowed("http://localhost:5173")
    assert not g.origin_allowed("https://evil.example")
    assert not g.origin_allowed(None)


def test_sliding_window():
    w = SlidingWindow(2, 60)
    assert w.allow() and w.allow() and not w.allow()


def test_agent_slot_serializes_and_caps(monkeypatch):
    g = _guard(monkeypatch, EDEN_MAX_AGENT_TASKS_PER_HOUR="2")

    async def scenario():
        seen = []
        async with g.agent_slot() as first:
            seen.append(first)
            async with g.agent_slot() as concurrent:
                seen.append(concurrent)
        async with g.agent_slot() as second:
            seen.append(second)
        async with g.agent_slot() as third:
            seen.append(third)
        return seen

    first, concurrent, second, third = asyncio.run(scenario())
    assert first is None and second is None
    assert concurrent and "another build" in concurrent
    assert third and "limit" in third


def test_empty_access_code_means_open(monkeypatch):
    g = _guard(monkeypatch, EDEN_ACCESS_CODE="")
    assert g.access_code is None and g.authorized(_ws())


def test_per_ip_cap_does_not_block_other_visitors(monkeypatch):
    g = _guard(monkeypatch, EDEN_MAX_AGENT_TASKS_PER_IP_PER_HOUR="1")

    async def run(ip):
        async with g.agent_slot(ip) as refused:
            return refused

    async def scenario():
        return [await run("1.1.1.1"), await run("1.1.1.1"), await run("2.2.2.2")]

    first, again, other = asyncio.run(scenario())
    assert first is None and other is None
    assert again and "your builds" in again
