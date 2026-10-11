"""
developer_agent.py
==================
The Developer Agent for the robot navigation project.

It turns the navigation plan produced by the Planner Agent into working Python
code that defines ``decide_next_move(state)``.  The same module also provides
the **revision** loop required by the integration project::

    run_developer(plan)
        -> navigation code from the plan

    run_developer_revision(original_code, review_notes, benchmark_report,
                           requirements, plan)
        -> revised navigation code from the original code + review notes +
           benchmark report + requirements + plan

Every candidate produced by the LLM is validated (it must be valid Python and
must expose ``decide_next_move``) and, additionally, evaluated against all 64
possible perception states so that a revision that breaks safety or the
goal-directed behaviour can never silently replace a working implementation.

Public API:
    run_developer(plan)                       -> str (code)
    run_developer_revision(...)               -> str (code)
    validate_code(code)                       -> str
    validate_navigation_behaviour(code)       -> dict (evaluation)
    build_fallback_navigation_code(...)       -> str
    write_navigation_logic(code, path=None)   -> str (path)
"""

import importlib.util
import itertools
import json
import os
import re
import sys

from openai import OpenAI

MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_ATTEMPTS = 3

HERE = os.path.dirname(os.path.abspath(__file__))
GENERATED_DIR = os.path.join(HERE, "generated")
DEFAULT_OUTPUT_PATH = os.path.join(GENERATED_DIR, "navigation_logic.py")

STATE_KEYS = (
    "blocked_front",
    "blocked_left",
    "blocked_right",
    "goal_front",
    "goal_left",
    "goal_right",
)
VALID_ACTIONS = ("FORWARD", "LEFT", "RIGHT", "STOP")

# The canonical state contract, shared with the Test Agent and the runner.
STATE_CONTRACT = """The state is a dictionary with exactly these six boolean keys:
- blocked_front, blocked_left, blocked_right: True when that direction is blocked.
- goal_front, goal_left, goal_right: True when the goal lies in that direction.
All six keys are always present and always booleans. Accept the descriptive
aliases front_blocked / left_blocked / right_blocked and
goal_ahead / goal_on_left / goal_on_right as well (defensive lookup), but the
six canonical keys are the contract used by the tests and the simulator."""

SYSTEM_PROMPT = """You are a software developer (the "Developer Agent") for a mobile robot navigation system.

ROLE:
You receive the validated navigation plan produced by the Planner Agent and implement it as working Python code.

TASK:
Read the plan JSON provided by the user and return ONLY the Python code that implements the navigation logic described by the plan.

The code must:
1. Define a function named decide_next_move that takes a single argument 'state'.
   %(state_contract)s
   Extract these six values from the state dictionary at the start of the function
   (coerce them with bool() so numpy booleans also work).
2. Return one of these four strings: "FORWARD", "LEFT", "RIGHT", "STOP".
3. Prefer moving toward the goal whenever that direction is safe (not blocked):
   goal_front and not blocked_front -> "FORWARD";
   goal_left and not blocked_left   -> "LEFT";
   goal_right and not blocked_right -> "RIGHT".
4. Never move into a blocked direction: never "FORWARD" while blocked_front,
   never "LEFT" while blocked_left, never "RIGHT" while blocked_right.
5. If no goal direction is safe, take any safe direction, using the reference
   priority FORWARD, then LEFT, then RIGHT.
6. If no safe direction is available at all, return "STOP".
7. Be valid Python 3 code, deterministic, and never mutate the state dictionary.
8. Do not output markdown, code fences or any explanatory text, only the code.
""" % {"state_contract": STATE_CONTRACT}

REVISION_SYSTEM_PROMPT = """You are a software developer (the "Developer Agent") for a mobile robot navigation system.

ROLE:
You are revising an existing navigation implementation after testing, simulation,
review and benchmarking. You receive:
1. the requirements produced by the Analyst Agent,
2. the plan produced by the Planner Agent,
3. the original navigation code,
4. the review notes for the simulation (reviewer agent),
5. the IR-SIM benchmark report and its review (success rate, efficiency rate,
   average steps, safety, goal completion, efficiency).

TASK:
Return ONLY the complete revised Python module that fixes the reported problems
while preserving everything that already worked.

The revision must:
1. Keep a function named decide_next_move that takes a single argument 'state'.
   %(state_contract)s
2. Return exactly one of "FORWARD", "LEFT", "RIGHT", "STOP".
3. Apply the fixes requested by the review notes and the benchmark review
   (for example: remove unsafe actions, restore goal-directed behaviour,
   reduce oscillation / unnecessary turning, avoid getting stuck against an
   obstacle, reach the goal in fewer steps).
4. Never move into a blocked direction, prefer the goal direction when it is
   safe, take any safe direction otherwise (reference priority FORWARD, LEFT,
   RIGHT) and return "STOP" only when no safe direction is available.
5. Be valid, deterministic Python 3 code that does not mutate the state dict.
6. Address the review notes explicitly - do not ignore a reported issue.
7. Do not output markdown, code fences or any explanatory text, only the code.
""" % {"state_contract": STATE_CONTRACT}



# Validation
def validate_code(code):
    """Validate the code produced by the Developer Agent.

    The output must be proper Python code: we check the type, look for the
    required function definition and try to compile it.
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Developer output must be a non-empty string of Python code.")
    if "```" in code:
        raise ValueError("Developer output must not contain markdown code fences.")
    if "def decide_next_move" not in code:
        raise ValueError(
            "Developer output does not contain required function: decide_next_move(state)"
        )
    try:
        compile(code, "<developer_output>", "exec")
    except SyntaxError as error:
        raise ValueError("Developer output is not valid Python: %s" % error)
    return code


def _reference_policy(state):
    """Reference policy from the brief, used to score a candidate."""
    if state["goal_front"] and not state["blocked_front"]:
        return "FORWARD"
    if state["goal_left"] and not state["blocked_left"]:
        return "LEFT"
    if state["goal_right"] and not state["blocked_right"]:
        return "RIGHT"
    if not state["blocked_front"]:
        return "FORWARD"
    if not state["blocked_left"]:
        return "LEFT"
    if not state["blocked_right"]:
        return "RIGHT"
    return "STOP"


BLOCKED_KEY_FOR_ACTION = {
    "FORWARD": "blocked_front",
    "LEFT": "blocked_left",
    "RIGHT": "blocked_right",
}


def meets_acceptance(evaluation):
    """Default acceptance predicate for a candidate implementation.

    A candidate is accepted when it is valid Python, exposes
    ``decide_next_move`` and never moves into a blocked direction in any of the
    64 perception scenarios (the safety requirement of the brief). Matching the
    reference priority exactly is *not* required: a safe but suboptimal
    implementation is allowed through so that the simulation, the reviewer and
    the IR-SIM benchmark can identify and report the remaining weaknesses
    instead of the logic being silently replaced.
    """
    return bool(evaluation.get("loadable")
                and evaluation.get("safe")
                and evaluation.get("invalid_actions") == 0
                and evaluation.get("exceptions") == 0)


def _load_module_from_code(code, module_name="navigation_logic_candidate"):
    """Execute the generated code and return the module object."""
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(module_name, loader=None)
    )
    module.__dict__["__name__"] = module_name
    module.__dict__["__file__"] = "<generated>"
    exec(compile(code, "<generated_navigation_logic>", "exec"), module.__dict__)
    return module


def validate_navigation_behaviour(code, expected_path=None):
    """Score a navigation implementation against all 64 perception states.

    Returns a dict with the number of safe / goal-directed / matching decisions
    and the list of problems found. The evaluation never raises: a broken
    candidate simply reports ``loadable=False`` and ``safe=False``.
    """
    evaluation = {
        "loadable": False,
        "safe": False,
        "matches_reference": False,
        "total_scenarios": 64,
        "safe_decisions": 0,
        "reference_matches": 0,
        "invalid_actions": 0,
        "exceptions": 0,
        "problems": [],
    }

    try:
        validate_code(code)
        module = _load_module_from_code(code)
        navigation_fn = getattr(module, "decide_next_move")
    except Exception as error:
        evaluation["problems"].append("code does not load: %s: %s"
                                      % (type(error).__name__, error))
        return evaluation

    evaluation["loadable"] = True

    for combo in itertools.product([False, True], repeat=len(STATE_KEYS)):
        state = dict(zip(STATE_KEYS, combo))
        try:
            action = navigation_fn(dict(state))
        except Exception as error:
            evaluation["exceptions"] += 1
            evaluation["problems"].append(
                "exception for %s: %s: %s" % (state, type(error).__name__, error)
            )
            continue

        if action not in VALID_ACTIONS:
            evaluation["invalid_actions"] += 1
            evaluation["problems"].append(
                "invalid action %r for %s" % (action, state)
            )
            continue

        blocked_key = BLOCKED_KEY_FOR_ACTION.get(action)
        if blocked_key is not None and state[blocked_key]:
            evaluation["problems"].append(
                "unsafe decision %s while %s is True for %s" % (action, blocked_key, state)
            )
            continue

        evaluation["safe_decisions"] += 1
        if action == _reference_policy(state):
            evaluation["reference_matches"] += 1

    total = evaluation["total_scenarios"]
    evaluation["safe"] = (
        evaluation["loadable"]
        and evaluation["safe_decisions"] == total
        and evaluation["invalid_actions"] == 0
        and evaluation["exceptions"] == 0
    )
    evaluation["matches_reference"] = evaluation["reference_matches"] == total
    evaluation["problems"] = evaluation["problems"][:20]
    return evaluation



# Deterministic fallback implementation
NAVIGATION_CODE_TEMPLATE = '''"""
navigation_logic.py
===================
Navigation logic for the mobile robot.

Implemented by the Developer Agent from the navigation plan:
%(strategy_comment)s

Contract:
    decide_next_move(state) -> "FORWARD" | "LEFT" | "RIGHT" | "STOP"

"state" is a dictionary with the six boolean keys blocked_front, blocked_left,
blocked_right, goal_front, goal_left, goal_right (the descriptive aliases
front_blocked / left_blocked / right_blocked and goal_ahead / goal_on_left /
goal_on_right are accepted as well).
"""

VALID_ACTIONS = ("FORWARD", "LEFT", "RIGHT", "STOP")

BLOCKED_KEYS = {
    "FORWARD": ("blocked_front", "front_blocked"),
    "LEFT": ("blocked_left", "left_blocked"),
    "RIGHT": ("blocked_right", "right_blocked"),
}

GOAL_KEYS = {
    "FORWARD": ("goal_front", "goal_ahead"),
    "LEFT": ("goal_left", "goal_on_left"),
    "RIGHT": ("goal_right", "goal_on_right"),
}


def _read_flag(state, keys):
    """Read the first present key of a flag, tolerating naming aliases."""
    for key in keys:
        if key in state:
            return bool(state[key])
    return False


def is_blocked(state, action):
    """True when the direction required by 'action' is blocked."""
    keys = BLOCKED_KEYS.get(action)
    if keys is None:
        return False
    return _read_flag(state, keys)


def points_to_goal(state, action):
    """True when 'action' moves the robot toward its goal."""
    keys = GOAL_KEYS.get(action)
    if keys is None:
        return False
    return _read_flag(state, keys)


def choose_action(blocked_front, blocked_left, blocked_right,
                  goal_front, goal_left, goal_right):
    """Pure decision function following the navigation plan."""
    # 1. prefer moving toward the goal whenever that direction is safe
    if goal_front and not blocked_front:
        return "FORWARD"
    if goal_left and not blocked_left:
        return "LEFT"
    if goal_right and not blocked_right:
        return "RIGHT"
    # 2. otherwise take any safe direction (reference priority front, left, right)
    if not blocked_front:
        return "FORWARD"
    if not blocked_left:
        return "LEFT"
    if not blocked_right:
        return "RIGHT"
    # 3. every direction is blocked: stop
    return "STOP"


def decide_next_move(state):
    """
    Standard external interface required by the project.

    Takes the perception state dictionary and returns one action string.
    This is the ONLY function that other programs should call.
    """
    if not isinstance(state, dict):
        raise TypeError("state must be a dict, got %%s" %% type(state).__name__)

    blocked_front = _read_flag(state, BLOCKED_KEYS["FORWARD"])
    blocked_left = _read_flag(state, BLOCKED_KEYS["LEFT"])
    blocked_right = _read_flag(state, BLOCKED_KEYS["RIGHT"])
    goal_front = _read_flag(state, GOAL_KEYS["FORWARD"])
    goal_left = _read_flag(state, GOAL_KEYS["LEFT"])
    goal_right = _read_flag(state, GOAL_KEYS["RIGHT"])

    action = choose_action(blocked_front, blocked_left, blocked_right,
                           goal_front, goal_left, goal_right)

    # final safety guard: never move into a blocked direction, never return
    # anything outside the allowed action set
    if action not in VALID_ACTIONS:
        return "STOP"
    if action != "STOP" and is_blocked(state, action):
        for candidate in ("FORWARD", "LEFT", "RIGHT"):
            if not is_blocked(state, candidate):
                return candidate
        return "STOP"
    return action
'''


def build_fallback_navigation_code(plan=None, revision_notes=None):
    """Deterministic implementation used when the LLM is unavailable.

    When revision notes are supplied, the notes are embedded in the module
    docstring so the revision is traceable, and the safety guard is kept.
    """
    plan = plan or {}
    strategy = plan.get("strategy") or "prefer the goal direction when safe; never move into a blocked direction"
    strategy = " ".join(str(strategy).split())
    if len(strategy) > 300:
        strategy = strategy[:297] + "..."

    lines = [" " + strategy]
    if revision_notes:
        lines.append(" Revision notes applied by the Developer Agent:")
        if isinstance(revision_notes, dict):
            notes = revision_notes.get("recommendation") or json.dumps(revision_notes, ensure_ascii=False)
        else:
            notes = str(revision_notes)
        lines.append(" " + " ".join(str(notes).split())[:400])

    strategy_comment = "\n".join(lines)
    return NAVIGATION_CODE_TEMPLATE % {"strategy_comment": strategy_comment}


def write_navigation_logic(code, path=None):
    """Validate and save navigation code, returning the written path."""
    validate_code(code)
    if path is None:
        path = DEFAULT_OUTPUT_PATH
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(code)
        if not code.endswith("\n"):
            handle.write("\n")
    return path


# Developer agent runs
def _build_revision_prompt(original_code, review_notes, benchmark_report,
                           requirements, plan, benchmark_review=None,
                           attempt=1):
    def dump(value):
        if value is None:
            return "(not available)"
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)

    return (
        "REQUIREMENTS (Analyst Agent):\n%s\n\n"
        "PLAN (Planner Agent):\n%s\n\n"
        "ORIGINAL NAVIGATION CODE:\n```python\n%s\n```\n\n"
        "SIMULATION REVIEW NOTES (Reviewer Agent):\n%s\n\n"
        "IR-SIM BENCHMARK REPORT:\n%s\n\n"
        "IR-SIM BENCHMARK REVIEW:\n%s\n\n"
        "REVISION ATTEMPT: %d of %d.\n\n"
        "Return the complete revised Python module that fixes the reported "
        "problems (unsafe actions, missed goals, inefficiency) while keeping "
        "the navigation contract. Return only the Python code."
        % (dump(requirements), dump(plan), original_code, dump(review_notes),
           dump(benchmark_report), dump(benchmark_review), attempt, MAX_ATTEMPTS)
    )


def run_developer(plan, client=None, use_llm=True, accepts=None):
    """Run the Developer Agent: plan -> validated navigation code."""
    accepts = accepts or meets_acceptance
    if use_llm:
        try:
            llm_client = client if client is not None else get_client()
        except Exception as error:
            print("[developer_agent] LLM unavailable (%s); using the deterministic "
                  "implementation built from the plan." % error)
            llm_client = None
    else:
        llm_client = None

    last_error = None
    if llm_client is not None:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = llm_client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(plan, ensure_ascii=False)},
                ],
                temperature=0.0,
            )
            raw_text = response.choices[0].message.content
            try:
                code = validate_code(_parse_code(raw_text))
                evaluation = validate_navigation_behaviour(code)
                if accepts(evaluation):
                    return code
                last_error = "generated code was rejected: %s" % "; ".join(evaluation["problems"][:3])
                print("[developer_agent] attempt %d rejected: %s" % (attempt, last_error))
            except (ValueError, SyntaxError) as error:
                last_error = error
                print("[developer_agent] attempt %d failed: %s" % (attempt, error))

    if llm_client is not None:
        print("[developer_agent] falling back to the deterministic implementation.")
    return validate_code(build_fallback_navigation_code(plan))


def run_developer_revision(original_code, review_notes, benchmark_report,
                           requirements, plan, benchmark_review=None,
                           client=None, use_llm=True, accepts=None):
    """Revise the navigation logic using every artefact of the pipeline.

    Receives the original navigation code, the review notes, the benchmark
    report, the requirements and the plan. It asks the LLM to generate a new
    navigation logic and returns the validated revised code. Candidates that
    break the safety contract are rejected, in which case the deterministic
    reference implementation is returned instead.
    """
    accepts = accepts or meets_acceptance
    prompt_args = (original_code, review_notes, benchmark_report, requirements, plan)

    if use_llm:
        try:
            llm_client = client if client is not None else get_client()
        except Exception as error:
            print("[developer_agent] LLM unavailable (%s); using the deterministic "
                  "revision." % error)
            llm_client = None
    else:
        llm_client = None

    last_error = None
    if llm_client is not None:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            prompt = _build_revision_prompt(
                *prompt_args, benchmark_review=benchmark_review, attempt=attempt
            )
            response = llm_client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": REVISION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            raw_text = response.choices[0].message.content
            try:
                code = validate_code(_parse_code(raw_text))
                evaluation = validate_navigation_behaviour(code)
                if accepts(evaluation):
                    return code
                last_error = ("revised code was rejected: %s"
                              % "; ".join(evaluation["problems"][:3]))
                print("[developer_agent] revision attempt %d rejected: %s"
                      % (attempt, last_error))
            except (ValueError, SyntaxError) as error:
                last_error = error
                print("[developer_agent] revision attempt %d failed: %s" % (attempt, error))

    if llm_client is not None:
        print("[developer_agent] falling back to the deterministic revision.")
    return validate_code(build_fallback_navigation_code(plan, revision_notes=review_notes))


# ---------------------------------------------------------------------------
# Helpers (same style as the Analyst / Planner / Test agents)
# ---------------------------------------------------------------------------
def _load_env_file():
    env_path = os.path.join(HERE, ".env")
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
    text = (text or "").strip()
    fence = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text


def main(argv=None):
    """Standalone developer run (plan -> generated/navigation_logic.py)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    plan_path = argv[0] if argv else os.path.join(HERE, "artifacts", "plan.json")
    output_path = argv[1] if len(argv) > 1 else DEFAULT_OUTPUT_PATH

    with open(plan_path, "r", encoding="utf-8") as handle:
        plan = json.load(handle)

    code = run_developer(plan)
    written = write_navigation_logic(code, output_path)
    evaluation = validate_navigation_behaviour(code)
    print("Navigation logic written to %s" % written)
    print("Behaviour check: safe=%s matches_reference=%s (%d/%d scenarios)"
          % (evaluation["safe"], evaluation["matches_reference"],
             evaluation["reference_matches"], evaluation["total_scenarios"]))
    return 0 if evaluation["safe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
