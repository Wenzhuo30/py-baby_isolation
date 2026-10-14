"""
test_planner.py
===============
Level 1 - Smoke test for the Planner Agent.

Takes the artifacts/requirements.json produced by the Analyst Agent, sends it to
the Planner Agent, lets the agent run as usual and stores the validated output in
the artifacts folder as plan.json (Testing instructions, "Test the planner
agent").

The test asserts on the outcome, so a real failure fails the test:

    python test_planner.py       # prints everything, exits 0/1
    pytest test_planner.py -v    # fails (not silently passes) when the agent fails

Note: run test_analyst.py first, so that requirements.json exists.
"""
import json
import os

import pytest

from planner_agent import _load_env_file, run_planner, validate_plan

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS_PATH = os.path.join(HERE, "artifacts", "requirements.json")
ARTIFACTS_DIR = os.path.join(HERE, "artifacts")
OUTPUT_PATH = os.path.join(ARTIFACTS_DIR, "plan.json")

# The Planner Agent has no deterministic fallback either, so the same rule as in
# test_analyst.py applies: skip when the key is missing, assert hard otherwise.
_load_env_file()
HAS_API_KEY = bool(os.getenv("DASHSCOPE_API_KEY"))


@pytest.mark.skipif(not HAS_API_KEY,
                    reason="DASHSCOPE_API_KEY is not configured, so the Planner "
                           "Agent cannot run. Set it (or add .env) and re-run.")
def test_planner_agent():
    print("=" * 60)
    print("TEST: Planner Agent Smoke Test")
    print("=" * 60)

    # Read the input requirements
    assert os.path.exists(REQUIREMENTS_PATH), \
        "requirements artifact not found at %s - run test_analyst.py first" % REQUIREMENTS_PATH
    with open(REQUIREMENTS_PATH, "r", encoding="utf-8") as f:
        requirements = json.load(f)
    assert isinstance(requirements, dict) and requirements, \
        "artifacts/requirements.json is not a non-empty JSON object"

    # Run the planner agent (its own validation runs inside run_planner)
    try:
        plan = run_planner(requirements)
    except Exception as error:  # noqa: BLE001 - reported as a test failure
        raise AssertionError("Planner Agent did not produce a valid plan: "
                             "%s: %s" % (type(error).__name__, error))

    print("\nPlanner agent produced valid plan:")
    print(json.dumps(plan, indent=2, ensure_ascii=False))

    # The agent must turn the requirements artifact into a plan the developer can use
    assert isinstance(plan, dict), "plan must be a dict, got %s" % type(plan).__name__
    validate_plan(plan)
    for key in ("strategy", "decisions", "stop_point"):
        assert key in plan, 'plan is missing the "%s" field' % key

    # Save to artifacts
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
        f.write("\n")

    assert os.path.exists(OUTPUT_PATH), "plan artifact was not written"
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        stored = json.load(f)
    assert stored == plan, "artifacts/plan.json does not contain the validated plan"

    print(f"\nPlan saved to {OUTPUT_PATH}")
    print("\nTest PASSED")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s", "--no-header",
                                  "-p", "no:cacheprovider"]))
