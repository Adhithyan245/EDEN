"""React + Vite project scaffold.

The scaffold provides all the boilerplate that never needs to change — the
package manifest, the Vite config, the HTML shell, and the React entrypoint.
The planner (LLM) only has to generate the two files that are actually specific
to the requested application:

    src/App.jsx      the application itself
    src/styles.css   its styling

This is the single most important reliability decision in the build pipeline:
by handing the model a working skeleton and asking it to fill in only the app
logic, we keep its output small, in-budget, and far less likely to contain a
fatal mistake in a config file. package.json can never be malformed because the
model never writes it.

The entrypoint imports ./App.jsx and ./styles.css, so the planner's two files
drop straight into a runnable project.

Plain JavaScript + JSX (not TypeScript) is used deliberately: it removes the
tsconfig surface and an entire class of type-check build failures during a live
demo, while remaining idiomatic React that Vite runs without extra setup.
"""

from __future__ import annotations

from ..builder.generator import GeneratedFile


# Pinned to versions known to work together, so `npm install` resolves the same
# tree every time regardless of what floats to latest.
_PACKAGE_JSON = """\
{{
  "name": "{slug}",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }},
  "dependencies": {{
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }},
  "devDependencies": {{
    "@vitejs/plugin-react": "^4.3.4",
    "vite": "^5.4.11"
  }}
}}
"""

_VITE_CONFIG = """\
import {{ defineConfig }} from 'vite'
import react from '@vitejs/plugin-react'

// Port is supplied on the command line at launch time (--port / --strictPort).
// host: true listens on all interfaces (127.0.0.1 + ::1) so the browser can
// reach the server regardless of how 'localhost' resolves on this machine.
export default defineConfig({{
  plugins: [react()],
  server: {{ host: true }},
}})
"""

_INDEX_HTML = """\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{app_name}</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""

_MAIN_JSX = """\
import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
"""


def _slugify(name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "eden-app"


def scaffold(app_name: str) -> list[GeneratedFile]:
    """Return the fixed React + Vite scaffold files for ``app_name``.

    These are written first; the planner's src/App.jsx and src/styles.css are
    layered on top (and win on any path collision).
    """
    slug = _slugify(app_name)
    return [
        GeneratedFile(path="package.json",   content=_PACKAGE_JSON.format(slug=slug)),
        GeneratedFile(path="vite.config.js", content=_VITE_CONFIG.format()),
        GeneratedFile(path="index.html",     content=_INDEX_HTML.format(app_name=app_name)),
        GeneratedFile(path="src/main.jsx",   content=_MAIN_JSX),
    ]


# Paths the scaffold owns. The planner is expected to provide these two:
APP_FILE   = "src/App.jsx"
STYLE_FILE = "src/styles.css"
