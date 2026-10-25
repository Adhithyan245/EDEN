"""The build pipeline's generation gate and its single repair attempt."""

from __future__ import annotations

import asyncio
import json

from app.agents import orchestrator as orch
from app.agents.planner import generate_plan

GOOD = {
    "app_name": "Counter",
    "app_type": "counter",
    "app_jsx": "import React from 'react';\nexport default function App() { return (<div>0</div>); }",
    "styles_css": "body { margin: 0; }",
}


class ScriptLLM:
    """Returns the queued JSON replies in order and records each prompt."""

    name = "script"

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.intents: list = []

    async def stream_reply(self, messages, system, *, model=None, intent=None):
        self.prompts.append(messages[-1]["content"])
        self.intents.append(intent)
        yield json.dumps(self.replies.pop(0))


def _plan(reply: dict, repair_error=None, llm=None):
    llm = llm or ScriptLLM([reply])
    return asyncio.run(generate_plan(
        task_id="t", app_type="counter", app_name="Counter", user_request="build a counter",
        features=[], llm=llm, repair_error=repair_error,
    ))


def test_check_generation_accepts_good_plan():
    assert orch._check_generation(_plan(GOOD)) is None


def test_check_generation_rejects_missing_plan():
    assert orch._check_generation(None) == "the design could not be generated"


def test_check_generation_rejects_invalid_code():
    bad = {**GOOD, "app_jsx": GOOD["app_jsx"] + "\nimport axios from 'axios';"}
    reason = orch._check_generation(_plan(bad))
    assert reason and "generated code is invalid" in reason and "axios" in reason


def test_planner_returns_none_without_default_export():
    assert _plan({**GOOD, "app_jsx": "function App() {}"}) is None


def test_repair_error_is_sent_back_to_the_model():
    llm = ScriptLLM([GOOD])
    _plan(GOOD, repair_error="unbalanced braces in src/App.jsx", llm=llm)
    assert "previous attempt was rejected" in llm.prompts[0]
    assert "unbalanced braces" in llm.prompts[0]


def test_one_repair_is_configured():
    assert orch._MAX_BUILD_REPAIRS == 1


def test_planners_request_the_large_build_budget():
    # B03 in eden-bench-v1 failed when the planner got the default 4096-token cap.
    from app.agents.edit_planner import generate_edit_plan
    from app.agents.intent import IntentType
    from app.providers.llm_gemini import _generation_config

    llm = ScriptLLM([GOOD, {"summary": "x", "files": []}])
    _plan(GOOD, llm=llm)
    asyncio.run(generate_edit_plan("Counter", "make it blue", {"src/App.jsx": "x"}, llm))
    assert llm.intents == [IntentType.BUILD, IntentType.BUILD]
    assert _generation_config(IntentType.BUILD)["max_output_tokens"] >= 16384
