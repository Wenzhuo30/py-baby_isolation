"""
test_analyst.py
===============
Level 1 - Smoke test for the Analyst Agent.

Takes the original brief.txt, sends it to the Analyst Agent, lets the agent run
as usual and stores the validated output in the artifacts folder as
requirements.json (Testing instructions, "Test the analyst agent").

The test asserts on the outcome, so a real failure fails the test:

    python test_analyst.py      # prints everything, exits 0/1
    pytest test_analyst.py -v   # fails (not silently passes) when the agent fails

Every assertion carries an explicit message so the reason is visible in the
pytest output and not only in the printed text.
"""
import json
import os

import pytest

from analyst_agent import _load_env_file, run_analyst, validate_requirements

HERE = os.path.dirname(os.path.abspath(__file__))
BRIEF_PATH = os.path.join(HERE, "brief.txt")
ARTIFACTS_DIR = os.path.join(HERE, "artifacts")
OUTPUT_PATH = os.path.join(ARTIFACTS_DIR, "requirements.json")

# The Analyst Agent has no deterministic fallback: without the Qwen key it cannot
# run at all.  That is "cannot run", not "produced wrong output", so the test is
# skipped (loudly) instead of being reported as a failure.  Once the agent DOES
# run, every check below is a hard assertion.
_load_env_file()
HAS_API_KEY = bool(os.getenv("DASHSCOPE_API_KEY"))


@pytest.mark.skipif(not HAS_API_KEY,
                    reason="DASHSCOPE_API_KEY is not configured, so the Analyst "
                           "Agent cannot run. Set it (or add .env) and re-run: "
                           "without the key this is untested, not passing.")
def test_analyst_agent():
    print("=" * 60)
    print("TEST: Analyst Agent Smoke Test")
    print("=" * 60)

    # Read the input brief
    assert os.path.exists(BRIEF_PATH), "input brief not found: %s" % BRIEF_PATH
    with open(BRIEF_PATH, "r", encoding="utf-8") as f:
        brief_text = f.read().strip()
    assert brief_text, "brief.txt is empty"

    # Run the analyst agent (its own validation runs inside run_analyst)
    try:
        requirements = run_analyst(brief_text)
    except Exception as error:  # noqa: BLE001 - reported as a test failure
        raise AssertionError("Analyst Agent did not produce valid requirements: "
                             "%s: %s" % (type(error).__name__, error))

    print("\nAnalyst agent produced valid requirements:")
    print(json.dumps(requirements, indent=2, ensure_ascii=False))

    # The agent must have turned the brief into a usable requirements artifact
    assert isinstance(requirements, dict), \
        "requirements must be a dict, got %s" % type(requirements).__name__
    validate_requirements(requirements)

    # Save to artifacts
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(requirements, f, indent=2, ensure_ascii=False)
        f.write("\n")

    assert os.path.exists(OUTPUT_PATH), "requirements artifact was not written"
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        stored = json.load(f)
    assert stored == requirements, \
        "artifacts/requirements.json does not contain the validated requirements"

    print(f"\nRequirements saved to {OUTPUT_PATH}")
    print("\nTest PASSED")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s", "--no-header",
                                  "-p", "no:cacheprovider"]))
