"""
test_planner.py
===============
Level 1 - Smoke test for the Planner Agent.
Reads artifacts/requirements.json, runs the planner agent,
validates the output, and saves the result to artifacts/plan.json.
"""
import json
import os
from planner_agent import run_planner

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS_PATH = os.path.join(HERE, "artifacts", "requirements.json")
ARTIFACTS_DIR = os.path.join(HERE, "artifacts")
OUTPUT_PATH = os.path.join(ARTIFACTS_DIR, "plan.json")

def test_planner_agent():
    print("=" * 60)
    print("TEST: Planner Agent Smoke Test")
    print("=" * 60)

    # Read input requirements
    if not os.path.exists(REQUIREMENTS_PATH):
        print(f"\n Error: Requirements file not found at {REQUIREMENTS_PATH}")
        print("Run test_analyst.py first to generate requirements.json")
        return False

    with open(REQUIREMENTS_PATH, "r", encoding="utf-8") as f:
        requirements = json.load(f)

    try:
        # Run planner agent (internal validation runs automatically)
        plan = run_planner(requirements)
        print("\n✅ Planner agent produced valid plan:")
        print(json.dumps(plan, indent=2, ensure_ascii=False))

        # Save to artifacts
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
            f.write("\n")

        print(f"\n Plan saved to {OUTPUT_PATH}")
        print("\n Test PASSED")
        return True

    except Exception as e:
        print(f"\n Test FAILED: {e}")
        return False

if __name__ == "__main__":
    success = test_planner_agent()
    exit(0 if success else 1)
