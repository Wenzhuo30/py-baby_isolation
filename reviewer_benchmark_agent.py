"""
reviewer_benchmark_agent.py
===========================
The Benchmark Reviewer Agent.

It reviews ``artifacts/irsim_benchmark_report.json`` (produced by
benchmark_irsim.py) in the same way reviewer_agent.py reviews the simulation
report, but with the *quality requirements* of the brief:

    safety            - no world may collide or terminate without reaching the goal
                        (any world with collision_or_done True while reached_goal
                        is False is an unsafe run)
    goal completion   - success_rate must be 1.0
    efficiency        - no successful-but-inefficient world and efficiency_rate 1.0

The output follows a strict schema with exactly these keys:

{
  "issue": "string",
  "likely_cause": "string",
  "recommendation": "string",
  "safety_passed": true,
  "goal_completion_passed": true,
  "efficiency_passed": true,
  "needs_revision": true
}

The booleans are always derived deterministically from the measured benchmark
figures (build_deterministic_review); the LLM only phrases the issue, the
likely cause and the recommendation. The output is saved to
``artifacts/irsim_benchmark_review.json``.

Public API:
    SYSTEM_PROMPT
    validate_review(review)                       -> dict
    build_deterministic_review(benchmark_report)  -> dict
    run_benchmark_reviewer(benchmark_report)      -> dict
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
BENCHMARK_REPORT_PATH = os.path.join(HERE, "artifacts", "irsim_benchmark_report.json")
BENCHMARK_REVIEW_PATH = os.path.join(HERE, "artifacts", "irsim_benchmark_review.json")

REQUIRED_KEYS = (
    "issue",
    "likely_cause",
    "recommendation",
    "safety_passed",
    "goal_completion_passed",
    "efficiency_passed",
    "needs_revision",
)
BOOLEAN_KEYS = (
    "safety_passed",
    "goal_completion_passed",
    "efficiency_passed",
    "needs_revision",
)
STRING_KEYS = ("issue", "likely_cause", "recommendation")

REVIEW_SCHEMA = {
    "issue": "(string) the most important quality problem found in the benchmark report",
    "likely_cause": "(string) the most likely cause in the navigation logic",
    "recommendation": "(string) the concrete fix for the Developer Agent",
    "safety_passed": "(boolean) no unsafe world (collision_or_done without reached_goal)",
    "goal_completion_passed": "(boolean) success_rate is 1.0",
    "efficiency_passed": "(boolean) no inefficient successful world and efficiency_rate is 1.0",
    "needs_revision": "(boolean) any of the three quality requirements failed",
}

SYSTEM_PROMPT = """You are a quality reviewer (the "Benchmark Reviewer Agent") for a mobile robot navigation system.

ROLE:
You receive the IR-SIM benchmark report produced by benchmark_irsim.py. It
contains, for every simulated world: reached_goal, collision_or_done, steps_taken,
efficiency_status and efficiency_passed, plus the summary fields total_worlds,
goals_reached, success_rate, efficient_worlds, inefficient_success_worlds,
failed_worlds, efficiency_rate and average_steps_taken.

TASK:
Review the benchmark against the three quality requirements of the brief and
recommend what should be done next (including whether the navigation logic must
be revised).

QUALITY REQUIREMENTS:
1. SAFETY: the robot must never crash into an obstacle and must never terminate
   without reaching the goal. Safety fails when any world has
   collision_or_done = true while reached_goal = false.
2. GOAL COMPLETION: the robot must reach the goal in every world, i.e.
   success_rate must be 1.0 (goals_reached == total_worlds).
3. EFFICIENCY: the robot must reach the goal efficiently, i.e.
   inefficient_success_worlds must be 0 and efficiency_rate must be 1.0
   (a world with more than the efficient step limit counts as successful but
   inefficient).

RULES:
1. Base every statement strictly on the measured numbers in the report. Never
   invent a problem the report does not show. Quote the world names.
2. The three booleans and "needs_revision" must match the deterministic review
   you are given: safety_passed, goal_completion_passed and efficiency_passed
   from the measured figures, and needs_revision = NOT (all three passed).
3. Specify precisely which world failed and what the measured value was.
4. "recommendation" must state the concrete change for the Developer Agent, e.g.
   "increase the obstacle clearance in decide_next_move" or
   "reduce oscillation by keeping the current heading when the goal is ahead".
5. Output valid JSON only. Do not output markdown, code fences, comments or any
   explanatory text.
6. The JSON object must contain EXACTLY these seven keys:
   "issue" (string), "likely_cause" (string), "recommendation" (string),
   "safety_passed" (boolean), "goal_completion_passed" (boolean),
   "efficiency_passed" (boolean), "needs_revision" (boolean).
"""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_review(data):
    """Validate the Benchmark Reviewer output.

    The output must be a JSON object with the required keys,
    ``safety_passed``, ``goal_completion_passed``, ``efficiency_passed`` and
    ``needs_revision`` must be booleans and the remaining keys must be strings.
    Raises ValueError when the output does not meet these criteria.
    """
    if not isinstance(data, dict):
        raise ValueError("Benchmark review must be a JSON object (dict), got %s."
                         % type(data).__name__)

    keys = set(data.keys())
    missing = set(REQUIRED_KEYS) - keys
    extra = keys - set(REQUIRED_KEYS)
    if missing:
        raise ValueError("Missing required key(s): %s" % sorted(missing))
    if extra:
        raise ValueError("Unexpected key(s) in benchmark review: %s" % sorted(extra))

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
# Deterministic review (measured quality gates)
# ---------------------------------------------------------------------------
def _unsafe_worlds(benchmark_report):
    """Worlds that collided or terminated without reaching the goal."""
    unsafe = []
    for result in benchmark_report.get("results") or []:
        if not isinstance(result, dict):
            continue
        reached_goal = bool(result.get("reached_goal"))
        collision_or_done = bool(result.get("collision_or_done"))
        if collision_or_done and not reached_goal:
            unsafe.append(result)
    return unsafe


def build_deterministic_review(benchmark_report):
    """Build the review from the measured benchmark report.

    Returns a dict with the keys ``issue``, ``likely_cause``,
    ``recommendation``, ``safety_passed``, ``goal_completion_passed``,
    ``efficiency_passed`` and ``needs_revision``. Missing report fields fall
    back to safe defaults so the function never crashes.
    """
    if not isinstance(benchmark_report, dict):
        benchmark_report = {}

    results = benchmark_report.get("results") or []
    total = int(benchmark_report.get("total_worlds") or len(results) or 0)
    goals_reached = int(benchmark_report.get("goals_reached") or 0)

    success_rate = benchmark_report.get("success_rate")
    if success_rate is None:
        success_rate = (goals_reached / total) if total else 0.0
    success_rate = float(success_rate)

    efficient_worlds = int(benchmark_report.get("efficient_worlds") or 0)
    inefficient_success_worlds = int(benchmark_report.get("inefficient_success_worlds") or 0)
    failed_worlds = int(benchmark_report.get("failed_worlds") or 0)

    efficiency_rate = benchmark_report.get("efficiency_rate")
    if efficiency_rate is None:
        efficiency_rate = (efficient_worlds / total) if total else 0.0
    efficiency_rate = float(efficiency_rate)

    average_steps = float(benchmark_report.get("average_steps_taken") or 0.0)

    unsafe = _unsafe_worlds(benchmark_report)

    # --- the three quality gates -----------------------------------------
    safety_passed = len(unsafe) == 0 and total > 0
    goal_completion_passed = success_rate >= 1.0 and total > 0
    efficiency_passed = (
        total > 0
        and inefficient_success_worlds == 0
        and efficiency_rate >= 1.0
    )
    needs_revision = not (safety_passed and goal_completion_passed and efficiency_passed)

    issues = []
    causes = []
    recommendations = []

    if total == 0:
        issues.append("The benchmark report contains no worlds")
        causes.append("benchmark_irsim.py did not run any IR-SIM world")
        recommendations.append("Run benchmark_irsim.py so that every world file in "
                               "irsim_worlds/ is simulated before reviewing.")
        return {
            "issue": "The benchmark report contains no worlds",
            "likely_cause": "benchmark_irsim.py did not run any IR-SIM world",
            "recommendation": recommendations[0],
            "safety_passed": False,
            "goal_completion_passed": False,
            "efficiency_passed": False,
            "needs_revision": True,
        }

    # --- safety -----------------------------------------------------------
    if not safety_passed:
        names = ", ".join(os.path.basename(str(w.get("world_file", "?"))) for w in unsafe)
        issues.append("Unsafe benchmark behavior detected in %d/%d world(s): %s "
                      "(collision_or_done=True while reached_goal=False)"
                      % (len(unsafe), total, names))
        causes.append("The robot collides with an obstacle or terminates before "
                      "reaching the goal, which means decide_next_move either "
                      "selects a blocked direction or has no recovery move when it "
                      "gets stuck in front of an obstacle.")
        recommendations.append("Add obstacle clearance and a recovery strategy to "
                               "decide_next_move: never choose a blocked direction, "
                               "and when the goal direction is blocked, turn into a "
                               "free direction until the front is free again.")

    # --- goal completion --------------------------------------------------
    if not goal_completion_passed:
        failing = [r for r in results
                   if isinstance(r, dict) and not r.get("reached_goal")]
        names = ", ".join(os.path.basename(str(r.get("world_file", "?"))) for r in failing) or "n/a"
        issues.append("Goal completion failure: %d/%d world(s) reached the goal "
                      "(success_rate=%.2f, failing worlds: %s)"
                      % (goals_reached, total, success_rate, names))
        causes.append("The robot does not reach the goal in %s; it either stops too "
                      "early (STOP while a safe direction exists), oscillates between "
                      "two directions, or gets trapped in a local minimum around an "
                      "obstacle." % names)
        recommendations.append("Fix the goal-directed fallback in decide_next_move so "
                               "the robot always keeps making progress (prefer the "
                               "goal direction when safe, otherwise take the safest "
                               "direction, and never return STOP while a direction is "
                               "free).")

    # --- efficiency -------------------------------------------------------
    if not efficiency_passed:
        inefficient_names = [
            os.path.basename(str(r.get("world_file", "?")))
            for r in results
            if isinstance(r, dict) and r.get("reached_goal")
            and str(r.get("efficiency_status")) != "efficient"
        ]
        issues.append("Successful but inefficient navigation: %d world(s) above the "
                      "efficient step limit and efficiency_rate=%.2f, average steps=%.1f%s"
                      % (inefficient_success_worlds, efficiency_rate, average_steps,
                         (" (%s)" % ", ".join(inefficient_names)) if inefficient_names else ""))
        causes.append("The robot takes too many steps because it turns, re-checks and "
                      "turns back instead of driving a straight line toward the goal, "
                      "so it wastes the step budget on corrections.")
        recommendations.append("Reduce oscillation: keep driving FORWARD while the goal "
                               "is ahead and the front is clear, turn only by the "
                               "smallest needed amount, and avoid alternating LEFT and "
                               "RIGHT between consecutive steps.")

    if issues:
        issue = " | ".join(issues)
        likely_cause = " ".join(causes)
        recommendation = " ".join(recommendations)
    else:
        issue = ("No problem found: all %d worlds reached the goal safely and "
                 "efficiently (success_rate=%.2f, efficiency_rate=%.2f, "
                 "average steps=%.1f)" % (total, success_rate, efficiency_rate, average_steps))
        likely_cause = ("The navigation logic satisfies the quality requirements: it "
                        "never collides, always reaches the goal and stays below the "
                        "efficient step limit.")
        recommendation = ("Keep the current decide_next_move implementation and "
                          "archive the benchmark report as evidence.")

    return {
        "issue": issue,
        "likely_cause": likely_cause,
        "recommendation": recommendation,
        "safety_passed": bool(safety_passed),
        "goal_completion_passed": bool(goal_completion_passed),
        "efficiency_passed": bool(efficiency_passed),
        "needs_revision": bool(needs_revision),
    }


# ---------------------------------------------------------------------------
# Reviewer run
# ---------------------------------------------------------------------------
def _summarise_report(report):
    """Compact, JSON-safe summary of the benchmark report for the LLM prompt."""
    if not isinstance(report, dict):
        return json.dumps({"report": str(report)}, ensure_ascii=False)

    keep = (
        "total_worlds", "goals_reached", "success_rate", "efficient_worlds",
        "inefficient_success_worlds", "failed_worlds", "efficiency_rate",
        "average_steps_taken", "efficient_step_limit", "max_steps_allowed",
        "navigation_logic",
    )
    summary = {key: report[key] for key in keep if key in report}
    summary["world_results"] = [
        {
            "world_file": r.get("world_file"),
            "reached_goal": r.get("reached_goal"),
            "collision_or_done": r.get("collision_or_done"),
            "steps_taken": r.get("steps_taken"),
            "efficiency_status": r.get("efficiency_status"),
        }
        for r in (report.get("results") or []) if isinstance(r, dict)
    ]
    return json.dumps(summary, indent=2, ensure_ascii=False, default=str)


def run_benchmark_reviewer(benchmark_report, client=None, use_llm=True):
    """Review the benchmark report and return the validated review dict.

    A deterministic review is built from the measured benchmark report and is
    used as the ground truth for the four booleans; the LLM phrases the issue,
    the likely cause and the recommendation whenever it is available.
    """
    deterministic = build_deterministic_review(benchmark_report)

    if use_llm:
        try:
            llm_client = client if client is not None else get_client()
        except Exception as error:
            print("[reviewer_benchmark_agent] LLM unavailable (%s); using the "
                  "deterministic review." % error)
            llm_client = None
    else:
        llm_client = None

    if llm_client is None:
        return validate_review(deterministic)

    user_prompt = (
        "IR-SIM BENCHMARK REPORT (measured results):\n%s\n\n"
        "DETERMINISTIC REVIEW (ground truth for the seven keys, produced from the "
        "measured benchmark figures - keep the same booleans and the same meaning):\n%s\n\n"
        "Return the JSON object described in your instructions. Measure quality as "
        "safety, goal completion and efficiency, specify precisely which world failed "
        "and recommend the concrete fix."
        % (_summarise_report(benchmark_report),
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
            # The measured benchmark always wins over the model on the gates.
            for key in BOOLEAN_KEYS:
                review[key] = bool(deterministic[key])
            return validate_review(review)
        except (json.JSONDecodeError, ValueError) as error:
            print("[reviewer_benchmark_agent] attempt %d failed: %s" % (attempt, error))

    print("[reviewer_benchmark_agent] falling back to the deterministic review.")
    return validate_review(deterministic)


def save_review(review, path=None):
    """Persist the benchmark review as JSON and return the file path."""
    if path is None:
        path = BENCHMARK_REVIEW_PATH
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
    """Standalone review of artifacts/irsim_benchmark_report.json."""
    argv = list(sys.argv[1:] if argv is None else argv)
    report_path = argv[0] if argv else BENCHMARK_REPORT_PATH

    with open(report_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)

    review = run_benchmark_reviewer(report)
    path = save_review(review)
    print(json.dumps(review, indent=2, ensure_ascii=False))
    print("Saved benchmark review to %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
