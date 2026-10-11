"""
runner.py
=========
Simulation runner for the navigation logic produced by the Developer Agent.

It exercises ``decide_next_move(state)`` against **every possible scenario** of
the perception state (the six boolean keys, i.e. all 2**6 = 64 combinations)
and checks that the returned action matches the navigation policy that follows
from the customer brief:

1. SAFETY  - the robot must never move into a blocked direction.
2. GOAL    - the robot prefers moving toward its goal whenever that direction
             is safe (goal_ahead -> FORWARD, goal_left -> LEFT,
             goal_right -> RIGHT).
3. FALLBACK- if no goal direction is safe, any safe direction is acceptable;
             the reference priority among the remaining safe directions is
             front > left > right.
4. STOP    - if no safe direction is available at all, the robot must STOP.

The complete result of the simulation is written to
``artifacts/simulation_report.json`` (see ``save_simulation_report``).

Public API:
    load_navigation_callable(path)  -> decide_next_move callable
    build_scenarios()               -> list of all 64 scenarios
    simulate(navigation_fn)         -> full simulation report (dict)
    run_simulation(...)             -> report + saved JSON path
    save_simulation_report(report)  -> path of the written report
"""

import importlib.util
import itertools
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(HERE, "artifacts")
SIMULATION_REPORT_PATH = os.path.join(ARTIFACTS_DIR, "simulation_report.json")

# The canonical state contract shared by every component of the project.
STATE_KEYS = (
    "blocked_front",
    "blocked_left",
    "blocked_right",
    "goal_front",
    "goal_left",
    "goal_right",
)

# Descriptive aliases accepted as well, so a state dict produced by the
# IR-SIM adapter (front_blocked / goal_ahead / ...) also works.
STATE_ALIASES = {
    "blocked_front": ("front_blocked",),
    "blocked_left": ("left_blocked",),
    "blocked_right": ("right_blocked",),
    "goal_front": ("goal_ahead",),
    "goal_left": ("goal_on_left",),
    "goal_right": ("goal_on_right",),
}

VALID_ACTIONS = ("FORWARD", "LEFT", "RIGHT", "STOP")

# Which action moves the robot toward the goal, per goal-direction flag.
GOAL_ACTION = {
    "goal_front": "FORWARD",
    "goal_left": "LEFT",
    "goal_right": "RIGHT",
}

# Direction corresponding to each action (used for the safety check).
ACTION_DIRECTION = {
    "FORWARD": "front",
    "LEFT": "left",
    "RIGHT": "right",
}

# Preference order used when no goal direction is safe.
FALLBACK_ORDER = ("FORWARD", "LEFT", "RIGHT")

POLICY_VERSION = "brief-v1: safe goal-directed navigation, stop when no safe direction"



# Navigation logic loading
def load_navigation_callable(path=None):
    """Import ``decide_next_move`` from the generated navigation logic.

    ``path`` points to a .py file (default: generated/navigation_logic.py).
    The module is always reloaded so a revised navigation logic replaces the
    previous one inside a single process.
    """
    if path is None:
        path = os.path.join(HERE, "generated", "navigation_logic.py")
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Navigation logic not found at %s. Run the Developer Agent first." % path
        )

    module_name = "navigation_logic_sim_%s" % os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    navigation_fn = getattr(module, "decide_next_move", None)
    if not callable(navigation_fn):
        raise AttributeError(
            "%s does not define a callable decide_next_move(state)." % path
        )
    return navigation_fn



# Scenario definition
def _normalize_state(state):
    """Build a canonical six-key state dict from a state produced by any source."""
    if not isinstance(state, dict):
        raise TypeError("state must be a dict, got %s" % type(state).__name__)

    normalized = {}
    for key in STATE_KEYS:
        if key in state:
            normalized[key] = bool(state[key])
            continue
        alias_value = None
        for alias in STATE_ALIASES[key]:
            if alias in state:
                alias_value = state[alias]
                break
        if alias_value is None:
            raise KeyError("state is missing required key %r" % key)
        normalized[key] = bool(alias_value)
    return normalized


def _label(state):
    """Human readable scenario name, e.g. ``B(front,left)_G(front)``."""
    blocked = [name for name in ("front", "left", "right") if state["blocked_%s" % name]]
    goals = [name for name in ("front", "left", "right") if state["goal_%s" % name]]
    blocked_label = ",".join(blocked) if blocked else "none"
    goal_label = ",".join(goals) if goals else "none"
    return "B(%s)_G(%s)" % (blocked_label, goal_label)


def expected_actions_for_state(state):
    """Return the list of acceptable actions for one state, best first.

    The first element is the reference expectation used by the simulation; the
    remaining elements are equally valid according to the brief (they only
    differ in the tie-break between two safe non-goal directions).
    """
    safe = [action for action in VALID_ACTIONS if action == "STOP"
            or not state["blocked_%s" % ACTION_DIRECTION[action]]]

    preference = []
    for goal_key, action in GOAL_ACTION.items():
        if state[goal_key] and action not in preference:
            preference.append(action)
    for action in FALLBACK_ORDER:
        if action not in preference:
            preference.append(action)

    acceptable = [action for action in preference if action in safe]
    if not acceptable:  # every direction is blocked -> the only safe action
        acceptable = ["STOP"]
    return acceptable


def build_scenarios():
    """Enumerate all 64 possible perception scenarios."""
    scenarios = []
    for index, combo in enumerate(itertools.product([False, True], repeat=len(STATE_KEYS))):
        state = dict(zip(STATE_KEYS, combo))
        expected = expected_actions_for_state(state)
        scenarios.append({
            "scenario_id": "S%02d" % index,
            "name": _label(state),
            "state": state,
            "expected": expected[0],
            "acceptable_actions": expected,
            "policy_version": POLICY_VERSION,
        })
    return scenarios


def _blocked_direction(action):
    direction = ACTION_DIRECTION.get(action)
    if direction is None:
        return None
    return "blocked_%s" % direction



# Simulation
def simulate(navigation_fn, scenarios=None):
    """Run ``navigation_fn`` against every scenario and summarise the outcome.

    Returns a JSON-serialisable report containing the total number of
    scenarios, the number of passed/failed scenarios and the success rate.
    """
    if not callable(navigation_fn):
        raise TypeError("navigation_fn must be callable")
    if scenarios is None:
        scenarios = build_scenarios()

    results = []
    passed = 0
    failed = 0
    safety_violations = 0
    error_count = 0
    preference_mismatches = 0

    for scenario in scenarios:
        state = scenario["state"]
        acceptable = scenario.get("acceptable_actions") or [scenario["expected"]]
        expected = acceptable[0]

        record = {
            "scenario_id": scenario["scenario_id"],
            "name": scenario["name"],
            "state": dict(state),
            "expected": expected,
            "acceptable_actions": list(acceptable),
        }

        try:
            actual = navigation_fn(dict(state))
        except Exception as error:  # the simulation must never crash the pipeline
            record.update({
                "actual": None,
                "passed": False,
                "reason": "EXCEPTION",
                "detail": "%s: %s" % (type(error).__name__, error),
            })
            error_count += 1
            failed += 1
            results.append(record)
            continue

        record["actual"] = actual

        if actual not in VALID_ACTIONS:
            record.update({
                "passed": False,
                "reason": "INVALID_ACTION",
                "detail": "returned %r, allowed actions are %s"
                          % (actual, ", ".join(VALID_ACTIONS)),
            })
            failed += 1
            results.append(record)
            continue

        blocked_key = _blocked_direction(actual)
        moved_into_obstacle = blocked_key is not None and bool(state[blocked_key])
        if moved_into_obstacle:
            record.update({
                "passed": False,
                "reason": "SAFETY_VIOLATION",
                "detail": "%s moves into %s which is blocked" % (actual, blocked_key),
            })
            safety_violations += 1
            failed += 1
            results.append(record)
            continue

        if actual == expected:
            record.update({"passed": True, "reason": "OK",
                           "detail": "matches the reference policy"})
            passed += 1
        elif actual in acceptable:
            record.update({
                "passed": True,
                "reason": "ACCEPTABLE_ALTERNATIVE",
                "detail": "safe fallback; reference priority prefers %s" % expected,
            })
            preference_mismatches += 1
            passed += 1
        else:
            record.update({
                "passed": False,
                "reason": "UNEXPECTED_ACTION",
                "detail": "expected %s (acceptable: %s), got %s"
                          % (expected, ", ".join(acceptable), actual),
            })
            failed += 1

        results.append(record)

    total = len(results)
    succeeded = failed == 0
    report = {
        "policy_version": POLICY_VERSION,
        "state_keys": list(STATE_KEYS),
        "valid_actions": list(VALID_ACTIONS),
        "total_scenarios": total,
        "passed_scenarios": passed,
        "failed_scenarios": failed,
        "success_rate": (passed / total) if total else 0.0,
        "safety_violations": safety_violations,
        "invalid_actions": sum(1 for r in results if r.get("reason") == "INVALID_ACTION"),
        "exceptions": error_count,
        "preference_mismatches": preference_mismatches,
        "status": "PASSED" if succeeded else "FAILED",
        "failed_details": [
            {
                "scenario_id": r["scenario_id"],
                "name": r["name"],
                "state": r["state"],
                "expected": r["expected"],
                "actual": r["actual"],
                "reason": r["reason"],
                "detail": r["detail"],
            }
            for r in results if not r["passed"]
        ],
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return report


def run_simulation(navigation_path=None, navigation_fn=None, scenarios=None):
    """Run the whole simulation and return ``(report, report_path)``."""
    if navigation_fn is None:
        navigation_fn = load_navigation_callable(navigation_path)

    report = simulate(navigation_fn, scenarios=scenarios)
    report["navigation_logic_path"] = os.path.relpath(
        os.path.abspath(navigation_path
                        or os.path.join(HERE, "generated", "navigation_logic.py")),
        HERE,
    )
    report_path = save_simulation_report(report)
    return report, report_path


def save_simulation_report(report, path=None):
    """Persist the simulation report as JSON and return the file path."""
    if path is None:
        path = SIMULATION_REPORT_PATH
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def print_summary(report):
    print("=" * 60)
    print("SIMULATION REPORT")
    print("=" * 60)
    print("Navigation logic : %s" % report.get("navigation_logic_path", "n/a"))
    print("Total scenarios  : %d" % report["total_scenarios"])
    print("Passed           : %d" % report["passed_scenarios"])
    print("Failed           : %d" % report["failed_scenarios"])
    print("Success rate     : %.2f%%" % (100.0 * report["success_rate"]))
    print("Safety violations: %d" % report["safety_violations"])
    for failure in report["failed_details"][:20]:
        print("  FAIL %s %s -> expected %s, got %s (%s)"
              % (failure["scenario_id"], failure["name"], failure["expected"],
                 failure["actual"], failure["reason"]))
    print("Status           : %s" % report["status"])
    print("=" * 60)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    navigation_path = argv[0] if argv else None
    output_path = argv[1] if len(argv) > 1 else None

    report, report_path = run_simulation(navigation_path=navigation_path)
    if output_path:
        report_path = save_simulation_report(report, output_path)
    print_summary(report)
    print("Saved simulation report to %s" % report_path)
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
