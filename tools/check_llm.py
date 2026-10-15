"""
check_llm.py
============
Pre-flight check for the Qwen (DashScope) API key.

Why this exists
---------------
The Requirements Engineering instructions are explicit that the requirements
JSON "MUST come from Qwen and not your Python program".  In this repository that
means ``artifacts/requirements.json`` and ``artifacts/plan.json`` have to be
produced by the LLM, and the LLM-backed stages of ``main.py`` must report ``ok``
- not ``degraded`` - in ``trace.log``.

Without this check the problem only shows up indirectly:

* no key at all  -> ``main.py`` silently uses the deterministic fallback, the two
  stages are logged ``degraded``, and the artifacts are NOT Qwen's output;
* invalid/expired key, or a model that cannot do JSON mode -> the failure appears
  only after the Analyst stage, i.e. after the expensive IR-SIM benchmark ran.

This script performs one minimal request that also exercises
``response_format={"type": "json_object"}`` - the exact feature every agent in
this pipeline depends on - and prints what to do about each failure.

It never prints the key itself, only whether one was found and where from.

Usage:
    python check_llm.py
    python check_llm.py --model qwen-max     # try a different model

Exit codes:
    0  the key works and the model supports JSON mode
    1  the key is missing, invalid, or the model rejects the request
"""

import os
import sys


import os
import sys

# tools/ holds helper scripts, so the repository root is one level up. Importing
# the agents (analyst_agent, runner, test_irsim_with_agent, ...) requires the
# root on sys.path; without this, running a script from tools/ fails with
# ModuleNotFoundError.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# The .env lives next to the agents, i.e. at the repository root, not in tools/.
ENV_PATH = os.path.join(ROOT, ".env")
EXIT_OK = 0
EXIT_FAIL = 1


def _key_source():
    """Where the credential came from, without revealing its value.

    ``load_env_file()`` copies the .env values into ``os.environ``, so reading
    the environment afterwards cannot tell the two sources apart - and an
    environment variable always wins over .env.  The answer therefore has to be
    decided from the environment *as it was before* .env was loaded.

    Both credentials are considered, because the backend may be DashScope
    (``DASHSCOPE_API_KEY``) or a local OpenAI-compatible server
    (``LLM_BASE_URL`` + ``LLM_API_KEY``).
    """
    from tools.llm_client import BASE_URL_ENV_HINT, load_env_file

    env_before = {name: bool(os.getenv(name))
                  for name in ("DASHSCOPE_API_KEY", "LLM_API_KEY")}
    env_file_readable = os.path.exists(ENV_PATH)

    # Read the credentials straight out of the file, without touching os.environ.
    file_values = {}
    if env_file_readable:
        try:
            with open(ENV_PATH, "r", encoding="utf-8-sig") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    if key in ("DASHSCOPE_API_KEY", "LLM_API_KEY", "LLM_BASE_URL"):
                        file_values[key] = value.strip().strip('"').strip("'")
        except OSError:
            file_values = {}

    load_env_file()  # now make it visible to get_client()

    for name in ("DASHSCOPE_API_KEY", "LLM_API_KEY"):
        if env_before[name]:
            return "environment variable %s (wins over .env)" % name
    for name in ("DASHSCOPE_API_KEY", "LLM_API_KEY"):
        if file_values.get(name):
            return "%s -> %s" % (os.path.relpath(ENV_PATH, ROOT), name)
    if env_file_readable:
        return "%s (exists, but holds no API key)" % os.path.relpath(ENV_PATH, ROOT)
    return "not found (neither the environment nor %s)%s" % (
        os.path.relpath(ENV_PATH, ROOT), BASE_URL_ENV_HINT)


def _advice(result):
    """Turn the pre-flight failure into a concrete next step."""
    error = result.get("error") or ""
    detail = (result.get("detail") or "").lower()

    if not result["key_present"]:
        return [
            "The key is missing, so the Analyst Agent cannot run.",
            "",
            "Fix it with ONE of these:",
            "  1) create .env in this folder (it is git-ignored):",
            "         copy .env.example .env",
            "         then edit .env and set  DASHSCOPE_API_KEY=sk-...",
            "  2) or set it for the current shell only:",
            '         PowerShell : $env:DASHSCOPE_API_KEY = "sk-..."',
            '         bash       : export DASHSCOPE_API_KEY="sk-..."',
            "",
            "Get a key at https://bailian.console.aliyun.com/ -> API-KEY",
            "Then re-run:  python check_llm.py",
        ]

    if "AuthenticationError" in error or "401" in detail or "invalid_api_key" in detail:
        return [
            "A key was found but DashScope rejected it (401 invalid_api_key).",
            "",
            "Check that:",
            "  * the value is the whole key, with no quotes/spaces and no ellipsis;",
            "  * the key was not deleted or regenerated in the console;",
            "  * you copied the API key, not an AccessKey ID/Secret;",
            "  * .env is saved as UTF-8 without a BOM.",
            "Re-copy the key from https://bailian.console.aliyun.com/ -> API-KEY",
        ]

    if "NotFoundError" in error or "404" in detail or "model" in detail and "not" in detail:
        return [
            "The key works but the model was not accepted (HTTP 404 / unknown model).",
            "",
            "Run it again with a model your account can use, for example:",
            "     python check_llm.py --model qwen-plus",
            "     python check_llm.py --model qwen-turbo",
            "or set QWEN_MODEL in .env to that model name.",
        ]

    if "BadRequest" in error or "400" in detail:
        return [
            "The request was rejected (HTTP 400).",
            "",
            "The most common cause is a model that does not support JSON mode",
            "(response_format={'type': 'json_object'}), which every agent here needs.",
            "Try another model:  python check_llm.py --model qwen-plus",
        ]

    if "APIConnection" in error or "Timeout" in error or "timeout" in detail:
        lines = [
            "The request to the model did not complete.",
            "",
            "  * check this machine's internet access / proxy;",
            "  * if you are outside mainland China, the DashScope endpoint may be",
            "    slow or blocked - a VPN or the international endpoint may help;",
        ]
        if result.get("backend", {}).get("kind") in ("local", "custom"):
            lines += [
                "  * a LOCAL model on CPU is slow rather than broken: qwen3:8b needs",
                "    roughly a minute per answer here. The check already waits",
                "    %s s, so a timeout means the server is stuck or still loading"
                % result.get("timeout"),
                "    the model into memory - watch  ollama ps  and retry;",
                "  * a very large model may simply not fit in RAM.",
            ]
        else:
            lines.append("  * if you meant to use a local server, set LLM_BASE_URL.")
        lines.append("Re-run:  python check_llm.py")
        return lines

    if "RateLimit" in error or "429" in detail:
        return [
            "DashScope rate-limited or quota-limited the request (429).",
            "Wait a moment and re-run, or check the quota in the console.",
        ]

    return [
        "The pre-flight request failed for a reason this script does not special-case.",
        "The raw cause is reported above; fix that and re-run  python check_llm.py",
    ]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # --model lets the check try a different model without editing .env.
    if "--model" in argv:
        index = argv.index("--model")
        try:
            os.environ["QWEN_MODEL"] = argv[index + 1]
        except IndexError:
            print("--model needs a value, e.g. --model qwen-plus")
            return EXIT_FAIL

    # Import after QWEN_MODEL is applied so MODEL picks it up.
    from analyst_agent import test_connection

    print("=" * 72)
    print("LLM PRE-FLIGHT CHECK")
    print("=" * 72)
    print("working dir : %s" % ROOT)
    print("script      : %s" % os.path.relpath(os.path.abspath(__file__), ROOT))
    print("key source  : %s" % _key_source())

    result = test_connection()
    backend = result.get("backend") or {}
    print("backend     : %s" % backend.get("kind", "?"))
    print("model       : %s" % result["model"])
    print("endpoint    : %s" % result["base_url"])
    if backend.get("kind") in ("local", "custom"):
        print("timeout     : %ss (local models on CPU need ~1 min per answer)"
              % result.get("timeout"))
    print("-" * 72)

    if result["ok"]:
        print("RESULT      : OK - the credential works and JSON mode is supported")
        if result.get("reply"):
            print("model reply : %s" % result["reply"])
        if result.get("empty_on_first_try"):
            print()
            print("note        : the first attempt returned an empty message (the")
            print("              reasoning budget consumed the token limit) and the")
            print("              retry with a larger budget succeeded. Thinking")
            print("              models such as qwen3 behave this way; it is not an")
            print("              error, but expect each call to be slow.")
        print()
        if backend.get("kind") == "dashscope":
            print("You can now produce the Qwen-authored artifacts with:")
            print("    python run_analyst.py      # -> artifacts/requirements.json")
            print("    python run_planner.py      # -> artifacts/plan.json")
            print("    python main.py             # full pipeline; AnalystAgent/PlannerAgent")
            print("                               #   must be logged 'ok', not 'degraded'")
        else:
            print("REMINDER: this is a LOCAL/custom backend, not DashScope.")
            print("The project instructions describe Qwen on DashScope and require the")
            print("requirements JSON to come from Qwen. Use this for development, but")
            print("confirm with your instructor before submitting a run that used it:")
            print("    unset LLM_BASE_URL   (then re-run python check_llm.py)")
        print("=" * 72)
        return EXIT_OK

    print("RESULT      : FAILED")
    print("error       : %s" % result.get("error"))
    if result.get("detail"):
        print("detail      : %s" % result["detail"])
    print("-" * 72)
    for line in _advice(result):
        print(line)
    print("=" * 72)
    return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
