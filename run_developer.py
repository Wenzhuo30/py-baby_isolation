import json
from pathlib import Path
from developer_agent import run_developer

## the logic is similar to the run_planner and run_analyst files
HERE = Path(__file__).resolve().parent
PLAN_PATH = HERE / "artifacts" / "plan.json"
GENERATED_DIR = HERE / "generated"
OUTPUT_PATH = GENERATED_DIR / "navigation_logic.py"

def main():
    with open(PLAN_PATH, "r", encoding="utf-8") as handle:
        plan = json.load(handle)
    
    code = run_developer(plan)
    
    # Create generated directory if it doesn't exist
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        handle.write(code)
        if not code.endswith("\n"):
            handle.write("\n")
    print("Generated navigation logic saved to %s" % OUTPUT_PATH)

if __name__ == "__main__":
    main()
