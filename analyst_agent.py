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
"""

import json
import os
import re

from openai import OpenAI

# Qwen model used for the analysis (override with the QWEN_MODEL env var).
MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

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


def _load_env_file():
    """Load KEY=VALUE pairs from a .env file located next to this script.

    This is a tiny, dependency-free loader so the API key can be configured
    without installing python-dotenv. Existing environment variables win.
    """
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


def get_client():
    """Build an OpenAI-compatible client pointed at the Qwen API."""
    _load_env_file()
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DASHSCOPE_API_KEY is not set. Configure it before running:\n"
            '  PowerShell : $env:DASHSCOPE_API_KEY = "sk-..."\n'
            '  bash       : export DASHSCOPE_API_KEY="sk-..."\n'
            "or put  DASHSCOPE_API_KEY=sk-...  in a .env file next to this script."
        )
    return OpenAI(api_key=api_key, base_url=BASE_URL)


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
