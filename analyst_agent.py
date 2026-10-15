"""
analyst_agent.py
================
The Analyst Agent for the robot navigation project.

This is the ONLY component responsible for analysing the natural-language
brief (brief.txt) and converting it into explicit software requirements.

It asks the Qwen model to return a JSON object with EXACTLY this structure:

{
  "goal": "string",
  "allowed_actions": ["FORWARD", "LEFT", "RIGHT", "STOP"],
  "safe_stop": true,
  "avoid_obstacles": true
}

The JSON content is produced by Qwen, never hard-coded by this program.
This program only sends the prompt, parses Qwen's answer and validates it.

Public API:
    run_analyst(brief_text)   -> validated requirements (dict)
    validate_requirements(d)  -> validated requirements (dict)
    get_client()              -> configured OpenAI-compatible Qwen client
    test_connection()         -> pre-flight result dict (used by check_llm.py)
"""

import json
import re

from tools.llm_client import (
    describe_backend,
    get_base_url,
    get_client,
    get_model,
    load_env_file as _load_env_file,
)

# Which model / endpoint the agents talk to.  DashScope + qwen-plus by default;
# see llm_client.py for the LLM_BASE_URL / LLM_API_KEY overrides.
MODEL = get_model()
BASE_URL = get_base_url()

# The only keys / actions allowed in the whole system.
REQUIRED_KEYS = {"goal", "allowed_actions", "safe_stop", "avoid_obstacles"}
VALID_ACTIONS = {"FORWARD", "LEFT", "RIGHT", "STOP"}
MAX_ATTEMPTS = 3

SYSTEM_PROMPT = """You are a requirements engineer (the "Analyst Agent") for a mobile robot navigation system.

ROLE:
You analyse a customer's natural-language brief and convert it into explicit software requirements.

TASK:
Read the brief provided by the user and return ONE JSON object that captures the requirements.

The JSON object must contain EXACTLY these four keys and no others:
- "goal": (string) the navigation objective understood from the brief.
- "allowed_actions": (array of strings) every action the robot may take. It must contain exactly these four values and no others, in any order: "FORWARD", "LEFT", "RIGHT", "STOP".
- "safe_stop": (boolean) true, because when no safe direction is available the robot must stop.
- "avoid_obstacles": (boolean) true, because the robot must never move into a blocked direction and must avoid obstacles.

RULES AND CONSTRAINTS:
1. The only allowed actions in the whole system are FORWARD, LEFT, RIGHT, STOP. Never introduce any other action.
2. The robot should prefer moving toward its goal whenever this can be done safely.
3. The robot must never move into a blocked direction.
4. If no safe direction is available, the robot must stop.
5. Output valid JSON only. Do not output markdown, code fences, comments or any explanatory text.
"""


# _load_env_file() and get_client() are imported from llm_client: they resolve
# the backend (DashScope by default, LLM_BASE_URL/LLM_API_KEY to override) in
# exactly one place instead of once per agent.


def test_connection(timeout=None):
    """Pre-flight check used by ``check_llm.py`` before a graded pipeline run.

    The Requirements Engineering instructions require the requirements JSON to be
    produced by Qwen and "not your Python program".  Without this check a missing
    or invalid key is only discovered *after* the Analyst stage, i.e. after the
    expensive IR-SIM benchmark has already run, and the pipeline would silently
    fall back to the deterministic implementation instead of failing loudly.

    Sends one minimal request that also asks for ``response_format=json_object``,
    because that is exactly what every agent in this pipeline relies on: a key
    that works but a model that rejects JSON mode would still break the run.

    The token budget is deliberately generous and doubled on retry: "thinking"
    models (qwen3 and friends) spend the budget on an internal reasoning block
    first, so a small ``max_tokens`` makes them return an *empty* message even
    though the request succeeded.  Reporting that as a hard failure would be
    wrong - it only means the budget was too small.

    Returns a dict describing the outcome; it never raises for an API problem, so
    the caller can report the precise cause.
    """
    backend = describe_backend()

    # A local model running on CPU needs far longer than a hosted API: qwen3:8b
    # on this machine takes ~50s for a JSON answer.  A tight default timeout
    # would make a working local backend look broken.
    if timeout is None:
        timeout = 300.0 if backend["kind"] in ("local", "custom") else 60.0

    result = {
        "model": MODEL,
        "base_url": BASE_URL,
        "backend": backend,
        "key_present": backend["credential_present"],
        "ok": False,
        "error": None,
        "detail": None,
        "reply": None,
        "empty_on_first_try": False,
        "timeout": timeout,
    }

    try:
        client = get_client()
    except Exception as error:  # missing key -> get_client already explains how to set it
        result["error"] = type(error).__name__
        result["detail"] = str(error)
        return result

    messages = [
        {"role": "system", "content": "Reply with a single JSON object."},
        {"role": "user", "content": 'Return exactly {"ok": true} as JSON.'},
    ]

    # 2048 is a ceiling, not a target: it costs nothing on a normal model and
    # leaves room for a reasoning block on a thinking model.
    for attempt, budget in enumerate((2048, 4096), start=1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                response_format={"type": "json_object"},
                messages=messages,
                temperature=0.0,
                max_tokens=budget,
                timeout=timeout,
            )
        except Exception as error:
            result["error"] = type(error).__name__
            status = getattr(error, "status_code", None)
            code = getattr(error, "code", None)
            message = " ".join(str(error).split())
            result["detail"] = " ".join(
                part for part in (
                    ("HTTP %s" % status) if status else "",
                    ("code=%s" % code) if code else "",
                    ("max_tokens=%d" % budget),
                    message[:300],
                ) if part
            )
            return result

        content = None
        try:
            content = (response.choices[0].message.content or "").strip()
        except Exception:
            content = ""

        if content:
            result["ok"] = True
            result["reply"] = content[:200]
            return result

        # Empty answer: almost always the reasoning block ate the whole budget.
        result["empty_on_first_try"] = True
        result["detail"] = (
            "the model returned an empty message with max_tokens=%d; retrying "
            "with a larger budget (thinking models spend it on reasoning first)"
            % budget
        )

    result["error"] = "EmptyResponse"
    return result


def _parse_json(text):
    """Parse the JSON returned by Qwen, tolerating stray code fences."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return json.loads(fence.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("Model response did not contain a valid JSON object.")


def validate_requirements(data):
    """Validate the requirements object returned by Qwen.

    Returns the validated data or raises ValueError describing the problem.
    """
    if not isinstance(data, dict):
        raise ValueError(
            "Requirements must be a JSON object (dict), got %s."
            % type(data).__name__
        )

    keys = set(data.keys())
    missing = REQUIRED_KEYS - keys
    extra = keys - REQUIRED_KEYS
    if missing:
        raise ValueError("Missing required key(s): %s" % sorted(missing))
    if extra:
        raise ValueError("Unexpected key(s) introduced by the model: %s" % sorted(extra))

    goal = data["goal"]
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError('"goal" must be a non-empty string.')

    actions = data["allowed_actions"]
    if not isinstance(actions, list) or not actions:
        raise ValueError('"allowed_actions" must be a non-empty list.')
    if not all(isinstance(action, str) for action in actions):
        raise ValueError('"allowed_actions" must contain only strings.')
    invalid = set(actions) - VALID_ACTIONS
    if invalid:
        raise ValueError(
            '"allowed_actions" contains invalid action(s): %s. '
            "Only FORWARD, LEFT, RIGHT, STOP are allowed." % sorted(invalid)
        )
    if set(actions) != VALID_ACTIONS:
        raise ValueError(
            '"allowed_actions" must contain exactly %s, got %s.'
            % (sorted(VALID_ACTIONS), sorted(set(actions)))
        )

    if not isinstance(data["safe_stop"], bool):
        raise ValueError('"safe_stop" must be a boolean.')
    if not isinstance(data["avoid_obstacles"], bool):
        raise ValueError('"avoid_obstacles" must be a boolean.')

    return data


def run_analyst(brief_text):
    """Send the brief to Qwen, parse and validate its JSON answer.

    Accepts the brief text as a parameter (it is called by another program),
    and returns the validated requirements dictionary.
    """
    client = get_client()
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = client.chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": brief_text},
            ],
            temperature=0.0,
        )
        raw_text = response.choices[0].message.content
        try:
            data = _parse_json(raw_text)
            return validate_requirements(data)
        except (json.JSONDecodeError, ValueError) as error:
            last_error = error
            print("[analyst_agent] attempt %d failed: %s" % (attempt, error))
    raise RuntimeError(
        "Analyst Agent failed to produce valid requirements after %d "
        "attempts. Last error: %s" % (MAX_ATTEMPTS, last_error)
    )
