"""Preview registry and the /preview route's path handling."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.builder.preview import PreviewRegistry, _summarize


def test_registry_reuses_id_per_workspace(tmp_path):
    reg = PreviewRegistry()
    a = reg.register(tmp_path)
    assert reg.register(tmp_path) == a
    assert reg.dist(a) == tmp_path.resolve() / "dist"
    assert reg.url(a) == f"/preview/{a}/"
    assert reg.dist("unknown") is None
    assert len(a) >= 16  # unguessable


def test_summarize_keeps_error_lines():
    out = "\n".join(["vite v5", "transforming...", "x Build failed",
                     "src/App.jsx (3:4): Unexpected token", "done"])
    s = _summarize(out)
    assert "Unexpected token" in s and "Build failed" in s and "transforming" not in s


@pytest.fixture()
def served(tmp_path, monkeypatch):
    from app import main

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "a.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    reg = PreviewRegistry()
    monkeypatch.setattr(main, "previews", reg)
    return main, reg.register(tmp_path)


def _get(main, pid, path):
    return asyncio.run(main.preview(pid, path))


def test_preview_serves_files_and_spa_fallback(served):
    main, pid = served
    assert str(_get(main, pid, "").path).endswith("index.html")
    assert str(_get(main, pid, "assets/a.js").path).endswith("a.js")
    assert str(_get(main, pid, "some/route").path).endswith("index.html")


def test_preview_blocks_traversal_and_unknown_ids(served):
    main, pid = served
    with pytest.raises(HTTPException):
        _get(main, pid, "../secret.txt")
    with pytest.raises(HTTPException):
        _get(main, "nope", "")
