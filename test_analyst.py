"""
test_analyst.py
===============
Level 1 - Smoke test for the Analyst Agent.
Reads brief.txt, runs the analyst agent, validates the output,
and saves the result to artifacts/requirements.json.
"""
import json
import os
from analyst_agent import run_analyst

HERE = os.path.dirname(os.path.abspath(__file__))
BRIEF_PATH = os.path.join(HERE, "brief.txt")
ARTIFACTS_DIR = os.path.join(HERE, "artifacts")
OUTPUT_PATH = os.path.join(ARTIFACTS_DIR, "requirements.json")

def test_analyst_agent():
    print("=" * 60)
    print("TEST: Analyst Agent Smoke Test")
    print("=" * 60)

    # Read input brief
    with open(BRIEF_PATH, "r", encoding="utf-8") as f:
        brief_text = f.read().strip()

    try:
        # Run analyst agent (internal validation runs automatically)
        requirements = run_analyst(brief_text)
        print("\n✅ Analyst agent produced valid requirements:")
        print(json.dumps(requirements, indent=2, ensure_ascii=False))

        # Save to artifacts
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(requirements, f, indent=2, ensure_ascii=False)
            f.write("\n")

        print(f"\n Requirements saved to {OUTPUT_PATH}")
        print("\n Test PASSED")
        return True

    except Exception as e:
        print(f"\n Test FAILED: {e}")
        return False

if __name__ == "__main__":
    success = test_analyst_agent()
    exit(0 if success else 1)
