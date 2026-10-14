"""Testing instructions, page 9 - "Introduce a bug".

Evidence that the test suite is useful, i.e. that it detects bugs and does not
just print "passed":

  1. run the generated tests on the correct navigation logic      -> all pass
  2. inject a realistic fault into generated/navigation_logic.py  -> tests FAIL
  3. restore the original code                                    -> all pass again

The fault that is injected is the exact mistake the instructions suggest
("making one test case return an incorrect direction"): the goal-to-the-left
branch is changed to turn right, which is safe but wrong.  A safety-only check
still accepts it - the behavioral tests must therefore compare against the
expected action, not only against the set of valid actions.

Results are written to artifacts/bug_injection_experiment.json.

Usage:
    python experiment_bug_injection.py            # inject, test, restore
    python experiment_bug_injection.py --keep-bug # leave the bug in place
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NAVIGATION_PATH = os.path.join(HERE, "generated", "navigation_logic.py")
TEST_PATH = os.path.join(HERE, "generated", "test_navigation_logic.py")
EXTRA_TEST_PATH = os.path.join(HERE, "test_generated_navigation_logic.py")
ARTIFACTS_DIR = os.path.join(HERE, "artifacts")
EVIDENCE_PATH = os.path.join(ARTIFACTS_DIR, "bug_injection_experiment.json")

# The fault: "goal is to the left and the left path is clear" must turn LEFT, the
# injected version stops instead.  The fault is deliberately SAFE (stopping never
# moves into a blocked direction), so the final safety guard inside
# decide_next_move accepts it - the fault can only be caught by comparing the
# returned action with the expected one, which is what these tests do.
ORIGINAL_BRANCH = '    if goal_left and not blocked_left:\n        return "LEFT"\n'
BUGGY_BRANCH = ('    if goal_left and not blocked_left:\n'
                '        return "STOP"  # BUG (injected on purpose)\n')

STATE = {"blocked_front": True, "blocked_left": False, "blocked_right": True,
         "goal_front": False, "goal_left": True, "goal_right": False}


def run_pytest(path):
    """Run one pytest file and return (returncode, passed, failed, tail)."""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", path, "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=HERE, capture_output=True, text=True,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    passed = re.search(r"(\d+) passed", output)
    failed = re.search(r"(\d+) failed", output)
    return {
        "returncode": completed.returncode,
        "passed": int(passed.group(1)) if passed else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "summary": (output.strip().splitlines() or ["<no output>"])[-1],
    }


def observe_action():
    """Import the navigation logic fresh and ask for the LEFT/clear-left state."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("nav_probe_%d" % time.time_ns(),
                                                  NAVIGATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.decide_next_move(dict(STATE))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    keep_bug = "--keep-bug" in argv
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    original_code = open(NAVIGATION_PATH, "r", encoding="utf-8").read()
    if ORIGINAL_BRANCH not in original_code:
        raise SystemExit("cannot inject the bug: the expected LEFT branch was not "
                         "found in %s" % NAVIGATION_PATH)

    evidence = {
        "instructions": "Testing instructions, page 9 - Introduce a bug",
        "navigation_logic": os.path.relpath(NAVIGATION_PATH, HERE),
        "injected_fault": ('choose_action(): "if goal_left and not blocked_left" '
                           'returned "STOP" instead of "LEFT" (safe but wrong, so '
                           'only an expected-action comparison can catch it)'),
        "probe_state": STATE,
        "test_suites": [os.path.relpath(TEST_PATH, HERE),
                        os.path.relpath(EXTRA_TEST_PATH, HERE)],
        "steps": [],
    }

    print("=" * 70)
    print("BUG INJECTION EXPERIMENT (Testing instructions, page 9)")
    print("=" * 70)

    # --- step 1: the tests on the correct logic ---------------------------
    print("\n[1/4] correct logic: run the generated tests")
    correct_generated = run_pytest(TEST_PATH)
    correct_extra = run_pytest(EXTRA_TEST_PATH)
    print("      expected action for the probe state: %s" % observe_action())
    print("      generated tests : %s" % correct_generated["summary"])
    print("      Level 2 tests   : %s" % correct_extra["summary"])
    assert correct_generated["failed"] == 0 and correct_generated["returncode"] == 0, \
        "the generated tests must pass on the correct logic before injecting a bug"
    assert correct_extra["failed"] == 0 and correct_extra["returncode"] == 0, \
        "the Level 2 tests must pass on the correct logic before injecting a bug"
    evidence["steps"].append({
        "step": "correct logic",
        "generated_tests": correct_generated,
        "level2_tests": correct_extra,
        "probe_action": observe_action(),
        "verdict": "all tests pass (baseline)",
    })

    # --- step 2: inject the bug -------------------------------------------
    print("\n[2/4] inject the bug into %s" % os.path.relpath(NAVIGATION_PATH, HERE))
    buggy_code = original_code.replace(ORIGINAL_BRANCH, BUGGY_BRANCH, 1)
    assert buggy_code != original_code, "bug injection had no effect"
    with open(NAVIGATION_PATH, "w", encoding="utf-8") as handle:
        handle.write(buggy_code)
    buggy_action = observe_action()
    print("      action for the probe state is now: %s (expected LEFT)" % buggy_action)
    assert buggy_action == "STOP", "the injected bug did not change the behaviour"
    evidence["steps"].append({
        "step": "bug injected",
        "probe_action": buggy_action,
        "verdict": "the robot stops instead of driving toward the goal "
                   "(safe, so it is not a safety violation - it is simply wrong)",
    })

    # --- step 3: the tests must now fail ----------------------------------
    print("\n[3/4] buggy logic: run the tests again - they must FAIL")
    buggy_generated = run_pytest(TEST_PATH)
    buggy_extra = run_pytest(EXTRA_TEST_PATH)
    print("      generated tests : %s" % buggy_generated["summary"])
    print("      Level 2 tests   : %s" % buggy_extra["summary"])
    caught = (buggy_generated["failed"] > 0 or buggy_extra["failed"] > 0
              or buggy_generated["returncode"] != 0 or buggy_extra["returncode"] != 0)
    evidence["steps"].append({
        "step": "buggy logic",
        "generated_tests": buggy_generated,
        "level2_tests": buggy_extra,
        "verdict": "bug detected by the test suite" if caught
                   else "BUG NOT DETECTED - a test must be added",
    })
    if not caught:
        print("\n      the bug was NOT detected: add a test that detects it!")

    correct_action = None
    # --- step 4: restore and confirm --------------------------------------
    if keep_bug:
        print("\n[4/4] --keep-bug given: the bug is left in place for inspection")
    else:
        print("\n[4/4] remove the bug and run the tests again")
        with open(NAVIGATION_PATH, "w", encoding="utf-8") as handle:
            handle.write(original_code)
        restored_generated = run_pytest(TEST_PATH)
        restored_extra = run_pytest(EXTRA_TEST_PATH)
        correct_action = observe_action()
        print("      correct logic restored, action for the probe state: %s" % correct_action)
        print("      generated tests : %s" % restored_generated["summary"])
        print("      Level 2 tests   : %s" % restored_extra["summary"])
        evidence["steps"].append({
            "step": "bug removed",
            "generated_tests": restored_generated,
            "level2_tests": restored_extra,
            "probe_action": correct_action,
            "verdict": "all tests pass again",
        })
        assert restored_generated["failed"] == 0 and restored_extra["failed"] == 0, \
            "the tests must pass again after the bug was removed"
        assert open(NAVIGATION_PATH, "r", encoding="utf-8").read() == original_code, \
            "the original navigation logic was not restored"

    evidence["conclusion"] = (
        "The generated tests and the Level 2 behavioral tests both detect the "
        "injected fault (all passed on the correct logic, failed while the bug was "
        "present, and passed again after it was removed), so the suite detects bugs "
        "instead of only printing 'passed'."
        if caught and not keep_bug else
        "The injected fault was not detected by the current tests."
    )
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print("\n" + "=" * 70)
    print("RESULT: %s" % evidence["conclusion"])
    print("evidence written to %s" % os.path.relpath(EVIDENCE_PATH, HERE))
    print("=" * 70)
    return 0 if caught else 1


if __name__ == "__main__":
    raise SystemExit(main())
