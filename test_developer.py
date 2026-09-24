"""
test_developer.py
=================
Level 1 - Smoke test for the Developer Agent.
Reads artifacts/plan.json, runs the developer agent,
validates the output code, and saves it to generated/navigation_logic.py.
"""
import os
import json
from developer_agent import run_developer

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN_PATH = os.path.join(HERE, "artifacts", "plan.json")
GENERATED_DIR = os.path.join(HERE, "generated")
OUTPUT_PATH = os.path.join(GENERATED_DIR, "navigation_logic.py")

def test_developer_agent():
    print("=" * 60)
    print("TEST: Developer Agent Smoke Test")
    print("=" * 60)

    # Read input plan
    if not os.path.exists(PLAN_PATH):
        print(f"\n Error: Plan file not found at {PLAN_PATH}")
        print("Run test_planner.py first to generate plan.json")
        return False

    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan = json.load(f)

    try:
        # Run developer agent (internal validation runs automatically)
        code = run_developer(plan)
        
        # Additional check: verify required function exists
        if "def decide_next_move" not in code:
            raise ValueError("Generated code missing required function: decide_next_move(state)")

        print("\n Developer agent produced valid Python code:")
        print("-" * 60)
        print(code)
        print("-" * 60)

        # Save to generated directory
        os.makedirs(GENERATED_DIR, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(code)
            if not code.endswith("\n"):
                f.write("\n")

        print(f"\n Navigation logic saved to {OUTPUT_PATH}")
        print("\n Test PASSED")
        return True

    except Exception as e:
        print(f"\n Test FAILED: {e}")
        return False

if __name__ == "__main__":
    success = test_developer_agent()
    exit(0 if success else 1)
