import json
import os
import re
from openai import OpenAI

## The logic is fairly similar to the Analyst and Planner agents
MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_ATTEMPTS = 3

SYSTEM_PROMPT = """You are a software developer (the "Developer Agent") for a mobile robot navigation system.
ROLE:
You receive the validated navigation plan produced by the Planner Agent and implement it as working Python code.
TASK:
Read the plan JSON provided by the user and return ONLY the Python code that implements the navigation logic described by the plan.
The code must:
1. Define a function named decide_next_move that takes a single argument 'state'.
   The 'state' is a dictionary containing six boolean keys: blocked_front, blocked_left, blocked_right, goal_front, goal_left, goal_right.
   Extract these six values from the state dictionary at the start of the function.
2. Return one of these four strings: "FORWARD", "LEFT", "RIGHT", "STOP".
3. Prefer moving toward the goal whenever that direction is safe (not blocked).
4. Never move into a blocked direction.
5. If no safe direction is available, return "STOP".
6. Be valid Python 3 code. Do not output markdown, code fences or any explanatory text, only the code.
"""

## Function to validate the output of the Developer Agent.
## The output must be proper Python code, so we check the type, look for a
## function definition and try to compile it.
def validate_code(code):
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Developer output must be a non-empty string of Python code.")
    if "def decide_next_move" not in code:
        raise ValueError("Developer output does not contain required function: decide_next_move(state)")
    try:
        compile(code, "<developer_output>", "exec")
    except SyntaxError as error:
        raise ValueError("Developer output is not valid Python: %s" % error)
    return code

## Function to run the Developer Agent.
## It takes the validated plan as input, sends it to the Developer Agent (Qwen),
## parses and validates the returned code, and returns it.
def run_developer(plan):
    client = get_client()
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(plan, ensure_ascii=False)},
            ],
            temperature=0.0,
        )
        raw_text = response.choices[0].message.content
        try:
            code = _parse_code(raw_text)
            return validate_code(code)
        except (ValueError, SyntaxError) as error:
            last_error = error
            print("[developer_agent] attempt %d failed: %s" % (attempt, error))
    raise RuntimeError(
        "Developer Agent failed to produce valid code after %d "
        "attempts. Last error: %s" % (MAX_ATTEMPTS, last_error)
    )

## Same helper functions as the Analyst and Planner agents.
def _load_env_file():
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

def _parse_code(text):
    """Strip markdown code fences if Qwen wraps the code in them."""
    text = text.strip()
    fence = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text
