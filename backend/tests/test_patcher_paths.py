"""Edits must never write outside the project workspace."""

from __future__ import annotations

import asyncio

from app.agents.edit_planner import EditPlan, FileEdit
from app.builder.patcher import apply_edit
from app.tools.filesystem import resolve_within


class _WS:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.events.append(data)


class _Task:
    id = "t1"

    def begin_step(self, *_): ...
    def complete_step(self, *_): ...
    def fail_step(self, *_): ...


def test_resolve_within_accepts_nested_paths(tmp_path):
    assert resolve_within(tmp_path, "src/App.jsx") == (tmp_path / "src" / "App.jsx").resolve()


def test_resolve_within_rejects_escapes(tmp_path):
    assert resolve_within(tmp_path, "../evil.js") is None
    assert resolve_within(tmp_path, "src/../../evil.js") is None
    assert resolve_within(tmp_path, str(tmp_path.parent / "evil.js")) is None
    assert resolve_within(tmp_path, "C:/Windows/evil.js") is None
    assert resolve_within(tmp_path, "") is None


def test_apply_edit_refuses_traversal_and_writes_nothing(tmp_path):
    ws = tmp_path / "project"
    ws.mkdir()
    plan = EditPlan(summary="x", edits=[FileEdit(path="../outside.css", content="a { }")])
    result = asyncio.run(apply_edit(plan, ws, _Task(), _WS()))
    assert not result.success
    assert "outside the project" in result.error
    assert not (tmp_path / "outside.css").exists()


def test_apply_edit_refuses_scaffold_files(tmp_path):
    for path in ("package.json", "vite.config.js", "index.html", "src/data.json"):
        plan = EditPlan(summary="x", edits=[FileEdit(path=path, content="{}")])
        result = asyncio.run(apply_edit(plan, tmp_path, _Task(), _WS()))
        assert not result.success and "not an editable source file" in result.error
        assert not (tmp_path / path).exists()


def test_apply_edit_writes_valid_in_workspace_file(tmp_path):
    plan = EditPlan(summary="x", edits=[FileEdit(path="src/styles.css", content="a { }")])
    result = asyncio.run(apply_edit(plan, tmp_path, _Task(), _WS()))
    assert result.success and result.changed == ["src/styles.css"]
    assert (tmp_path / "src" / "styles.css").read_text() == "a { }"
