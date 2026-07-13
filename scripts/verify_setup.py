#!/usr/bin/env python3
"""EDEN - Day-0 API & environment verification.

Reports what's available and what EDEN will use in each DEMO MODE. It is
intentionally NON-FATAL for missing optional keys: a missing key is a downgrade
(Claude -> mock, ElevenLabs -> browser voice), not an error. Development is
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


def load_env() -> None:
    """Load backend/.env if python-dotenv is available (best effort)."""
    if importlib.util.find_spec("dotenv") and ENV_FILE.exists():
        from dotenv import load_dotenv

        load_dotenv(ENV_FILE)


def check_deps() -> bool:
    """Required backend deps. Missing ones are a real blocker (exit non-zero)."""
    required = ["fastapi", "uvicorn", "anthropic", "httpx"]
    optional = ["dotenv"]
    print("Dependencies")
    all_required = True
    for mod in required:
        present = importlib.util.find_spec(mod) is not None
        print(f"  {OK if present else NO} {mod}")
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

    has_key = bool(env("ANTHROPIC_API_KEY"))
    assume = (env("EDEN_ASSUME_ANTHROPIC") or "").lower() in {"1", "true", "yes", "on"}
    has_anthropic = has_key or assume
    if has_key:
        print(f"  {OK} ANTHROPIC_API_KEY present  -> reasoning: Claude")
    elif assume:
        print(f"  {OK} EDEN_ASSUME_ANTHROPIC=true  -> reasoning: Claude (via `ant` profile)")
    else:
        print(f"  {WARN} No Anthropic access        -> reasoning: mock (dev is NOT blocked)")
        print("         Set ANTHROPIC_API_KEY, or run `ant auth login` and set")
        print("         EDEN_ASSUME_ANTHROPIC=true in backend/.env")

    has_elevenlabs = bool(env("ELEVENLABS_API_KEY"))
    if has_elevenlabs:
        print(f"  {OK} ELEVENLABS_API_KEY present  -> voice: ElevenLabs (premium)")
    else:
        print(f"  {WARN} No ElevenLabs key          -> voice: browser SpeechSynthesis")
    print()
    return has_anthropic, has_elevenlabs


def resolved_providers(has_anthropic: bool, has_elevenlabs: bool) -> None:
    print("Resolved providers per DEMO MODE")
    voice_enabled = (env("EDEN_VOICE_ENABLED") or "true").lower() in {"1", "true", "yes", "on"}
    rows = {
        "LIVE": (
            "Claude" if has_anthropic else "mock",
            "ElevenLabs" if (has_elevenlabs and voice_enabled) else "browser",
        ),
        "SAFE": (
            "Claude" if has_anthropic else "mock",
            "ElevenLabs" if (has_elevenlabs and voice_enabled) else "browser",
        ),
        "PRESENTATION": ("scripted", "browser"),
    }
    for mode, (llm, tts) in rows.items():
        print(f"  {mode:<13} llm={llm:<10} tts={tts}")
    print()


def live_checks(has_anthropic: bool, has_elevenlabs: bool) -> None:
    """Ping present providers; for Anthropic run a real streaming call."""
    print("Live checks (--live)")

    if has_anthropic:
        try:
            import asyncio
            import anthropic

            async def _stream_test() -> str:
                client = anthropic.AsyncAnthropic()
                tokens: list[str] = []
                async with client.messages.stream(
                    model=env("EDEN_MODEL_VOICE") or "claude-sonnet-5",
                    max_tokens=32,
                    system="You are a test probe. Follow instructions exactly.",
                    messages=[{"role": "user", "content": "Reply with exactly the word: READY"}],
                ) as stream:
                    async for text in stream.text_stream:
                        tokens.append(text)
                        if len(tokens) > 20:
                            break
                return "".join(tokens).strip()

            reply = asyncio.run(_stream_test())
            print(f"  {OK} Anthropic stream OK  -> model replied: {reply[:80]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {WARN} Anthropic stream test failed: {exc}")
    else:
        print(f"  ....  skipped Anthropic (no key or EDEN_ASSUME_ANTHROPIC not set)")

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
    parser.add_argument("--live", action="store_true", help="ping present providers")
    args = parser.parse_args()

    print("=" * 60)
    print("EDEN - environment verification")
    print("=" * 60)
    if not ENV_FILE.exists():
        print(f"  {WARN} backend/.env not found - copy backend/.env.example to")
        print("         backend/.env (optional; defaults run fine with no keys)\n")

    load_env()
    deps_ok = check_deps()
    has_anthropic, has_elevenlabs = check_credentials()
    resolved_providers(has_anthropic, has_elevenlabs)
    if args.live:
        if deps_ok:
            live_checks(has_anthropic, has_elevenlabs)
        else:
            print("Live checks skipped: install backend deps first.\n")

    print("Summary")
    print(f"  EDEN will run{' ' if deps_ok else ' ONCE DEPS ARE INSTALLED '}"
          f"in {'full' if (has_anthropic and has_elevenlabs) else 'fallback'} configuration.")
    print("  Missing optional keys are fine - EDEN degrades gracefully.")
    # Only a hard failure (missing required deps) is non-zero.
    return 0 if deps_ok else 1


if __name__ == "__main__":
    sys.exit(main())
