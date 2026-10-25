"""Static validator tests: the gate every generated or edited file passes before disk."""

from __future__ import annotations

from app.builder.validator import validate_all, validate_file, validate_workspace

GOOD_APP = """import React, { useState } from 'react';
export default function App() {
  const [n, setN] = useState(0);
  return (<button onClick={() => setN(n + 1)}>{n}</button>);
}
"""


def test_valid_app_passes():
    assert validate_file("src/App.jsx", GOOD_APP).ok


def test_empty_file_rejected():
    r = validate_file("src/App.jsx", "   \n")
    assert not r.ok and "empty" in r.reason


def test_truncated_app_rejected_for_unbalanced_braces():
    r = validate_file("src/App.jsx", GOOD_APP[:-3])
    assert not r.ok and "unbalanced" in r.reason


def test_missing_default_export_rejected():
    r = validate_file("src/App.jsx", GOOD_APP.replace("export default ", ""))
    assert not r.ok and "default export" in r.reason


def test_third_party_import_rejected():
    r = validate_file("src/App.jsx", "import axios from 'axios';\n" + GOOD_APP)
    assert not r.ok and "axios" in r.reason


def test_react_subpaths_and_relative_imports_allowed():
    code = "import { createRoot } from 'react-dom/client';\nimport x from './x';\n" + GOOD_APP
    assert validate_file("src/App.jsx", code).ok


def test_css_unbalanced_braces_rejected():
    assert validate_file("src/styles.css", "body { color: red; }").ok
    assert not validate_file("src/styles.css", "body { color: red;").ok


def test_unknown_file_types_accepted():
    assert validate_file("README.md", "anything {").ok


def test_validate_all_returns_first_failure():
    r = validate_all({"src/App.jsx": GOOD_APP, "src/styles.css": "a {"})
    assert not r.ok and "styles.css" in r.reason


def test_validate_workspace_shape(tmp_path):
    assert not validate_workspace(tmp_path / "missing").ok
    assert not validate_workspace(tmp_path).ok  # no package.json
    (tmp_path / "package.json").write_text("{}")
    assert not validate_workspace(tmp_path).ok  # no src/
    (tmp_path / "src").mkdir()
    assert validate_workspace(tmp_path).ok
    assert not validate_workspace(tmp_path, ["src/App.jsx"]).ok
    (tmp_path / "src" / "App.jsx").write_text(GOOD_APP)
    assert validate_workspace(tmp_path, ["src/App.jsx"]).ok
