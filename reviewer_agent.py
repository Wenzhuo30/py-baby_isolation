"""
reviewer_agent.py
=================
The Reviewer Agent for the navigation simulation.

It analyses ``artifacts/simulation_report.json`` (produced by runner.py), finds
the problems inside the report and recommends improvements. The output follows
a strict schema with exactly these keys:

{
  "issue": "string",
  "likely_cause": "string",
  "recommendation": "string",
  "needs_revision": true
}

A deterministic review is always computed from the measured report first, so
the pass/fail decision never depends on the LLM; the LLM only phrases the
issue, the likely cause and the recommendation.

Public API:
    SYSTEM_PROMPT
    validate_review(review)                   -> dict
    build_deterministic_review(report)        -> dict
    run_reviewer(simulation_report)           -> dict
    REVIEW_SCHEMA
"""

import json
import os
import re
import sys

from openai import OpenAI

MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_ATTEMPTS = 3

HERE = os.path.dirname(os.path.abspath(__file__))
SIMULATION_REPORT_PATH = os.path.join(HERE, "artifacts", "simulation_report.json")
REVIEW_PATH = os.path.join(HERE, "artifacts", "simulation_review.json")

REQUIRED_KEYS = ("issue", "likely_cause", "recommendation", "needs_revision")
BOOLEAN_KEYS = ("needs_revision",)
STRING_KEYS = ("issue", "likely_cause", "recommendation")

REVIEW_SCHEMA = {
    "issue": "(string) the most important problem found in the simulation report",
    "likely_cause": "(string) the most likely cause of that problem in the navigation logic",
    "recommendation": "(string) the concrete change the Developer Agent should make",
    "needs_revision": "(boolean) true when the navigation logic must be revised",
}

SYSTEM_PROMPT = """You are a reviewer (the "Reviewer Agent") for a mobile robot navigation system.

ROLE:
You receive the simulation report produced by runner.py. The report contains the
result of running decide_next_move(state) against every possible scenario of the
perception state, together with the counters total_scenarios, passed_scenarios,
failed_scenarios, success_rate, safety_violations, invalid_actions, exceptions
and failed_details.

TASK:
Analyse the report, identify the most important problem (if any) and recommend
how the navigation logic should be improved.

WHAT TO LOOK FOR, in this order of priority:
1. Safety violations: a decision that moves the robot into a blocked direction
   (reason "SAFETY_VIOLATION"). This is the most severe problem: the brief says
   the robot must never move into a blocked direction.
2. Exceptions or invalid actions (reason "EXCEPTION" / "INVALID_ACTION"):
   the function crashes or returns something other than FORWARD, LEFT, RIGHT, STOP.
3. Unexpected actions (reason "UNEXPECTED_ACTION"): the returned action does not
   follow the plan, e.g. the goal direction is safe but was not taken.
4. Preference mismatches: safe but not the reference priority (front, left, right).
   This is a minor issue and alone does not require a revision.
5. A success rate below 1.0 means the navigation logic does not satisfy the brief.

RULES:
1. Base every statement strictly on the numbers in the report. Never invent a
   problem that the report does not show.
2. "needs_revision" must be true when there is at least one failed scenario
   (failed_scenarios > 0) or a success rate below 1.0. When every scenario
   passes, "needs_revision" is false and you must say so in "issue".
3. "issue" and "likely_cause" must be short and specific (name the failing
   scenarios and the wrong action that was returned).
4. "recommendation" must be actionable for the Developer Agent that will rewrite
   decide_next_move.
5. Output valid JSON only. Do not output markdown, code fences, comments or any
   explanatory text.
6. The JSON object must contain EXACTLY these four keys:
   "issue" (string), "likely_cause" (string), "recommendation" (string),
   "needs_revision" (boolean).
"""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_review(data):
    """Validate the Reviewer Agent output.

    The output must be a JSON object with the required keys, ``needs_revision``
    must be a boolean and the remaining keys must be strings. Returns the
    validated data or raises ValueError describing the problem.
    """
    if not isinstance(data, dict):
        raise ValueError("Review must be a JSON object (dict), got %s."
                         % type(data).__name__)

    keys = set(data.keys())
    missing = set(REQUIRED_KEYS) - keys
    extra = keys - set(REQUIRED_KEYS)
    if missing:
        raise ValueError("Missing required key(s): %s" % sorted(missing))
    if extra:
        raise ValueError("Unexpected key(s) in review: %s" % sorted(extra))

    for key in STRING_KEYS:
        value = data[key]
        if not isinstance(value, str):
            raise ValueError('"%s" must be a string, got %s.'
                             % (key, type(value).__name__))
        if not value.strip():
            raise ValueError('"%s" must not be empty.' % key)

    for key in BOOLEAN_KEYS:
        if not isinstance(data[key], bool):
            raise ValueError('"%s" must be a boolean, got %s.'
                             % (key, type(data[key]).__name__))

    return data


# ---------------------------------------------------------------------------
# Deterministic review (ground truth from the measured report)
# ---------------------------------------------------------------------------
def build_deterministic_review(report):
    """Build the review from the measured simulation report.

    Returns a dict with the keys ``issue``, ``likely_cause``,
    ``recommendation`` and ``needs_revision``. Missing fields fall back to
    safe defaults so the function never crashes on an incomplete report.
    """
    if not isinstance(report, dict):
        report = {}

    total = int(report.get("total_scenarios") or 0)
    passed = int(report.get("passed_scenarios") or 0)
    failed = int(report.get("failed_scenarios") or 0)
    success_rate = report.get("success_rate")
    if success_rate is None:
        success_rate = (passed / total) if total else 0.0
    success_rate = float(success_rate)

    safety_violations = int(report.get("safety_violations") or 0)
    invalid_actions = int(report.get("invalid_actions") or 0)
    exceptions = int(report.get("exceptions") or 0)
    preference_mismatches = int(report.get("preference_mismatches") or 0)

    failed_details = report.get("failed_details") or []
    reasons = {}
    for detail in failed_details:
        reason = (detail or {}).get("reason") or "UNKNOWN"
        reasons[reason] = reasons.get(reason, 0) + 1

    def describe_failures(limit=3):
        parts = []
        for detail in failed_details[:limit]:
            parts.append("%s (%s -> %s, got %s)"
                         % (detail.get("name", "?"),
                            detail.get("expected", "?"),
                            detail.get("actual", "?"),
                            detail.get("reason", "?")))
        return "; ".join(parts)

    needs_revision = failed > 0 or success_rate < 1.0 or total == 0

    if not needs_revision:
        issue = ("No problem found: all %d scenarios passed (success rate %.2f)"
                 % (total, success_rate))
        likely_cause = ("The navigation logic correctly follows the plan: it never "
                        "moves into a blocked direction and prefers the goal direction.")
        recommendation = ("Keep the current decide_next_move implementation and "
                          "continue with the IR-SIM benchmark.")
        if preference_mismatches:
            recommendation += (" Note: %d scenario(s) used a safe but non-preferred "
                               "fallback direction instead of front > left > right."
                               % preference_mismatches)
        return {
            "issue": issue,
            "likely_cause": likely_cause,
            "recommendation": recommendation,
            "needs_revision": False,
        }

    if total == 0:
        return {
            "issue": "The simulation report contains no scenarios",
            "likely_cause": "The simulation runner did not execute decide_next_move",
            "recommendation": ("Re-run runner.py so that all 64 perception scenarios "
                               "are executed before reviewing."),
            "needs_revision": True,
        }

    if safety_violations > 0:
        issue = ("Unsafe navigation: %d of %d scenarios move the robot into a blocked "
                 "direction (success rate %.2f)" % (safety_violations, total, success_rate))
        likely_cause = ("The priority order inside decide_next_move checks the goal "
                        "direction before the blocked flags, or a blocked direction "
                        "is missing from the decision branches. Failing scenarios: %s"
                        % describe_failures())
        recommendation = ("Re-order decide_next_move so that a direction is only "
                          "chosen when its blocked flag is False (test every candidate "
                          "action with an explicit safety guard) and return STOP when "
                          "no safe direction is left.")
    elif exceptions > 0 or invalid_actions > 0:
        issue = ("%d scenario(s) crashed or returned an invalid action (%d exception(s), "
                 "%d invalid action(s))" % (exceptions + invalid_actions, exceptions,
                                            invalid_actions))
        likely_cause = ("decide_next_move does not handle every combination of the state "
                        "keys, or it returns a value outside FORWARD, LEFT, RIGHT, STOP. "
                        "Failing scenarios: %s" % describe_failures())
        recommendation = ("Make decide_next_move total over the six boolean state keys "
                          "(read every key defensively) and guarantee that only "
                          "FORWARD, LEFT, RIGHT or STOP is returned, defaulting to STOP.")
    elif reasons.get("UNEXPECTED_ACTION"):
        issue = ("%d of %d scenarios return an unexpected action (success rate %.2f)"
                 % (reasons.get("UNEXPECTED_ACTION", 0), total, success_rate))
        likely_cause = ("The goal-directed preference is not applied before the fallback "
                        "order, so a safe goal direction is ignored. Failing scenarios: %s"
                        % describe_failures())
        recommendation = ("Check the goal flags first: if goal_front/goal_left/goal_right is "
                          "True and the matching direction is not blocked, return "
                          "FORWARD/LEFT/RIGHT before falling back to any safe direction.")
    else:
        issue = ("%d of %d scenarios failed (success rate %.2f)"
                 % (failed, total, success_rate))
        likely_cause = ("The decision order in decide_next_move does not match the plan. "
                        "Failing scenarios: %s" % describe_failures())
        recommendation = ("Align decide_next_move with the plan: goal direction when safe, "
                          "then any safe direction (front, left, right), then STOP.")

    return {
        "issue": issue,
        "likely_cause": likely_cause,
        "recommendation": recommendation,
        "needs_revision": True,
    }


# ---------------------------------------------------------------------------
# Reviewer run
# ---------------------------------------------------------------------------
def _summarise_report(report):
    """Compact, JSON-safe summary of the report used inside the LLM prompt."""
    if not isinstance(report, dict):
        return json.dumps({"report": str(report)}, ensure_ascii=False)
    keep = (
        "policy_version", "total_scenarios", "passed_scenarios", "failed_scenarios",
        "success_rate", "safety_violations", "invalid_actions", "exceptions",
        "preference_mismatches", "status", "failed_details", "navigation_logic_path",
    )
    summary = {key: report[key] for key in keep if key in report}
    return json.dumps(summary, indent=2, ensure_ascii=False, default=str)


def run_reviewer(simulation_report, client=None, use_llm=True):
    """Review the simulation report and return the validated review dict.

    A deterministic review is computed from the measured report and is used as
    the ground truth for the pass/fail decision; the LLM phrases the issue, the
    likely cause and the recommendation whenever it is available.
    """
    deterministic = build_deterministic_review(simulation_report)

    if use_llm:
        try:
            llm_client = client if client is not None else get_client()
        except Exception as error:
            print("[reviewer_agent] LLM unavailable (%s); using the deterministic "
                  "review." % error)
            llm_client = None
    else:
        llm_client = None

    if llm_client is None:
        return validate_review(deterministic)

    user_prompt = (
        "SIMULATION REPORT (measured results):\n%s\n\n"
        "DETERMINISTIC REVIEW (ground truth for the four keys, produced from the "
        "measured report - keep the same booleans and the same meaning):\n%s\n\n"
        "Return the JSON object described in your instructions, using the measured "
        "numbers and the deterministic review above."
        % (_summarise_report(simulation_report),
           json.dumps(deterministic, indent=2, ensure_ascii=False))
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = llm_client.chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
        raw_text = response.choices[0].message.content
        try:
            data = _parse_json(raw_text)
            review = validate_review(data)
            # The measured report always wins over the model on the decision.
            review["needs_revision"] = bool(deterministic["needs_revision"])
            return validate_review(review)
        except (json.JSONDecodeError, ValueError) as error:
            print("[reviewer_agent] attempt %d failed: %s" % (attempt, error))

    print("[reviewer_agent] falling back to the deterministic review.")
    return validate_review(deterministic)


def save_review(review, path=None):
    """Persist the review as JSON and return the file path."""
    if path is None:
        path = REVIEW_PATH
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(review, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


# ---------------------------------------------------------------------------
# Helpers (same style as the other agents)
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


def _parse_json(text):
    """Parse the JSON returned by Qwen, tolerating stray code fences."""
    text = (text or "").strip()
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


def main(argv=None):
    """Standalone review of artifacts/simulation_report.json."""
    argv = list(sys.argv[1:] if argv is None else argv)
    report_path = argv[0] if argv else SIMULATION_REPORT_PATH

    with open(report_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)

    review = run_reviewer(report)
    path = save_review(review)
    print(json.dumps(review, indent=2, ensure_ascii=False))
    print("Saved review to %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
