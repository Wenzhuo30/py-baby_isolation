"""
test_generated_navigation_logic.py
==================================
Level 2 - Behavioral testing for the generated navigation logic.

Calls decide_next_move(state) with known robot states and checks that the returned
action is a valid action and the expected move (Testing instructions, "Test the
navigation logic").

Run it either way:

    python test_generated_navigation_logic.py     # prints a PASS/FAIL table, exits 0/1
    pytest test_generated_navigation_logic.py -v   # one real test per case

Both work: the cases below are exposed as pytest tests, and the adapter at the
bottom turns the same cases into a printed report when the file is executed as a
script.
"""
import os
import sys

import pytest

# Add project root to import path
HERE = os.path.dirname(os.path.abspath(__file__))
GENERATED_DIR = os.path.join(HERE, "generated")
sys.path.insert(0, GENERATED_DIR)

from generated.navigation_logic import decide_next_move

VALID_ACTIONS = {"FORWARD", "LEFT", "RIGHT", "STOP"}

BLOCKED_KEY_FOR_ACTION = {
    "FORWARD": "blocked_front",
    "LEFT": "blocked_left",
    "RIGHT": "blocked_right",
}

# Test cases: (test_name, state_dict, expected_action)
TEST_CASES = [
    # --- Goal-aligned safe directions ---
    (
        "Goal front, front safe -> FORWARD",
        {"blocked_front": False, "blocked_left": False, "blocked_right": False,
         "goal_front": True, "goal_left": False, "goal_right": False},
        "FORWARD"
    ),
    (
        "Goal left, left safe -> LEFT",
        {"blocked_front": True, "blocked_left": False, "blocked_right": True,
         "goal_front": False, "goal_left": True, "goal_right": False},
        "LEFT"
    ),
    (
        "Goal right, right safe -> RIGHT",
        {"blocked_front": True, "blocked_left": True, "blocked_right": False,
         "goal_front": False, "goal_left": False, "goal_right": True},
        "RIGHT"
    ),

    # --- Goal direction blocked, fall back to safe direction ---
    (
        "Goal front blocked, left safe -> LEFT",
        {"blocked_front": True, "blocked_left": False, "blocked_right": True,
         "goal_front": True, "goal_left": False, "goal_right": False},
        "LEFT"
    ),
    (
        "Goal left blocked, front safe -> FORWARD",
        {"blocked_front": False, "blocked_left": True, "blocked_right": True,
         "goal_front": False, "goal_left": True, "goal_right": False},
        "FORWARD"
    ),

    # --- No goal direction: priority front > left > right ---
    (
        "No goal, all safe -> FORWARD",
        {"blocked_front": False, "blocked_left": False, "blocked_right": False,
         "goal_front": False, "goal_left": False, "goal_right": False},
        "FORWARD"
    ),
    (
        "No goal, front blocked, left safe -> LEFT",
        {"blocked_front": True, "blocked_left": False, "blocked_right": False,
         "goal_front": False, "goal_left": False, "goal_right": False},
        "LEFT"
    ),
    (
        "No goal, front & left blocked, right safe -> RIGHT",
        {"blocked_front": True, "blocked_left": True, "blocked_right": False,
         "goal_front": False, "goal_left": False, "goal_right": False},
        "RIGHT"
    ),

    # --- All directions blocked -> STOP ---
    (
        "All directions blocked -> STOP",
        {"blocked_front": True, "blocked_left": True, "blocked_right": True,
         "goal_front": True, "goal_left": True, "goal_right": True},
        "STOP"
    ),

    # --- Multiple goal directions ---
    (
        "Goal front+left, both safe -> FORWARD (priority)",
        {"blocked_front": False, "blocked_left": False, "blocked_right": True,
         "goal_front": True, "goal_left": True, "goal_right": False},
        "FORWARD"
    ),
]

CASE_IDS = [name for name, _, _ in TEST_CASES]


@pytest.mark.parametrize("name,state,expected", TEST_CASES, ids=CASE_IDS)
def test_known_state_returns_expected_action(name, state, expected):
    """Each known robot state must produce exactly the expected action."""
    action = decide_next_move(dict(state))
    assert action in VALID_ACTIONS, \
        "%s: returned %r, which is not one of %s" % (name, action, sorted(VALID_ACTIONS))
    assert action == expected, "%s: expected %s, got %s" % (name, expected, action)


@pytest.mark.parametrize("name,state,expected", TEST_CASES, ids=CASE_IDS)
def test_known_state_is_safe(name, state, expected):
    """The robot must never move into a direction that is marked as blocked."""
    action = decide_next_move(dict(state))
    blocked_key = BLOCKED_KEY_FOR_ACTION.get(action)
    if blocked_key is None:
        assert action == "STOP", "%s: unexpected action %r" % (name, action)
    else:
        assert not state[blocked_key], \
            "%s: chose %s although %s is blocked" % (name, action, blocked_key)


def behavior_report():
    """Run TEST_CASES and return (passed, failed, lines) for the script mode."""
    passed, failed, lines = 0, 0, []
    for name, state, expected in TEST_CASES:
        try:
            result = decide_next_move(dict(state))
        except Exception as error:  # noqa: BLE001 - reported as a failure
            lines.append("FAIL: %s\n   Exception: %s" % (name, error))
            failed += 1
            continue
        if result not in VALID_ACTIONS:
            lines.append("FAIL: %s\n   Invalid action returned: %s" % (name, result))
            failed += 1
        elif result == expected:
            lines.append("PASS: %s" % name)
            passed += 1
        else:
            lines.append("FAIL: %s\n   Expected: %s\n   Got:      %s"
                         % (name, expected, result))
            failed += 1
    return passed, failed, lines


def run_behavioral_tests():
    """Printed report used when this file is executed as a script."""
    print("=" * 60)
    print("TEST: Navigation Logic Behavioral Tests")
    print("=" * 60)
    print("Total test cases: %d\n" % len(TEST_CASES))

    passed, failed, lines = behavior_report()
    for line in lines:
        print(line)

    print("\n" + "-" * 60)
    print("Results: %d passed, %d failed, total %d" % (passed, failed, len(TEST_CASES)))
    if failed == 0:
        print("\nAll behavioral tests PASSED")
        return True
    print("\n%d test(s) FAILED" % failed)
    return False


if __name__ == "__main__":
    success = run_behavioral_tests()
    exit(0 if success else 1)
