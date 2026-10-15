"""
llm_client.py
=============
Single place that decides **which** LLM backend the agents talk to.

The course project targets Qwen on Alibaba Cloud DashScope, and that stays the
default: with no extra configuration this module behaves exactly like the
hard-coded clients the agents used before.

Two environment variables make a *local* OpenAI-compatible server (for example
Ollama, as covered by the "Ollama and Qwen installation" practice sheet) usable
without touching any agent code:

    LLM_BASE_URL   endpoint of the OpenAI-compatible API
    LLM_API_KEY    credential for that endpoint

    # .env  ->  talk to a local Ollama instead of DashScope
    LLM_BASE_URL=http://localhost:11434/v1
    LLM_API_KEY=ollama
    QWEN_MODEL=qwen3:8b

Why LLM_API_KEY exists: ``DASHSCOPE_API_KEY`` is the *DashScope* credential and
is expected to look like a DashScope key. A local server usually ignores the
credential entirely, but the ``openai`` client refuses to be constructed without
a non-empty one, so a separate variable keeps the two concerns apart instead of
telling people to put a fake value into ``DASHSCOPE_API_KEY``.

CAVEAT - this is a development convenience, not the graded configuration:
the project instructions describe Qwen on DashScope and the requirements JSON
"must come from Qwen". A local model of a different family would not satisfy
that; keep ``LLM_BASE_URL`` unset for the run you submit unless your instructor
says otherwise. ``describe_backend()`` reports which backend is active so a run
can never be silent about it.
"""

import os

from openai import OpenAI


import os
import sys

# tools/ holds helper scripts, so the repository root is one level up. Importing
# the agents (analyst_agent, runner, test_irsim_with_agent, ...) requires the
# root on sys.path; without this, running a script from tools/ fails with
# ModuleNotFoundError.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Appended to "no credential found" messages so the local-server route is
# discoverable instead of only the DashScope one.
BASE_URL_ENV_HINT = (
    "\n  (or set LLM_BASE_URL + LLM_API_KEY to use a local OpenAI-compatible "
    "server such as Ollama)"
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")


def load_env_file():
    """Load ``KEY=VALUE`` pairs from the ``.env`` next to this file.

    A tiny dependency-free loader, so the API key can be configured without
    installing python-dotenv. Existing environment variables always win.
    """
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH, "r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


def get_model():
    """Model name (``QWEN_MODEL``, default ``qwen-plus``)."""
    load_env_file()
    return os.getenv("QWEN_MODEL", "qwen-plus")


def get_base_url():
    """Endpoint to talk to (``LLM_BASE_URL``, default DashScope)."""
    load_env_file()
    return os.getenv("LLM_BASE_URL") or DASHSCOPE_BASE_URL


def is_local_backend():
    """True when LLM_BASE_URL points somewhere other than DashScope."""
    return get_base_url() != DASHSCOPE_BASE_URL


def get_api_key():
    """The credential to use, or None when none is configured.

    Resolution order:
      1. LLM_API_KEY            - explicit override (local servers)
      2. DASHSCOPE_API_KEY      - the DashScope credential (default backend)
    """
    load_env_file()
    return os.getenv("LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY")


def get_timeout():
    """Per-request timeout in seconds (``LLM_TIMEOUT``, else a backend default).

    This matters far more for a local model than for a hosted API. The agents
    pass no timeout of their own, so without this the ``openai`` client waits
    forever: a stalled request hangs the whole pipeline with no error and no
    progress, which is exactly what a local Ollama does when it unloads the
    model underneath a slow request. A finite timeout turns that into a normal,
    retryable API error instead.

    The local default is deliberately large. A "thinking" model spends most of
    its budget on an internal reasoning block: measured on this machine,
    qwen3:8b answered the Analyst prompt in ~45s but the TestAgent prompt in
    ~1200s (5178 completion tokens, only 1013 prompt tokens). A tighter default
    does not make a slow model faster - it only turns a correct but slow answer
    into a failure. Raise or lower it per machine with LLM_TIMEOUT.
    """
    load_env_file()
    override = os.getenv("LLM_TIMEOUT")
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    return 1800.0 if is_local_backend() else 60.0


def get_client():
    """Build the OpenAI-compatible client for the configured backend."""
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError(
            "No LLM credential is configured. Either use the Qwen API on "
            "DashScope:\n"
            '  PowerShell : $env:DASHSCOPE_API_KEY = "sk-..."\n'
            '  bash       : export DASHSCOPE_API_KEY="sk-..."\n'
            "  or put  DASHSCOPE_API_KEY=sk-...  in a .env file next to this "
            "script.\n"
            "Or point the agents at a local OpenAI-compatible server (Ollama):\n"
            "  LLM_BASE_URL=http://localhost:11434/v1\n"
            "  LLM_API_KEY=ollama\n"
            "  QWEN_MODEL=qwen3:8b"
        )
    return OpenAI(api_key=api_key, base_url=get_base_url(),
                  timeout=get_timeout(), max_retries=1)


def describe_backend():
    """Human-readable description of the active backend, for logs and reports."""
    base_url = get_base_url()
    key = get_api_key()
    if base_url == DASHSCOPE_BASE_URL:
        kind = "dashscope"
        source = ("DASHSCOPE_API_KEY" if os.getenv("DASHSCOPE_API_KEY")
                  else ("LLM_API_KEY" if key else "none"))
    elif base_url.startswith(("http://localhost", "http://127.0.0.1")):
        kind = "local"
        source = "LLM_API_KEY" if os.getenv("LLM_API_KEY") else "none"
    else:
        kind = "custom"
        source = "LLM_API_KEY" if os.getenv("LLM_API_KEY") else "none"
    return {
        "kind": kind,
        "base_url": base_url,
        "model": get_model(),
        "credential_source": source,
        "credential_present": bool(key),
    }
