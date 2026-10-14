"""
test_developer.py
=================
Level 1 - Smoke test for the Developer Agent.

Takes the artifacts/plan.json produced by the Planner Agent, sends it to the
Developer Agent, lets the agent run as usual and stores the generated navigation
logic in generated/navigation_logic.py (Testing instructions, "Test the developer
agent"). The generated code must define decide_next_move(state), which is the only
function other programs may call.

The test asserts on the outcome, so a real failure fails the test:

    python test_developer.py      # prints everything, exits 0/1
    pytest test_developer.py -v   # fails (not silently passes) when the agent fails

Note: run test_planner.py first, so that plan.json exists.

The Testing instructions mention the navigation logic artifact as
artifacts/navigation_logic.py while the "finally you should have" list names
generated/navigation_logic.py. The generated/ location is the one the rest of the
pipeline imports, so it is written here; a copy is kept in artifacts/ as well so
both documented paths exist.
"""
import json
import os

import pytest

from developer_agent import _load_env_file, run_developer, validate_code

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN_PATH = os.path.join(HERE, "artifacts", "plan.json")
GENERATED_DIR = os.path.join(HERE, "generated")
ARTIFACTS_DIR = os.path.join(HERE, "artifacts")
OUTPUT_PATH = os.path.join(GENERATED_DIR, "navigation_logic.py")
ARTIFACT_COPY_PATH = os.path.join(ARTIFACTS_DIR, "navigation_logic.py")

_load_env_file()
HAS_API_KEY = bool(os.getenv("DASHSCOPE_API_KEY"))


@pytest.mark.skipif(not HAS_API_KEY,
                    reason="DASHSCOPE_API_KEY is not configured, so the Developer "
                           "Agent would only return its deterministic fallback "
                           "instead of asking Qwen. Set it (or add .env) and re-run.")
def test_developer_agent():
    print("=" * 60)
    print("TEST: Developer Agent Smoke Test")
    print("=" * 60)

    # Read the input plan
    assert os.path.exists(PLAN_PATH), \
        "plan artifact not found at %s - run test_planner.py first" % PLAN_PATH
    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan = json.load(f)
    assert isinstance(plan, dict) and plan, \
        "artifacts/plan.json is not a non-empty JSON object"

    # Run the developer agent (its own validation runs inside run_developer)
    try:
        code = run_developer(plan)
    except Exception as error:  # noqa: BLE001 - reported as a test failure
        raise AssertionError("Developer Agent did not produce valid Python code: "
                             "%s: %s" % (type(error).__name__, error))

    # The generated code must be valid Python ...
    assert isinstance(code, str) and code.strip(), "generated code is empty"
    validate_code(code)
    compile(code, "navigation_logic.py", "exec")

    # ... and it must define the function every other program calls
    assert "def decide_next_move" in code, \
        "generated code is missing the required function decide_next_move(state)"

    print("\nDeveloper agent produced valid Python code:")
    print("-" * 60)
    print(code)
    print("-" * 60)

    # Save to the generated directory (and keep the artifacts/ copy in sync)
    os.makedirs(GENERATED_DIR, exist_ok=True)
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(code)
        if not code.endswith("\n"):
            f.write("\n")
    with open(ARTIFACT_COPY_PATH, "w", encoding="utf-8") as f:
        f.write(code)
        if not code.endswith("\n"):
            f.write("\n")

    assert os.path.exists(OUTPUT_PATH), "navigation logic artifact was not written"

    print(f"\nNavigation logic saved to {OUTPUT_PATH}")
    print(f"Copy kept at {ARTIFACT_COPY_PATH}")
    print("\nTest PASSED")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s", "--no-header",
                                  "-p", "no:cacheprovider"]))
