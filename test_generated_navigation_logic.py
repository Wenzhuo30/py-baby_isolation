"""
test_generated_navigation_logic.py
===================================
Level 2 - Behavioral testing for the generated navigation logic.
Tests the decide_next_move(state) function with known input states
and verifies the output action is correct.
"""
import sys
import os

# Add project root to import path
HERE = os.path.dirname(os.path.abspath(__file__))
GENERATED_DIR = os.path.join(HERE, "generated")
sys.path.insert(0, GENERATED_DIR)


from generated.navigation_logic import decide_next_move

VALID_ACTIONS = {"FORWARD", "LEFT", "RIGHT", "STOP"}

# Test cases: (test_name, state_dict, expected_action)
TEST_CASES = [
    # --- Goal-aligned safe directions ---
    (
        "Goal front, front safe → FORWARD",
        {"blocked_front": False, "blocked_left": False, "blocked_right": False,
         "goal_front": True, "goal_left": False, "goal_right": False},
        "FORWARD"
    ),
    (
        "Goal left, left safe → LEFT",
        {"blocked_front": True, "blocked_left": False, "blocked_right": True,
         "goal_front": False, "goal_left": True, "goal_right": False},
        "LEFT"
    ),
    (
        "Goal right, right safe → RIGHT",
        {"blocked_front": True, "blocked_left": True, "blocked_right": False,
         "goal_front": False, "goal_left": False, "goal_right": True},
        "RIGHT"
    ),

    # --- Goal direction blocked, fall back to safe direction ---
    (
        "Goal front blocked, left safe → LEFT",
        {"blocked_front": True, "blocked_left": False, "blocked_right": True,
         "goal_front": True, "goal_left": False, "goal_right": False},
        "LEFT"
    ),
    (
        "Goal left blocked, front safe → FORWARD",
        {"blocked_front": False, "blocked_left": True, "blocked_right": True,
         "goal_front": False, "goal_left": True, "goal_right": False},
        "FORWARD"
    ),

    # --- No goal direction: priority front > left > right ---
    (
        "No goal, all safe → FORWARD",
        {"blocked_front": False, "blocked_left": False, "blocked_right": False,
         "goal_front": False, "goal_left": False, "goal_right": False},
        "FORWARD"
    ),
    (
        "No goal, front blocked, left safe → LEFT",
        {"blocked_front": True, "blocked_left": False, "blocked_right": False,
         "goal_front": False, "goal_left": False, "goal_right": False},
        "LEFT"
    ),
    (
        "No goal, front & left blocked, right safe → RIGHT",
        {"blocked_front": True, "blocked_left": True, "blocked_right": False,
         "goal_front": False, "goal_left": False, "goal_right": False},
        "RIGHT"
    ),

    # --- All directions blocked → STOP ---
    (
        "All directions blocked → STOP",
        {"blocked_front": True, "blocked_left": True, "blocked_right": True,
         "goal_front": True, "goal_left": True, "goal_right": True},
        "STOP"
    ),

    # --- Multiple goal directions ---
    (
        "Goal front+left, both safe → FORWARD (priority)",
        {"blocked_front": False, "blocked_left": False, "blocked_right": True,
         "goal_front": True, "goal_left": True, "goal_right": False},
        "FORWARD"
    ),
]

def run_behavioral_tests():
    print("=" * 60)
    print("TEST: Navigation Logic Behavioral Tests")
    print("=" * 60)
    print(f"Total test cases: {len(TEST_CASES)}\n")

    passed = 0
    failed = 0

    for name, state, expected in TEST_CASES:
        try:
            result = decide_next_move(state)
            
            # Check if result is a valid action
            if result not in VALID_ACTIONS:
                print(f" FAIL: {name}")
                print(f"   Invalid action returned: {result}")
                failed += 1
                continue
            
            # Check if result matches expected
            if result == expected:
                print(f" PASS: {name}")
                passed += 1
            else:
                print(f" FAIL: {name}")
                print(f"   Expected: {expected}")
                print(f"   Got:      {result}")
                failed += 1

        except Exception as e:
            print(f" FAIL: {name}")
            print(f"   Exception: {e}")
            failed += 1

    print("\n" + "-" * 60)
    print(f"Results: {passed} passed, {failed} failed, total {len(TEST_CASES)}")
    
    if failed == 0:
        print("\n All behavioral tests PASSED")
        return True
    else:
        print(f"\n  {failed} test(s) FAILED")
        return False

if __name__ == "__main__":
    success = run_behavioral_tests()
    exit(0 if success else 1)
