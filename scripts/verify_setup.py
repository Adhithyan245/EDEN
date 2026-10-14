#!/usr/bin/env python3
"""EDEN - Day-0 API & environment verification.

Reports what's available and what EDEN will use in each DEMO MODE. It is
intentionally NON-FATAL for missing optional keys: a missing key is a downgrade
(Gemini -> mock, ElevenLabs -> browser voice), not an error. Development is
never blocked on external API availability.

Usage:
    python scripts/verify_setup.py            # status only (no network calls)
    python scripts/verify_setup.py --live     # also ping present providers
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

OK = "[ OK ]"
NO = "[MISS]"
WARN = "[WARN]"

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "backend" / ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal key=value parser — used when python-dotenv is not installed."""
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def load_env() -> None:
    """Load backend/.env into os.environ, always overriding stale values."""
    print(f"  env file : {ENV_FILE}")
    if not ENV_FILE.exists():
        print(f"  {WARN} backend/.env not found — running without it")
        return

    if importlib.util.find_spec("dotenv"):
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE, override=True)
        print(f"  {OK} loaded via python-dotenv (override=True)")
    else:
        # python-dotenv not in the active Python; fall back to built-in parser.
        pairs = _parse_env_file(ENV_FILE)
        for k, v in pairs.items():
            os.environ[k] = v
        print(f"  {OK} loaded via built-in parser ({len(pairs)} keys) — install python-dotenv for full .env support")
    print()


def check_deps() -> bool:
    """Required backend deps. Missing ones are a real blocker (exit non-zero)."""
    required = ["fastapi", "uvicorn", "google.genai", "httpx"]
    optional = ["dotenv"]
    print("Dependencies")
    all_required = True
    for mod in required:
        present = importlib.util.find_spec(mod) is not None
        label = "google-genai" if mod == "google.genai" else mod
        print(f"  {OK if present else NO} {label}")
        all_required = all_required and present
    for mod in optional:
        present = importlib.util.find_spec(mod) is not None
        label = "python-dotenv" if mod == "dotenv" else mod
        print(f"  {OK if present else WARN} {label} (optional)")
    if not all_required:
        print(f"\n  {WARN} Install backend deps:  pip install -r backend/requirements.txt")
    print()
    return all_required


def env(name: str) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else None


def check_credentials() -> tuple[bool, bool]:
    print("Credentials")
    mode = (env("EDEN_MODE") or "SAFE").upper()
    print(f"  EDEN_MODE = {mode}")

    has_gemini = bool(env("GEMINI_API_KEY"))
    if has_gemini:
        print(f"  {OK} GEMINI_API_KEY present     -> reasoning: Gemini")
    else:
        print(f"  {WARN} No Gemini key              -> reasoning: mock (dev is NOT blocked)")
        print("         Set GEMINI_API_KEY in backend/.env")
        print("         Get a key at: https://aistudio.google.com/apikey")

    has_elevenlabs = bool(env("ELEVENLABS_API_KEY"))
    if has_elevenlabs:
        print(f"  {OK} ELEVENLABS_API_KEY present  -> voice: ElevenLabs (premium)")
    else:
        print(f"  {WARN} No ElevenLabs key          -> voice: browser SpeechSynthesis")
    print()
    return has_gemini, has_elevenlabs


def resolved_providers(has_gemini: bool, has_elevenlabs: bool) -> None:
    print("Resolved providers per DEMO MODE")
    voice_enabled = (env("EDEN_VOICE_ENABLED") or "true").lower() in {"1", "true", "yes", "on"}
    rows = {
        "LIVE": (
            "Gemini" if has_gemini else "mock",
            "ElevenLabs" if (has_elevenlabs and voice_enabled) else "browser",
        ),
        "SAFE": (
            "Gemini" if has_gemini else "mock",
            "ElevenLabs" if (has_elevenlabs and voice_enabled) else "browser",
        ),
        "PRESENTATION": ("scripted", "browser"),
    }
    for mode, (llm, tts) in rows.items():
        print(f"  {mode:<13} llm={llm:<10} tts={tts}")
    print()


def check_models(has_gemini: bool) -> None:
    """Validate configured model IDs against the live Gemini API."""
    print("Model validation")
    if not has_gemini:
        print(f"  ....  skipped (no GEMINI_API_KEY)")
        print()
        return

    try:
        from google import genai

        client = genai.Client(api_key=env("GEMINI_API_KEY"))
        available = {m.name.split("/")[-1] for m in client.models.list()}

        for var, default, role in [
            ("EDEN_MODEL_VOICE",   "gemini-3.1-flash-lite", "voice"),
            ("EDEN_MODEL_BUILDER", "gemini-3.1-flash-lite", "builder"),
        ]:
            model_id = env(var) or default
            if model_id in available:
                print(f"  {OK} {var}={model_id} ({role}) — available")
            else:
                print(f"  {WARN} {var}={model_id} ({role}) — NOT in available models list")
                print(f"         Run with --models to see what's available")
    except Exception as exc:  # noqa: BLE001
        print(f"  {WARN} model validation failed: {exc}")
    print()


def list_models(has_gemini: bool) -> None:
    """Print all models available to the configured API key."""
    print("Available Gemini models")
    if not has_gemini:
        print(f"  ....  skipped (no GEMINI_API_KEY)")
        print()
        return

    try:
        from google import genai

        client = genai.Client(api_key=env("GEMINI_API_KEY"))
        for m in client.models.list():
            methods = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None) or []
            if "generateContent" not in methods:
                continue  # skip embedding / audio-only models
            short = m.name.split("/")[-1]
            dname = getattr(m, "display_name", "") or ""
            desc  = (getattr(m, "description", "") or "")[:60]
            print(f"  {short:<45} {dname}")
            if desc:
                print(f"    {desc}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {WARN} could not list models: {exc}")
    print()


def live_checks(has_gemini: bool, has_elevenlabs: bool) -> None:
    """Ping present providers; for Gemini run a real streaming call."""
    print("Live checks (--live)")

    if has_gemini:
        try:
            import asyncio
            from google import genai
            from google.genai import types

            async def _stream_test() -> str:
                client = genai.Client(api_key=env("GEMINI_API_KEY"))
                model = env("EDEN_MODEL_VOICE") or "gemini-3.1-flash-lite"
                tokens: list[str] = []
                async for chunk in await client.aio.models.generate_content_stream(
                    model=model,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[types.Part(text="Reply with exactly the word: READY")],
                        )
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction="You are a test probe. Follow instructions exactly.",
                        max_output_tokens=32,
                    ),
                ):
                    if chunk.text:
                        tokens.append(chunk.text)
                    if len(tokens) > 20:
                        break
                return "".join(tokens).strip()

            voice_model = env("EDEN_MODEL_VOICE") or "gemini-2.5-flash"
            reply = asyncio.run(_stream_test())
            print(f"  {OK} Gemini stream OK  model={voice_model!r}  replied: {reply[:80]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {WARN} Gemini stream test failed: {exc}")
    else:
        print(f"  ....  skipped Gemini (no GEMINI_API_KEY)")

    if has_elevenlabs:
        try:
            import httpx

            r = httpx.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": env("ELEVENLABS_API_KEY") or ""},
                timeout=15.0,
            )
            r.raise_for_status()
            print(f"  {OK} ElevenLabs API reachable")
        except Exception as exc:  # noqa: BLE001
            print(f"  {WARN} ElevenLabs ping failed: {exc}")
    else:
        print(f"  ....  skipped ElevenLabs (no key)")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify EDEN's environment.")
    parser.add_argument("--live",   action="store_true", help="ping providers + validate model IDs")
    parser.add_argument("--models", action="store_true", help="list all generateContent-capable models for the key")
    args = parser.parse_args()

    print("=" * 60)
    print("EDEN - environment verification")
    print("=" * 60)
    print()
    print("Loading .env")
    load_env()
    deps_ok = check_deps()
    has_gemini, has_elevenlabs = check_credentials()
    resolved_providers(has_gemini, has_elevenlabs)
    if args.models:
        list_models(has_gemini)
    if args.live:
        if deps_ok:
            check_models(has_gemini)
            live_checks(has_gemini, has_elevenlabs)
        else:
            print("Live checks skipped: install backend deps first.\n")

    print("Summary")
    print(f"  EDEN will run{' ' if deps_ok else ' ONCE DEPS ARE INSTALLED '}"
          f"in {'full' if (has_gemini and has_elevenlabs) else 'fallback'} configuration.")
    print("  Missing optional keys are fine - EDEN degrades gracefully.")
    # Only a hard failure (missing required deps) is non-zero.
    return 0 if deps_ok else 1


if __name__ == "__main__":
    sys.exit(main())
