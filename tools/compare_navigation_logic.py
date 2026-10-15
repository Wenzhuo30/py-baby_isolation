"""
compare_navigation_logic.py
===========================
A/B comparison of two navigation-logic implementations over the same IR-SIM
worlds.

Motivation: a locally hosted model (Ollama, qwen3:8b) *can* implement
``decide_next_move``, but whether it produces logic that is as safe and as
efficient as the deterministic implementation is an empirical question. This
script answers it with the project's own benchmark instead of an opinion.

Both implementations are measured with ``benchmark_irsim.run_benchmark`` against
the same world files, so success rate, efficiency rate and average steps are
directly comparable.

Usage:
    python compare_navigation_logic.py A.py B.py [--worlds w1.yaml w2.yaml]
                                         [--label-a NAME] [--label-b NAME]
                                         [--out artifacts/logic_ab_comparison.json]

Exit code is always 0: this is a measurement, not a gate.
"""

import argparse
import json
import os
import sys


import os
import sys

# tools/ holds helper scripts, so the repository root is one level up. Importing
# the agents (analyst_agent, runner, test_irsim_with_agent, ...) requires the
# root on sys.path; without this, running a script from tools/ fails with
# ModuleNotFoundError.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

DEFAULT_OUT = os.path.join(ROOT, "artifacts", "logic_ab_comparison.json")

METRICS = ("total_worlds", "goals_reached", "success_rate", "efficient_worlds",
           "inefficient_success_worlds", "failed_worlds", "efficiency_rate",
           "average_steps_taken", "total_steps_taken")


def _load_logic(path):
    """Import one navigation-logic file and return its decide_next_move."""
    import importlib.util

    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError("navigation logic not found: %s" % path)

    name = "ab_logic_%s" % os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fn = getattr(module, "decide_next_move", None)
    if not callable(fn):
        raise AttributeError("%s does not define decide_next_move(state)" % path)
    return fn


def _scenario_check(fn):
    """Cheap, model-independent check across all 64 states: safety + agreement.

    Uses the same policy runner.py uses, so a difference here means a real
    behavioural difference rather than a benchmarking artefact.
    """
    from runner import build_scenarios, VALID_ACTIONS

    unsafe = []
    valid_action_failures = []
    exceptions = []
    differs_from_reference = []

    for scenario in build_scenarios():
        state = scenario["state"]
        acceptable = scenario["acceptable_actions"]
        try:
            action = fn(dict(state))
        except Exception as error:
            exceptions.append({"name": scenario["name"],
                               "error": "%s: %s" % (type(error).__name__, error)})
            continue

        if action not in VALID_ACTIONS:
            valid_action_failures.append({"name": scenario["name"], "action": action})
            continue

        blocked_key = {"FORWARD": "blocked_front", "LEFT": "blocked_left",
                       "RIGHT": "blocked_right"}.get(action)
        if blocked_key and state[blocked_key]:
            unsafe.append({"name": scenario["name"], "action": action,
                           "blocked": blocked_key})
        if action not in acceptable:
            differs_from_reference.append({"name": scenario["name"],
                                           "expected": scenario["expected"],
                                           "acceptable": acceptable,
                                           "action": action})

    return {
        "verified": True,
        "total_scenarios": 64,
        "unsafe_decisions": len(unsafe),
        "invalid_actions": len(valid_action_failures),
        "exceptions": len(exceptions),
        "differs_from_best_policy": len(differs_from_reference),
        "unsafe_details": unsafe[:10],
        "differ_details": differs_from_reference[:10],
    }


def measure(label, path, world_files, verbose=False):
    """Run the full IR-SIM benchmark for one implementation."""
    from benchmark_irsim import run_benchmark

    print("=" * 74)
    print("MEASURING %s" % label)
    print("  file : %s" % os.path.relpath(os.path.abspath(path), ROOT))
    print("  worlds: %d" % len(world_files))
    print("=" * 74)

    report = run_benchmark(world_files=world_files, navigation_path=path,
                           verbose=verbose)

    metrics = {key: report.get(key) for key in METRICS}
    per_world = [
        {
            "world_file": os.path.basename(str(r.get("world_file", "?"))),
            "reached_goal": r.get("reached_goal"),
            "steps_taken": r.get("steps_taken"),
            "efficiency_status": r.get("efficiency_status"),
            "collision_or_done": r.get("collision_or_done"),
        }
        for r in report.get("results", [])
    ]
    return {
        "label": label,
        "file": os.path.relpath(os.path.abspath(path), ROOT),
        "metrics": metrics,
        "per_world": per_world,
        "scenario_check": _scenario_check(_load_logic(path)),
    }


def _fmt(value):
    if isinstance(value, float):
        return "%.3f" % value
    return str(value)


def print_comparison(results):
    print()
    print("=" * 74)
    print("A/B COMPARISON")
    print("=" * 74)

    labels = [r["label"] for r in results]
    width = max(18, max(len(l) for l in labels) + 2)
    print("%-28s %s" % ("metric", "".join("%-*s" % (width, l) for l in labels)))
    print("-" * 74)
    for metric in METRICS:
        row = "".join("%-*s" % (width, _fmt(r["metrics"].get(metric)))
                      for r in results)
        print("%-28s %s" % (metric, row))

    print("-" * 74)
    print("%-28s %s" % ("per-world steps",
                        "".join("%-*s" % (width, l) for l in labels)))
    world_names = [w["world_file"] for w in results[0]["per_world"]]
    for index, world in enumerate(world_names):
        cells = []
        for result in results:
            entry = result["per_world"][index] if index < len(result["per_world"]) else {}
            mark = "ok" if entry.get("reached_goal") else "MISS"
            cells.append("%s %s" % (entry.get("steps_taken"), mark))
        print("%-28s %s" % (world, "".join("%-*s" % (width, c) for c in cells)))

    print("-" * 74)
    print("64-state policy check (safety is the hard requirement)")
    for result in results:
        check = result["scenario_check"]
        print("  %-*s unsafe=%s invalid=%s exceptions=%s differs_from_best=%s"
              % (width, result["label"], check["unsafe_decisions"],
                 check["invalid_actions"], check["exceptions"],
                 check["differs_from_best_policy"]))
    print("=" * 74)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare two navigation logics.")
    parser.add_argument("logic_a", help="baseline navigation logic (.py)")
    parser.add_argument("logic_b", help="candidate navigation logic (.py)")
    parser.add_argument("--label-a", default=None)
    parser.add_argument("--label-b", default=None)
    parser.add_argument("--worlds", nargs="*", default=None,
                        help="world files (default: every world in irsim_worlds/)")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--verbose", action="store_true",
                        help="echo the per-world simulation output")
    args = parser.parse_args(argv)

    from benchmark_irsim import resolve_world_files

    world_files = resolve_world_files(args.worlds)
    if not world_files:
        print("no world files found in irsim_worlds/")
        return 1

    label_a = args.label_a or os.path.splitext(os.path.basename(args.logic_a))[0]
    label_b = args.label_b or os.path.splitext(os.path.basename(args.logic_b))[0]

    results = [
        measure(label_a, args.logic_a, world_files, verbose=args.verbose),
        measure(label_b, args.logic_b, world_files, verbose=args.verbose),
    ]

    print_comparison(results)

    # verdict: goal completion first, then efficiency, then step count
    a, b = results
    verdict = []
    for metric, better in (("goals_reached", "higher"), ("efficiency_rate", "higher"),
                           ("average_steps_taken", "lower")):
        va, vb = a["metrics"].get(metric), b["metrics"].get(metric)
        if va is None or vb is None or va == vb:
            continue
        winner = a["label"] if ((va > vb) == (better == "higher")) else b["label"]
        verdict.append("%s: %s (%s vs %s)" % (metric, winner, _fmt(va), _fmt(vb)))
    if not verdict:
        verdict.append("the two implementations scored identically on every metric")

    print()
    print("VERDICT")
    for line in verdict:
        print("  * %s" % line)

    output = {
        "worlds": world_files,
        "results": results,
        "verdict": verdict,
        "world_files": world_files,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print()
    print("comparison written to %s" % os.path.relpath(args.out, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
